import { advanceTask, updateStageOutput, addArtifact, PIPELINE_STAGES } from './taskModel.mjs'
import { getTask, saveTask } from './taskStore.mjs'
import { emitPipelineEvent } from '../events.mjs'
import { executeClaudeCode, buildExecutionPrompt, getJobsByTask } from '../executor/executorBridge.mjs'
import { callLLM } from './llmBridge.mjs'

const STAGE_PROMPTS = {
  planning: (task) => ({
    role: 'product-manager',
    system: `你是一位资深产品经理。根据以下需求，输出一份结构化 PRD，必须包含：
1. 需求概述（一句话描述核心价值）
2. 目标用户
3. 功能范围（IN-SCOPE / OUT-OF-SCOPE）
4. 用户故事（至少3条，格式: As a... I want... So that...）
5. 验收标准（可量化的条件列表）
6. 非功能需求（性能/安全/兼容性）
7. 里程碑和优先级

用 Markdown 格式输出。`,
    user: `## 需求标题\n${task.title}\n\n## 需求描述\n${task.description || '(无详细描述)'}`
  }),

  architecture: (task) => {
    const prdOutput = task.stages.find(s => s.id === 'planning')?.output || ''
    return {
      role: 'developer',
      system: `你是一位资深技术架构师。根据 PRD 输出技术方案，必须包含：
1. 技术选型和理由
2. 系统架构（组件/模块划分）
3. 数据模型设计
4. API 接口设计（RESTful 路由表）
5. 实现步骤（按优先级排序，每步预估工时）
6. 风险点和降级方案
7. 文件变更清单

用 Markdown 格式输出。不要写代码实现，只写方案。`,
      user: `## 需求标题\n${task.title}\n\n## PRD\n${prdOutput}`
    }
  },

  testing: (task) => {
    const prdOutput = task.stages.find(s => s.id === 'planning')?.output || ''
    const buildOutput = task.stages.find(s => s.id === 'building')?.output || ''
    return {
      role: 'qa-lead',
      system: `你是一位资深 QA 负责人。根据 PRD 和开发产出，输出测试验证报告，必须包含：
1. 测试范围
2. 测试用例清单（编号 + 步骤 + 预期结果）
3. 边界条件和异常场景
4. 回归关注点
5. 性能/安全验证项
6. 结论：PASS ✅ 或 NEEDS WORK ❌（附具体原因）

用 Markdown 格式输出。`,
      user: `## 需求标题\n${task.title}\n\n## PRD\n${prdOutput}\n\n## 开发产出\n${buildOutput}`
    }
  },

  reviewing: (task) => {
    const allOutputs = task.stages
      .filter(s => s.output && s.id !== 'reviewing')
      .map(s => `### ${s.label}\n${s.output}`)
      .join('\n\n')
    return {
      role: 'orchestrator',
      system: `你是项目总控。审查所有阶段产出，输出验收评审报告，必须包含：
1. 各阶段完成度评估（每个阶段打分 1-10）
2. 需求覆盖度检查
3. 质量风险评估
4. 验收结论：APPROVED ✅ 或 REJECTED ❌
5. 如 REJECTED，明确指出需要返回哪个阶段修改什么

用 Markdown 格式输出。`,
      user: `## 需求标题\n${task.title}\n\n## 各阶段产出\n${allOutputs}`
    }
  },
}

export async function runStage(taskId, stageId) {
  const task = await getTask(taskId)
  if (!task) return { ok: false, error: '任务不存在' }
  if (task.currentStageId !== stageId) return { ok: false, error: `任务当前不在 ${stageId} 阶段` }

  const stageConf = PIPELINE_STAGES.find(s => s.id === stageId)
  if (!stageConf) return { ok: false, error: '未知阶段' }

  emitPipelineEvent('stage:processing', {
    taskId, stageId, role: stageConf.ownerRole, label: stageConf.label,
  })

  if (stageId === 'intake') {
    const result = advanceTask(task)
    if (result.ok) {
      await saveTask(result.task)
      emitPipelineEvent('task:stage-advanced', {
        taskId, from: 'intake', to: 'planning', task: result.task,
      })
    }
    return result
  }

  if (stageId === 'building') {
    return runBuildingStage(task)
  }

  const promptFn = STAGE_PROMPTS[stageId]
  if (!promptFn) {
    return { ok: false, error: `阶段 ${stageId} 没有配置 AI 处理逻辑` }
  }

  const { system, user } = promptFn(task)

  const llmResult = await callLLM(system, user)
  if (!llmResult.ok) {
    emitPipelineEvent('stage:error', { taskId, stageId, error: llmResult.error })
    return { ok: false, error: llmResult.error }
  }

  let updated = updateStageOutput(task, stageId, llmResult.content)

  const artifactNames = {
    planning: 'PRD 文档',
    architecture: '技术方案',
    testing: '测试报告',
    reviewing: '验收评审报告',
  }

  updated = addArtifact(updated, {
    type: 'document',
    name: artifactNames[stageId] || `${stageConf.label}产出`,
    content: llmResult.content,
    stageId,
  })

  const advanced = advanceTask(updated)
  if (!advanced.ok) {
    await saveTask(updated)
    emitPipelineEvent('stage:completed', { taskId, stageId, output: llmResult.content })
    return { ok: true, task: updated, advanced: false }
  }

  await saveTask(advanced.task)
  emitPipelineEvent('stage:completed', { taskId, stageId, output: llmResult.content })
  emitPipelineEvent('task:stage-advanced', {
    taskId, from: stageId, to: advanced.task.currentStageId, task: advanced.task,
  })

  return { ok: true, task: advanced.task, advanced: true }
}

