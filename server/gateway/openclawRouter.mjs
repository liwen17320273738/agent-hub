import { Router } from 'express'
import { createTask, advanceTask } from '../pipeline/taskModel.mjs'
import { saveTask } from '../pipeline/taskStore.mjs'
import { emitPipelineEvent } from '../events.mjs'

const router = Router()

const OPENCLAW_GATEWAY_SECRET = () => process.env.OPENCLAW_GATEWAY_SECRET?.trim() || ''

router.use((req, res, next) => {
  const need = OPENCLAW_GATEWAY_SECRET()
  if (!need) return next()
  const h =
    req.headers['x-gateway-secret'] ||
    (typeof req.headers.authorization === 'string'
      ? req.headers.authorization.replace(/^Bearer\s+/i, '').trim()
      : '')
  if (h !== need) return res.status(401).json({ error: '未授权' })
  next()
})

router.post('/intake', async (req, res, next) => {
  try {
    const { title, description, source, sourceMessageId, sourceUserId, priority } = req.body

    if (!title?.trim() && !description?.trim()) {
      return res.status(400).json({ error: '需求标题和描述不能同时为空' })
    }

    const task = createTask({
      title: (title || description.slice(0, 50)).trim(),
      description: description || '',
      source: source || 'api',
      sourceMessageId,
      sourceUserId,
      createdBy: req.user?.id || 'openclaw',
    })

    if (priority) task.priority = priority

    await saveTask(task)
    emitPipelineEvent('task:created', task)
    emitPipelineEvent('openclaw:intake', {
      taskId: task.id,
      source: task.source,
      title: task.title,
    })

    res.status(201).json({
      ok: true,
      task: {
        id: task.id,
        title: task.title,
        currentStageId: task.currentStageId,
        status: task.status,
      },
    })
  } catch (e) { next(e) }
})

router.get('/status', (_req, res) => {
  res.json({
    gateway: 'openclaw',
    status: 'online',
    channels: {
      feishu: { enabled: !!(process.env.FEISHU_APP_ID && process.env.FEISHU_APP_SECRET) },
      qq: { enabled: !!process.env.QQ_BOT_ENDPOINT },
      wechat: { enabled: !!process.env.WECHAT_MP_TOKEN },
      web: { enabled: true },
      api: { enabled: true },
    },
  })
})

export default router

export async function dispatchToOpenClaw({ title, description, source, sourceMessageId, sourceUserId, autoAdvance = true }) {
  const task = createTask({
    title: (title || description?.slice(0, 50) || '未命名需求').trim(),
    description: description || '',
    source: source || 'api',
    sourceMessageId,
    sourceUserId,
    createdBy: 'openclaw',
  })

  await saveTask(task)
  emitPipelineEvent('task:created', task)
  emitPipelineEvent('openclaw:intake', {
    taskId: task.id,
    source: task.source,
    title: task.title,
  })

  if (autoAdvance) {
    const advanced = advanceTask(task)
    if (advanced.ok) {
      await saveTask(advanced.task)
      emitPipelineEvent('task:stage-advanced', {
        taskId: advanced.task.id,
        from: 'intake',
        to: 'planning',
        task: advanced.task,
      })
      console.log(`[openclaw] 自动推进 → ${advanced.task.id} 进入 planning 阶段`)
      return advanced.task
    }
  }

  return task
}
