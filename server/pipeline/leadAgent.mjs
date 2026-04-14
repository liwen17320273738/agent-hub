/**
 * Lead Agent — deer-flow 风格的智能决策引擎
 *
 * 与固定管线不同，Lead Agent 分析需求后**动态决定**需要哪些子任务，
 * 可以并行派发多个 subagent，每个 subagent 拥有独立上下文和工具集。
 *
 * 灵感来源: bytedance/deer-flow 的 lead_agent + task_tool + SubagentExecutor
 */

import { randomUUID } from 'node:crypto'
import { getTask, saveTask } from './taskStore.mjs'
import { updateStageOutput, addArtifact, advanceTask } from './taskModel.mjs'
import { emitPipelineEvent } from '../events.mjs'
import { loadSkills } from './skills.mjs'
import { runMiddlewarePipeline } from './middleware.mjs'
import { callLLM } from './llmBridge.mjs'
import { executeClaudeCode, buildExecutionPrompt, getJobsByTask, killJob } from '../executor/executorBridge.mjs'

const LEAD_AGENT_SYSTEM = `你是 OpenClaw Lead Agent，AI 军团的总指挥。你的职责是：

1. **分析需求**：理解用户意图，判断复杂度
2. **任务分解**：将复杂需求拆分为可并行执行的子任务
3. **角色分配**：为每个子任务指定最合适的专家角色
4. **质量把控**：审查各子任务产出，决定是否通过

## 可用角色
- product-manager: 产品经理，负责 PRD、用户故事、验收标准
- developer: 技术架构师，负责技术方案、API 设计、数据模型
- executor: 开发执行者，负责代码实现（调用 Claude Code）
- qa-lead: QA 负责人，负责测试方案和验证
- orchestrator: 总控评审，负责验收

## 输出格式
你必须以 JSON 格式输出任务分解计划：
\`\`\`json
{
  "analysis": "对需求的理解和分析",
  "subtasks": [
    {
      "id": "subtask-1",
      "title": "子任务标题",
      "role": "product-manager",
      "prompt": "给该角色的详细指令",
      "dependsOn": [],
      "priority": 1
    }
  ],
  "strategy": "parallel | sequential | mixed",
  "estimatedComplexity": "low | medium | high"
}
\`\`\`

## 规则
- 简单需求(low)：1-2 个子任务即可
- 中等需求(medium)：3-4 个子任务，可并行
- 复杂需求(high)：5+ 个子任务，注意依赖关系
- 每次最多 5 个并行子任务
- 子任务的 prompt 必须包含充足上下文，子 agent 无法看到其他子任务的内容`

/**
 * Lead Agent 分析需求并生成子任务计划
 */
export async function analyzeAndDecompose(taskId) {
  const task = await getTask(taskId)
  if (!task) return { ok: false, error: '任务不存在' }

  emitPipelineEvent('lead-agent:analyzing', { taskId, title: task.title })

  const skills = await loadSkills()
  const skillContext = skills.length
    ? `\n\n## 已启用技能\n${skills.map(s => `- ${s.name}: ${s.description}`).join('\n')}`
    : ''

  const systemPrompt = LEAD_AGENT_SYSTEM + skillContext

  const previousOutputs = task.stages
    .filter(s => s.output)
    .map(s => `### ${s.label}\n${s.output}`)
    .join('\n\n')

  const userMessage = [
    `## 需求标题\n${task.title}`,
    `## 需求描述\n${task.description || '(无详细描述)'}`,
    `## 当前阶段\n${task.currentStageId}`,
    previousOutputs ? `## 已有产出\n${previousOutputs}` : '',
  ].filter(Boolean).join('\n\n')

  const result = await runMiddlewarePipeline('lead-agent', async () => {
    return callLLM(systemPrompt, userMessage)
  }, { taskId, stage: 'lead-agent' })

  if (!result.ok) {
    emitPipelineEvent('lead-agent:error', { taskId, error: result.error })
    return result
  }

  let plan
  try {
    const jsonMatch = result.content.match(/```json\s*([\s\S]*?)```/)
    const jsonStr = jsonMatch ? jsonMatch[1] : result.content
    plan = JSON.parse(jsonStr.trim())
  } catch {
    plan = {
      analysis: result.content,
      subtasks: [{
        id: 'subtask-1',
        title: task.title,
        role: 'product-manager',
        prompt: `请针对以下需求进行处理:\n${task.title}\n${task.description}`,
        dependsOn: [],
        priority: 1,
      }],
      strategy: 'sequential',
      estimatedComplexity: 'medium',
    }
  }

  emitPipelineEvent('lead-agent:plan-ready', {
    taskId,
    plan: {
      analysis: plan.analysis,
      subtaskCount: plan.subtasks.length,
      strategy: plan.strategy,
      complexity: plan.estimatedComplexity,
    },
  })

  return { ok: true, plan, rawAnalysis: result.content }
}

