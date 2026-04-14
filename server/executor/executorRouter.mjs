import { Router } from 'express'
import { executeClaudeCode, getJob, getJobsByTask, killJob, buildExecutionPrompt } from './executorBridge.mjs'
import { getTask } from '../pipeline/taskStore.mjs'

const router = Router()

router.post('/run', (req, res) => {
  const { taskId, prompt, workDir, allowedTools } = req.body

  if (!taskId && !prompt) {
    return res.status(400).json({ error: '需要 taskId 或 prompt' })
  }

  let finalPrompt = prompt
  if (taskId && !prompt) {
    const task = getTask(taskId)
    if (!task) return res.status(404).json({ error: '任务不存在' })
    finalPrompt = buildExecutionPrompt(task)
  }

  const job = executeClaudeCode({
    taskId: taskId || 'manual',
    prompt: finalPrompt,
    workDir,
    allowedTools,
  })

  res.status(201).json({
    jobId: job.id,
    taskId: job.taskId,
    status: job.status,
    pid: job.pid,
  })
})

router.get('/jobs/:jobId', (req, res) => {
  const job = getJob(req.params.jobId)
  if (!job) return res.status(404).json({ error: '执行任务不存在' })
  res.json({
    id: job.id,
    taskId: job.taskId,
    status: job.status,
    pid: job.pid,
    startedAt: job.startedAt,
    completedAt: job.completedAt,
    exitCode: job.exitCode,
    logCount: job.logs.length,
    outputPreview: job.output.slice(0, 500),
  })
})

router.get('/jobs/:jobId/logs', (req, res) => {
  const job = getJob(req.params.jobId)
  if (!job) return res.status(404).json({ error: '执行任务不存在' })
  const offset = Number(req.query.offset) || 0
  res.json({
    jobId: job.id,
    status: job.status,
    logs: job.logs.slice(offset),
    total: job.logs.length,
  })
})

router.get('/jobs/:jobId/output', (req, res) => {
  const job = getJob(req.params.jobId)
  if (!job) return res.status(404).json({ error: '执行任务不存在' })
  res.json({
    jobId: job.id,
    status: job.status,
    output: job.output,
  })
})

router.post('/jobs/:jobId/kill', (req, res) => {
  const ok = killJob(req.params.jobId)
  if (!ok) return res.status(404).json({ error: '无法终止该任务' })
  res.json({ ok: true })
})

router.get('/tasks/:taskId/jobs', (req, res) => {
  const jobs = getJobsByTask(req.params.taskId)
  res.json({
    jobs: jobs.map((j) => ({
      id: j.id,
      status: j.status,
      startedAt: j.startedAt,
      completedAt: j.completedAt,
      exitCode: j.exitCode,
    })),
  })
})

export default router
