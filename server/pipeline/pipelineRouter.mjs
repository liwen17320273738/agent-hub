import { Router } from 'express'
import {
  createTask,
  advanceTask,
  rejectTask,
  addArtifact,
  updateStageOutput,
  PIPELINE_STAGES,
} from './taskModel.mjs'
import { getAllTasks, getTask, saveTask, deleteTask } from './taskStore.mjs'
import { emitPipelineEvent } from '../events.mjs'
import { runStage, runFullPipeline, resumePipelineAfterBuild } from './orchestrator.mjs'
import { analyzeAndDecompose, runSmartPipeline } from './leadAgent.mjs'
import { listSkills, toggleSkill, ensureSkillsDirs } from './skills.mjs'
import {
  getMiddlewareStats,
  resolveApproval,
  getPendingApprovals,
  getAuditLog,
  getTracesByTask,
  getAllTraces,
} from './middleware.mjs'
import { resolveModelForRole } from './llmBridge.mjs'

ensureSkillsDirs().catch(() => {})

const router = Router()

router.get('/stages', (_req, res) => {
  res.json({ stages: PIPELINE_STAGES })
})

router.get('/tasks', async (req, res, next) => {
  try {
    const { status, stage, source } = req.query
    const tasks = await getAllTasks({ status, stage, source })
    res.json({ tasks })
  } catch (e) { next(e) }
})

router.post('/tasks', async (req, res, next) => {
  try {
    const { title, description, source, sourceMessageId, sourceUserId } = req.body
    if (!title?.trim()) {
      return res.status(400).json({ error: '任务标题不能为空' })
    }
    const task = createTask({
      title: title.trim(),
      description: description || '',
      source,
      sourceMessageId,
      sourceUserId,
      createdBy: req.user?.id || 'system',
    })
    await saveTask(task)
    emitPipelineEvent('task:created', task)
    res.status(201).json({ task })
  } catch (e) { next(e) }
})

router.get('/tasks/:id', async (req, res, next) => {
  try {
    const task = await getTask(req.params.id)
    if (!task) return res.status(404).json({ error: '任务不存在' })
    res.json({ task })
  } catch (e) { next(e) }
})

router.patch('/tasks/:id', async (req, res, next) => {
  try {
    const task = await getTask(req.params.id)
    if (!task) return res.status(404).json({ error: '任务不存在' })

    const allowed = ['title', 'description', 'status']
    const updates = {}
    for (const key of allowed) {
      if (req.body[key] !== undefined) updates[key] = req.body[key]
    }

    const updated = { ...task, ...updates, updatedAt: Date.now() }
    await saveTask(updated)
    emitPipelineEvent('task:updated', updated)
    res.json({ task: updated })
  } catch (e) { next(e) }
})

router.delete('/tasks/:id', async (req, res, next) => {
  try {
    const task = await getTask(req.params.id)
    if (!task) return res.status(404).json({ error: '任务不存在' })
    await deleteTask(req.params.id)
    emitPipelineEvent('task:deleted', { id: req.params.id })
    res.json({ ok: true })
  } catch (e) { next(e) }
})

router.post('/tasks/:id/advance', async (req, res, next) => {
  try {
    const task = await getTask(req.params.id)
    if (!task) return res.status(404).json({ error: '任务不存在' })

    const { output } = req.body
    let current = task
    if (output) {
      current = updateStageOutput(current, current.currentStageId, output)
    }

    const result = advanceTask(current)
    if (!result.ok) return res.status(400).json({ error: result.error })

    await saveTask(result.task)
    emitPipelineEvent('task:stage-advanced', {
      taskId: result.task.id,
      from: task.currentStageId,
      to: result.task.currentStageId,
      task: result.task,
    })
    res.json({ task: result.task })
  } catch (e) { next(e) }
})

router.post('/tasks/:id/reject', async (req, res, next) => {
  try {
    const task = await getTask(req.params.id)
    if (!task) return res.status(404).json({ error: '任务不存在' })

    const { targetStageId, reason } = req.body
    if (!targetStageId) return res.status(400).json({ error: '请指定打回到哪个阶段' })

    const result = rejectTask(task, targetStageId)
    if (!result.ok) return res.status(400).json({ error: result.error })

    await saveTask(result.task)
    emitPipelineEvent('task:rejected', {
      taskId: result.task.id,
      from: task.currentStageId,
      to: targetStageId,
      reason,
      task: result.task,
    })
    res.json({ task: result.task })
  } catch (e) { next(e) }
})

router.post('/tasks/:id/artifacts', async (req, res, next) => {
  try {
    const task = await getTask(req.params.id)
    if (!task) return res.status(404).json({ error: '任务不存在' })

    const { type, name, content, stageId } = req.body
    if (!type || !name || !content) {
      return res.status(400).json({ error: '缺少 type, name 或 content' })
    }

    const updated = addArtifact(task, {
      type,
      name,
      content,
      stageId: stageId || task.currentStageId,
    })
    await saveTask(updated)
    emitPipelineEvent('task:artifact-added', {
      taskId: updated.id,
      artifact: updated.artifacts[updated.artifacts.length - 1],
    })
    res.json({ task: updated })
  } catch (e) { next(e) }
})

