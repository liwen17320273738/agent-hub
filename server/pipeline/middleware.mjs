/**
 * Middleware Pipeline — deer-flow 风格的中间件管道
 *
 * 每次 LLM 调用前后，依次执行中间件链：
 *   TokenBudget → Guardrail → LoopDetection → Memory → ErrorHandling
 *
 * 中间件可以拦截/修改请求、记录日志、或阻止执行。
 */

import { emitPipelineEvent } from '../events.mjs'

const middlewareRegistry = new Map()
const executionHistory = new Map()

/**
 * 注册中间件
 * @param {string} name
 * @param {{ before?: Function, after?: Function, wrapCall?: Function }} hooks
 */
export function registerMiddleware(name, hooks) {
  middlewareRegistry.set(name, hooks)
}

/**
 * 执行中间件管道包裹的 LLM 调用
 */
export async function runMiddlewarePipeline(agentRole, llmCallFn, context = {}) {
  const middlewares = [...middlewareRegistry.values()]
  const ctx = {
    ...context,
    agentRole,
    startTime: Date.now(),
    requestId: `req-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  }

  // before hooks
  for (const mw of middlewares) {
    if (mw.before) {
      const decision = await mw.before(ctx)
      if (decision?.block) {
        emitPipelineEvent('middleware:blocked', {
          middleware: mw.name || 'unknown',
          reason: decision.reason,
          ...ctx,
        })
        return { ok: false, error: `[Middleware] ${decision.reason}`, blocked: true }
      }
    }
  }

  // execute LLM call
  let result
  try {
    result = await llmCallFn(ctx)
  } catch (error) {
    result = { ok: false, error: error.message }
  }

  // after hooks
  ctx.result = result
  ctx.duration = Date.now() - ctx.startTime
  for (const mw of middlewares) {
    if (mw.after) {
      await mw.after(ctx)
    }
  }

  return result
}

// ===== 内置中间件 =====

registerMiddleware('token-usage', {
  name: 'token-usage',
  after: async (ctx) => {
    const usage = ctx.result?.tokenUsage
    if (usage) {
      emitPipelineEvent('middleware:token-usage', {
        requestId: ctx.requestId,
        agentRole: ctx.agentRole,
        taskId: ctx.taskId,
        tokens: usage,
        duration: ctx.duration,
      })
    }
  },
})

registerMiddleware('guardrail', {
  name: 'guardrail',
  before: async (ctx) => {
    const blocked = getGuardrailPolicy(ctx)
    if (blocked) return { block: true, reason: blocked }
    return null
  },
})

registerMiddleware('loop-detection', {
  name: 'loop-detection',
  before: async (ctx) => {
    const key = `${ctx.taskId}:${ctx.agentRole}`
    const history = executionHistory.get(key) || []

    const recentWindow = history.slice(-5)
    const duplicateCount = recentWindow.filter(h =>
      h.stage === ctx.stage && Date.now() - h.time < 60000
    ).length

    if (duplicateCount >= 4) {
      return { block: true, reason: `检测到循环: ${ctx.agentRole} 在 ${ctx.stage} 阶段重复执行 ${duplicateCount} 次` }
    }

    history.push({ stage: ctx.stage, time: Date.now() })
    if (history.length > 20) history.splice(0, history.length - 20)
    executionHistory.set(key, history)
    return null
  },
})

registerMiddleware('error-formatting', {
  name: 'error-formatting',
  after: async (ctx) => {
    if (!ctx.result?.ok && ctx.result?.error) {
      const original = ctx.result.error
      if (original.includes('ECONNREFUSED')) {
        ctx.result.error = `LLM 服务连接失败，请检查 LLM_API_URL 配置。原始错误: ${original}`
      } else if (original.includes('401') || original.includes('403')) {
        ctx.result.error = `LLM 认证失败，请检查 LLM_API_KEY。原始错误: ${original}`
      } else if (original.includes('429')) {
        ctx.result.error = `LLM 请求频率超限，请稍后重试。原始错误: ${original}`
      }
    }
  },
})

function getGuardrailPolicy(ctx) {
  if (ctx.agentRole === 'executor' && !process.env.ALLOW_EXECUTOR) {
    return '执行者角色需要显式启用 ALLOW_EXECUTOR=1'
  }
  return null
}

// ===== Self-Verification Middleware =====

const STAGE_REQUIREMENTS = {
  planning: { sections: ['目标', '范围', '用户故事', '验收'], minLength: 500 },
  architecture: { sections: ['技术选型', '架构', 'API', '实现步骤', '风险'], minLength: 800 },
  testing: { sections: ['测试', '用例', '边界'], minLength: 400, mustContainAny: ['PASS', 'NEEDS WORK'] },
  reviewing: { sections: ['评估', '验收'], minLength: 300, mustContainAny: ['APPROVED', 'REJECTED'] },
}

registerMiddleware('self-verify', {
  name: 'self-verify',
  after: async (ctx) => {
    const content = ctx.result?.content
    if (!content || !ctx.result?.ok) return

    const stageId = ctx.stage || ctx.stageId
    const reqs = STAGE_REQUIREMENTS[stageId]
    if (!reqs) return

    const checks = []

    // Length check
    if (content.length < reqs.minLength) {
      checks.push({ check: 'length', status: content.length < reqs.minLength * 0.5 ? 'fail' : 'warn', message: `内容偏短 (${content.length}/${reqs.minLength})` })
    } else {
      checks.push({ check: 'length', status: 'pass', message: `长度: ${content.length}` })
    }

    // Required sections check
    const missing = reqs.sections.filter(s => !content.includes(s))
    if (missing.length > 0) {
      checks.push({ check: 'sections', status: missing.length > reqs.sections.length * 0.5 ? 'fail' : 'warn', message: `缺少: ${missing.join(', ')}` })
    } else {
      checks.push({ check: 'sections', status: 'pass', message: '包含所有必要章节' })
    }

    // Must-contain keywords
    if (reqs.mustContainAny) {
      const found = reqs.mustContainAny.some(kw => content.includes(kw))
      checks.push({ check: 'keywords', status: found ? 'pass' : 'fail', message: found ? '包含结论关键词' : `缺少结论: ${reqs.mustContainAny.join(' / ')}` })
    }

    // Placeholder check
    const placeholders = ['TODO', 'TBD', 'FIXME', '[待补充]']
    const foundPH = placeholders.filter(p => content.toLowerCase().includes(p.toLowerCase()))
    if (foundPH.length > 0) {
      checks.push({ check: 'placeholder', status: 'warn', message: `包含占位符: ${foundPH.join(', ')}` })
    }

    const overall = checks.some(c => c.status === 'fail') ? 'fail' : checks.some(c => c.status === 'warn') ? 'warn' : 'pass'

    ctx.result.verification = { overall, checks, autoProceed: overall !== 'fail' }

    emitPipelineEvent('middleware:self-verify', {
      requestId: ctx.requestId,
      taskId: ctx.taskId,
      stageId,
      agentRole: ctx.agentRole,
      verification: ctx.result.verification,
    })
  },
})

// ===== Guardrail Approval Middleware =====

const pendingApprovals = new Map()
const auditLog = []

const IRREVERSIBLE_ACTIONS = new Set(['deploy_production', 'delete_data', 'publish_release', 'merge_to_main'])

registerMiddleware('guardrail-approval', {
  name: 'guardrail-approval',
  before: async (ctx) => {
    const action = ctx.action
    if (!action || !IRREVERSIBLE_ACTIONS.has(action)) return null

    const approvalId = `approval-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
    pendingApprovals.set(approvalId, {
      id: approvalId,
      taskId: ctx.taskId,
      action,
      role: ctx.agentRole,
      status: 'pending',
      createdAt: Date.now(),
    })

    auditLog.push({ action, role: ctx.agentRole, taskId: ctx.taskId, outcome: 'pending_approval', time: Date.now() })

    emitPipelineEvent('guardrail:approval-required', {
      approvalId,
      taskId: ctx.taskId,
      action,
      role: ctx.agentRole,
    })

    return { block: true, reason: `操作 ${action} 需要人工审批 (approval: ${approvalId})` }
  },
})