/**
 * SubtaskExecutor — 并发执行子任务（deer-flow 风格）
 *
 * 每个子任务拥有独立上下文，通过 SSE 实时汇报进度
 */
export async function executeSubtasks(taskId, subtasks) {
  const results = new Map()

  const groups = groupByDependency(subtasks)

  for (const group of groups) {
    emitPipelineEvent('subtasks:batch-start', {
      taskId,
      batchSize: group.length,
      subtaskIds: group.map(s => s.id),
    })

    const promises = group.map(subtask => executeOneSubtask(taskId, subtask, results))
    const batchResults = await Promise.allSettled(promises)

    for (let i = 0; i < group.length; i++) {
      const subtask = group[i]
      const settled = batchResults[i]
      if (settled.status === 'fulfilled') {
        results.set(subtask.id, settled.value)
      } else {
        results.set(subtask.id, {
          ok: false,
          error: settled.reason?.message || '执行失败',
          subtaskId: subtask.id,
        })
      }
    }
  }

  return Object.fromEntries(results)
}

async function executeOneSubtask(taskId, subtask, previousResults) {
  const subtaskId = subtask.id || randomUUID()

  emitPipelineEvent('subtask:start', {
    taskId,
    subtaskId,
    title: subtask.title,
    role: subtask.role,
  })

  let contextFromDeps = ''
  if (subtask.dependsOn?.length) {
    for (const depId of subtask.dependsOn) {
      const depResult = previousResults.get(depId)
      if (depResult?.ok) {
        contextFromDeps += `\n\n### 前置任务 [${depId}] 产出\n${depResult.content}`
      }
    }
  }

  const rolePrompts = {
    'product-manager': '你是一位资深产品经理，请输出结构化 PRD（包含用户故事、验收标准、功能范围、里程碑）。',
    'developer': '你是一位资深技术架构师，请输出技术方案（技术选型、数据模型、API 设计、实现步骤、风险点）。',
    'qa-lead': '你是一位资深 QA 负责人，请输出测试方案（测试用例、边界条件、回归关注点、PASS/FAIL 结论）。',
    'orchestrator': '你是项目总控，请审查所有产出并给出验收评审（打分、覆盖度、结论）。',
    'executor': '你是开发执行者，请列出需要执行的具体代码变更清单。',
  }

  const systemPrompt = rolePrompts[subtask.role] || '请处理以下任务。'
  const userPrompt = subtask.prompt + (contextFromDeps ? `\n\n---\n${contextFromDeps}` : '')

  const result = await runMiddlewarePipeline(subtask.role, async () => {
    return callLLM(systemPrompt, userPrompt)
  }, { taskId, subtaskId, role: subtask.role })

  if (result.ok) {
    emitPipelineEvent('subtask:completed', {
      taskId, subtaskId, title: subtask.title, role: subtask.role,
      outputLength: result.content.length,
    })
  } else {
    emitPipelineEvent('subtask:failed', {
      taskId, subtaskId, title: subtask.title, error: result.error,
    })
  }

  return { ...result, subtaskId, title: subtask.title, role: subtask.role }
}

function groupByDependency(subtasks) {
  const groups = []
  const done = new Set()
  let remaining = [...subtasks]

  while (remaining.length > 0) {
    const batch = remaining.filter(s =>
      !s.dependsOn?.length || s.dependsOn.every(d => done.has(d))
    )
    if (batch.length === 0) {
      groups.push(remaining)
      break
    }
    groups.push(batch)
    for (const s of batch) done.add(s.id)
    remaining = remaining.filter(s => !done.has(s.id))
  }

  return groups
}

/**
 * Lead Agent 驱动的全智能流水线
 * 替代 runFullPipeline，不再死板走固定阶段
 */