router.post('/tasks/:id/stage-output', async (req, res, next) => {
  try {
    const task = await getTask(req.params.id)
    if (!task) return res.status(404).json({ error: '任务不存在' })

    const { stageId, output } = req.body
    if (!stageId || output === undefined) {
      return res.status(400).json({ error: '缺少 stageId 或 output' })
    }

    const updated = updateStageOutput(task, stageId, output)
    await saveTask(updated)
    res.json({ task: updated })
  } catch (e) { next(e) }
})

router.post('/tasks/:id/run-stage', async (req, res, next) => {
  try {
    const task = await getTask(req.params.id)
    if (!task) return res.status(404).json({ error: '任务不存在' })

    const stageId = req.body.stageId || task.currentStageId

    emitPipelineEvent('stage:queued', { taskId: task.id, stageId })

    res.json({ ok: true, message: `阶段 ${stageId} 已开始处理`, taskId: task.id, stageId })

    runStage(task.id, stageId).catch(e => {
      console.error(`[orchestrator] run-stage 异常:`, e.message)
      emitPipelineEvent('stage:error', { taskId: task.id, stageId, error: e.message })
    })
  } catch (e) { next(e) }
})

router.post('/tasks/:id/auto-run', async (req, res, next) => {
  try {
    const task = await getTask(req.params.id)
    if (!task) return res.status(404).json({ error: '任务不存在' })

    emitPipelineEvent('pipeline:auto-queued', { taskId: task.id })

    res.json({ ok: true, message: '全自动流水线已启动', taskId: task.id })

    runFullPipeline(task.id).catch(e => {
      console.error(`[orchestrator] auto-run 异常:`, e.message)
      emitPipelineEvent('pipeline:auto-error', { taskId: task.id, error: e.message })
    })
  } catch (e) { next(e) }
})

router.post('/tasks/:id/resume-after-build', async (req, res, next) => {
  try {
    const task = await getTask(req.params.id)
    if (!task) return res.status(404).json({ error: '任务不存在' })

    res.json({ ok: true, message: '从 building 阶段恢复继续', taskId: task.id })

    resumePipelineAfterBuild(task.id).catch(e => {
      console.error(`[orchestrator] resume 异常:`, e.message)
      emitPipelineEvent('pipeline:auto-error', { taskId: task.id, error: e.message })
    })
  } catch (e) { next(e) }
})

// ===== Lead Agent 智能流水线 (deer-flow 风格) =====

router.post('/tasks/:id/smart-run', async (req, res, next) => {
  try {
    const task = await getTask(req.params.id)
    if (!task) return res.status(404).json({ error: '任务不存在' })

    emitPipelineEvent('pipeline:smart-queued', { taskId: task.id })

    res.json({ ok: true, message: 'Lead Agent 智能流水线已启动', taskId: task.id })

    runSmartPipeline(task.id).catch(e => {
      console.error(`[lead-agent] smart-run 异常:`, e.message)
      emitPipelineEvent('pipeline:smart-error', { taskId: task.id, error: e.message })
    })
  } catch (e) { next(e) }
})

router.post('/tasks/:id/analyze', async (req, res, next) => {
  try {
    const task = await getTask(req.params.id)
    if (!task) return res.status(404).json({ error: '任务不存在' })

    res.json({ ok: true, message: 'Lead Agent 正在分析...', taskId: task.id })

    analyzeAndDecompose(task.id).catch(e => {
      console.error(`[lead-agent] analyze 异常:`, e.message)
      emitPipelineEvent('lead-agent:error', { taskId: task.id, error: e.message })
    })
  } catch (e) { next(e) }
})

// ===== Skills 技能系统 =====

router.get('/skills', async (_req, res, next) => {
  try {
    const skills = await listSkills()
    res.json({ skills })
  } catch (e) { next(e) }
})

router.put('/skills/:name', async (req, res, next) => {
  try {
    const { enabled } = req.body
    if (typeof enabled !== 'boolean') {
      return res.status(400).json({ error: 'enabled 必须是布尔值' })
    }
    const result = await toggleSkill(req.params.name, enabled)
    res.json(result)
  } catch (e) { next(e) }
})

// ===== 中间件监控 =====

router.get('/middleware/stats', (_req, res) => {
  res.json({ stats: getMiddlewareStats() })
})

// ===== Observability: Traces =====

router.get('/traces', (_req, res) => {
  res.json({ traces: getAllTraces() })
})

router.get('/traces/:taskId', (req, res) => {
  const spans = getTracesByTask(req.params.taskId)
  res.json({ taskId: req.params.taskId, spans })
})

// ===== Guardrail: Approvals =====

router.get('/approvals', (_req, res) => {
  res.json({ approvals: getPendingApprovals() })
})

router.post('/approvals/:id/resolve', (req, res) => {
  const { approved, reviewer, comment } = req.body
  if (typeof approved !== 'boolean') return res.status(400).json({ error: 'approved 必须是布尔值' })
  const result = resolveApproval(req.params.id, approved, reviewer || req.user?.id || 'system')
  if (!result) return res.status(404).json({ error: '审批请求不存在' })
  res.json({ approval: result })
})

// ===== Audit Log =====

router.get('/audit-log', (req, res) => {
  const limit = parseInt(req.query.limit) || 100
  res.json({ entries: getAuditLog(limit) })
})

// ===== Planner-Worker: Model Resolution =====

router.post('/planner/resolve-model', (req, res) => {
  const { role, stageId } = req.body
  if (!role) return res.status(400).json({ error: '缺少 role 参数' })
  const resolution = resolveModelForRole(role, stageId)
  res.json({ resolution })
})

export default router