export function resolveApproval(approvalId, approved, reviewer) {
  const approval = pendingApprovals.get(approvalId)
  if (!approval) return null
  approval.status = approved ? 'approved' : 'rejected'
  approval.reviewer = reviewer
  approval.resolvedAt = Date.now()
  auditLog.push({ action: approval.action, role: reviewer, taskId: approval.taskId, outcome: approval.status, time: Date.now() })
  return approval
}

export function getPendingApprovals() { return [...pendingApprovals.values()].filter(a => a.status === 'pending') }
export function getAuditLog(limit = 100) { return auditLog.slice(-limit) }

// ===== Observability Trace Middleware =====

const traces = new Map()

registerMiddleware('trace', {
  name: 'trace',
  before: async (ctx) => {
    ctx._traceStart = Date.now()
    ctx._spanId = `span-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
  },
  after: async (ctx) => {
    const duration = Date.now() - (ctx._traceStart || ctx.startTime)
    const span = {
      spanId: ctx._spanId,
      taskId: ctx.taskId,
      stageId: ctx.stage || ctx.stageId,
      role: ctx.agentRole,
      model: ctx.result?.model || '',
      tier: ctx.result?.tier || '',
      status: ctx.result?.ok ? 'completed' : 'failed',
      durationMs: duration,
      promptTokens: ctx.result?.tokenUsage?.prompt_tokens || ctx.result?.tokenUsage?.input_tokens || 0,
      completionTokens: ctx.result?.tokenUsage?.completion_tokens || ctx.result?.tokenUsage?.output_tokens || 0,
      verification: ctx.result?.verification || null,
      timestamp: Date.now(),
    }
    span.totalTokens = span.promptTokens + span.completionTokens

    const traceKey = ctx.taskId || 'global'
    if (!traces.has(traceKey)) traces.set(traceKey, [])
    traces.get(traceKey).push(span)

    emitPipelineEvent('middleware:trace', {
      ...span,
      requestId: ctx.requestId,
    })
  },
})

export function getTracesByTask(taskId) { return traces.get(taskId) || [] }
export function getAllTraces() {
  const all = []
  for (const [taskId, spans] of traces) {
    all.push({ taskId, spans: spans.length, lastSpan: spans[spans.length - 1] })
  }
  return all
}

export function getMiddlewareStats() {
  const stats = {}
  for (const [key, history] of executionHistory.entries()) {
    stats[key] = {
      totalCalls: history.length,
      lastCall: history[history.length - 1]?.time,
    }
  }
  stats._traces = { taskCount: traces.size, totalSpans: [...traces.values()].reduce((n, s) => n + s.length, 0) }
  stats._approvals = { pending: getPendingApprovals().length, auditLogSize: auditLog.length }
  return stats
}