async function runBuildingStage(task) {
  const prompt = buildExecutionPrompt(task)

  emitPipelineEvent('stage:processing', {
    taskId: task.id, stageId: 'building', role: 'executor', label: '开发实现',
    mode: 'claude-code',
  })

  const job = executeClaudeCode({
    taskId: task.id,
    prompt,
    workDir: process.cwd(),
  })

  return { ok: true, task, jobId: job.id, mode: 'async-execution' }
}

export async function runFullPipeline(taskId) {
  const stages = ['intake', 'planning', 'architecture', 'building', 'testing', 'reviewing']

  emitPipelineEvent('pipeline:auto-start', { taskId })

  for (const stageId of stages) {
    const task = await getTask(taskId)
    if (!task) return { ok: false, error: '任务不存在' }
    if (task.status !== 'active') return { ok: false, error: '任务已非活跃状态', task }
    if (task.currentStageId !== stageId) {
      if (task.currentStageId === 'done') return { ok: true, task, completed: true }
      continue
    }

    console.log(`[orchestrator] 自动执行 ${task.title} → ${stageId}`)

    const result = await runStage(taskId, stageId)
    if (!result.ok) {
      emitPipelineEvent('pipeline:auto-error', { taskId, stageId, error: result.error })
      return { ok: false, error: result.error, stoppedAt: stageId }
    }

    if (stageId === 'building' && result.mode === 'async-execution') {
      emitPipelineEvent('pipeline:auto-paused', {
        taskId, stageId: 'building', reason: 'Claude Code 异步执行中，需要手动确认完成后继续',
        jobId: result.jobId,
      })
      return { ok: true, task: result.task, pausedAt: 'building', jobId: result.jobId }
    }
  }

  const finalTask = await getTask(taskId)
  emitPipelineEvent('pipeline:auto-completed', { taskId, task: finalTask })
  return { ok: true, task: finalTask, completed: true }
}

export async function resumePipelineAfterBuild(taskId) {
  const task = await getTask(taskId)
  if (!task) return { ok: false, error: '任务不存在' }
  if (task.currentStageId !== 'building') {
    return { ok: false, error: '任务不在 building 阶段' }
  }

  const jobs = getJobsByTask(taskId)
  const latestJob = jobs[0]

  let buildOutput = '(无 Claude Code 执行记录)'
  if (latestJob) {
    buildOutput = latestJob.output || latestJob.logs.map(l => l.text).join('')
    if (!buildOutput.trim()) buildOutput = `Claude Code 执行完成，退出码: ${latestJob.exitCode}`
  }

  let updated = updateStageOutput(task, 'building', buildOutput)
  updated = addArtifact(updated, {
    type: 'code',
    name: '开发实现记录',
    content: buildOutput.slice(0, 10000),
    stageId: 'building',
  })

  const advanced = advanceTask(updated)
  if (!advanced.ok) {
    await saveTask(updated)
    return { ok: false, error: advanced.error }
  }

  await saveTask(advanced.task)
  emitPipelineEvent('task:stage-advanced', {
    taskId, from: 'building', to: advanced.task.currentStageId, task: advanced.task,
  })

  const remaining = ['testing', 'reviewing']
  for (const stageId of remaining) {
    const t = await getTask(taskId)
    if (!t || t.currentStageId !== stageId || t.status !== 'active') break

    const result = await runStage(taskId, stageId)
    if (!result.ok) {
      emitPipelineEvent('pipeline:auto-error', { taskId, stageId, error: result.error })
      return { ok: false, error: result.error, stoppedAt: stageId }
    }
  }

  const finalTask = await getTask(taskId)
  emitPipelineEvent('pipeline:auto-completed', { taskId, task: finalTask })
  return { ok: true, task: finalTask }
}