export async function runSmartPipeline(taskId) {
  const task = await getTask(taskId)
  if (!task) return { ok: false, error: '任务不存在' }

  emitPipelineEvent('pipeline:smart-start', { taskId, title: task.title })

  // Phase 1: Lead Agent 分析和分解
  const decomposition = await analyzeAndDecompose(taskId)
  if (!decomposition.ok) return decomposition

  const plan = decomposition.plan

  // 保存分析结果
  let updated = updateStageOutput(task, 'intake', decomposition.rawAnalysis)
  updated = addArtifact(updated, {
    type: 'document',
    name: 'Lead Agent 分析报告',
    content: decomposition.rawAnalysis,
    stageId: 'intake',
  })
  const adv = advanceTask(updated)
  if (adv.ok) updated = adv.task
  await saveTask(updated)
  emitPipelineEvent('task:stage-advanced', {
    taskId, from: 'intake', to: updated.currentStageId, task: updated,
  })

  // Phase 2: 执行子任务
  const subtaskResults = await executeSubtasks(taskId, plan.subtasks)

  // Phase 3: 收集产出、推进阶段
  let current = await getTask(taskId)
  const stageMapping = {
    'product-manager': 'planning',
    'developer': 'architecture',
    'executor': 'building',
    'qa-lead': 'testing',
    'orchestrator': 'reviewing',
  }

  for (const [, result] of Object.entries(subtaskResults)) {
    if (!result.ok) continue

    const targetStage = stageMapping[result.role]
    if (!targetStage) continue

    const stageExists = current.stages.find(s => s.id === targetStage)
    if (!stageExists) continue

    current = updateStageOutput(current, targetStage, result.content)
    current = addArtifact(current, {
      type: 'document',
      name: `${result.title}`,
      content: result.content,
      stageId: targetStage,
    })
  }

  // 按顺序推进到 building 之前的阶段
  const preBuilding = ['planning', 'architecture']
  for (const stageId of preBuilding) {
    if (current.currentStageId !== stageId) continue
    const stage = current.stages.find(s => s.id === stageId)
    if (!stage?.output) continue

    const result = advanceTask(current)
    if (result.ok) {
      current = result.task
      emitPipelineEvent('task:stage-advanced', {
        taskId, from: stageId, to: current.currentStageId, task: current,
      })
    }
  }

  await saveTask(current)

  // Phase 4: Building 阶段 — 真正调用 Claude Code 执行开发
  if (current.currentStageId === 'building') {
    console.log(`[lead-agent] 启动 Claude Code 执行开发任务: ${current.title}`)

    const prompt = buildExecutionPrompt(current)

    emitPipelineEvent('stage:processing', {
      taskId, stageId: 'building', role: 'executor', label: '开发实现',
      mode: 'claude-code',
    })

    const job = executeClaudeCode({
      taskId,
      prompt,
      workDir: process.cwd(),
    })

    emitPipelineEvent('executor:launched', {
      taskId, jobId: job.id, pid: job.pid,
      message: 'Claude Code 已启动，正在终端中执行开发任务...',
    })

    // 等待 Claude Code 执行完成（轮询，最长 15 分钟）
    const maxWait = 15 * 60 * 1000
    const pollInterval = 3000
    const startWait = Date.now()

    await new Promise((resolve) => {
      const poll = () => {
        if (job.status === 'done' || job.status === 'failed' || job.status === 'error' || job.status === 'killed') {
          resolve()
          return
        }
        if (Date.now() - startWait > maxWait) {
          console.log('[lead-agent] Claude Code 执行超时 (15min)，正在终止进程...')
          try { killJob(job.id) } catch {}
          emitPipelineEvent('executor:timeout', { taskId, jobId: job.id })
          resolve()
          return
        }

        // 每 30 秒输出一次进度日志
        const elapsed = Math.round((Date.now() - startWait) / 1000)
        if (elapsed % 30 === 0 && elapsed > 0) {
          const logCount = job.logs.length
          const logChars = job.logs.reduce((n, l) => n + (l.text?.length || 0), 0)
          console.log(`[lead-agent] Claude Code 运行中 ${elapsed}s, logs=${logCount}, chars=${logChars}`)
        }

        setTimeout(poll, pollInterval)
      }
      poll()
    })

    // 收集 Claude Code 产出
    const stdoutLogs = job.logs.filter(l => l.type === 'stdout').map(l => l.text).join('')
    const stderrLogs = job.logs.filter(l => l.type === 'stderr').map(l => l.text).join('')
    let buildOutput = job.output || stdoutLogs
    if (!buildOutput.trim() && stderrLogs.trim()) {
      buildOutput = `[stderr]\n${stderrLogs}`
    }
    if (!buildOutput.trim()) {
      buildOutput = `Claude Code 执行完成，退出码: ${job.exitCode}, logs: ${job.logs.length}`
    }

    current = await getTask(taskId)
    current = updateStageOutput(current, 'building', buildOutput)
    current = addArtifact(current, {
      type: 'code',
      name: '开发实现记录 (Claude Code)',
      content: buildOutput.slice(0, 30000),
      stageId: 'building',
    })

    emitPipelineEvent('stage:completed', { taskId, stageId: 'building', exitCode: job.exitCode })

    const advBuild = advanceTask(current)
    if (advBuild.ok) {
      current = advBuild.task
      emitPipelineEvent('task:stage-advanced', {
        taskId, from: 'building', to: current.currentStageId, task: current,
      })
    }

    await saveTask(current)
  }

  // Phase 5: Building 之后，如果 testing/reviewing 还没产出，用 LLM 补齐
  current = await getTask(taskId)
  const postBuilding = ['testing', 'reviewing']
  for (const stageId of postBuilding) {
    if (current.currentStageId !== stageId || current.status !== 'active') break

    const stage = current.stages.find(s => s.id === stageId)
    if (stage?.output) {
      // 已有产出（子任务提前跑的），直接推进
      const result = advanceTask(current)
      if (result.ok) {
        current = result.task
        emitPipelineEvent('task:stage-advanced', {
          taskId, from: stageId, to: current.currentStageId, task: current,
        })
        await saveTask(current)
      }
      continue
    }

    // 需要用 LLM 补一轮
    emitPipelineEvent('stage:processing', { taskId, stageId, role: stageId === 'testing' ? 'qa-lead' : 'orchestrator' })

    const rolePrompts = {
      testing: {
        system: `你是一位资深 QA 负责人。根据 PRD 和开发产出，输出测试验证报告（测试用例、边界条件、结论）。用 Markdown 格式。`,
        user: () => {
          const prd = current.stages.find(s => s.id === 'planning')?.output || ''
          const build = current.stages.find(s => s.id === 'building')?.output || ''
          return `## ${current.title}\n\n### PRD\n${prd}\n\n### 开发产出\n${build}`
        },
      },
      reviewing: {
        system: `你是项目总控。审查所有阶段产出，输出验收评审报告（打分 1-10、覆盖度、结论 APPROVED/REJECTED）。用 Markdown 格式。`,
        user: () => {
          const allOutputs = current.stages
            .filter(s => s.output && s.id !== 'reviewing')
            .map(s => `### ${s.label}\n${s.output}`)
            .join('\n\n')
          return `## ${current.title}\n\n${allOutputs}`
        },
      },
    }

    const promptConf = rolePrompts[stageId]
    if (!promptConf) continue

    const llmResult = await callLLM(promptConf.system, promptConf.user())
    if (llmResult.ok) {
      current = updateStageOutput(current, stageId, llmResult.content)
      current = addArtifact(current, {
        type: 'document',
        name: stageId === 'testing' ? '测试报告 (post-build)' : '验收评审报告',
        content: llmResult.content,
        stageId,
      })
      emitPipelineEvent('stage:completed', { taskId, stageId })

      const adv2 = advanceTask(current)
      if (adv2.ok) {
        current = adv2.task
        emitPipelineEvent('task:stage-advanced', {
          taskId, from: stageId, to: current.currentStageId, task: current,
        })
      }
      await saveTask(current)
    }
  }

  await saveTask(current)

  emitPipelineEvent('pipeline:smart-completed', {
    taskId,
    finalStage: current.currentStageId,
    status: current.status,
    subtaskCount: plan.subtasks.length,
    completedSubtasks: Object.values(subtaskResults).filter(r => r.ok).length,
  })

  return {
    ok: true,
    task: current,
    plan,
    subtaskResults,
  }
}
