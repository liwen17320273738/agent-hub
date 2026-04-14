import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { emitPipelineEvent } from '../events.mjs'

const runningJobs = new Map()

/**
 * Claude Code 执行桥：在终端中执行 claude 命令，捕获输出并推送实时日志。
 *
 * 依赖：系统需安装 claude CLI（npm install -g @anthropic-ai/claude-code）
 *
 * 执行模式：
 * 1. 构建包含 PRD 和上下文的 prompt
 * 2. 通过 claude CLI 执行
 * 3. 实时捕获 stdout/stderr 并推送 SSE
 * 4. 完成后收集输出作为 stage artifact
 */
export function executeClaudeCode({ taskId, prompt, workDir, allowedTools }) {
  const jobId = randomUUID()
  const logs = []
  const startedAt = Date.now()

  const claudeArgs = ['--print', '--output-format', 'text']
  if (allowedTools?.length) {
    claudeArgs.push('--allowedTools', allowedTools.join(','))
  }

  const job = {
    id: jobId,
    taskId,
    status: 'running',
    pid: null,
    logs,
    startedAt,
    completedAt: null,
    exitCode: null,
    output: '',
  }

  runningJobs.set(jobId, job)

  emitPipelineEvent('executor:started', {
    jobId,
    taskId,
    startedAt,
  })

  const claudeBin = process.env.CLAUDE_PATH || 'claude'
  const child = spawn(claudeBin, claudeArgs, {
    cwd: workDir || process.cwd(),
    env: { ...process.env },
    stdio: ['pipe', 'pipe', 'pipe'],
  })

  job.pid = child.pid

  child.stdin.write(prompt)
  child.stdin.end()

  let stdout = ''
  let stderr = ''

  child.stdout.on('data', (chunk) => {
    const text = chunk.toString()
    stdout += text
    const logEntry = { type: 'stdout', text, timestamp: Date.now() }
    logs.push(logEntry)
    emitPipelineEvent('executor:log', { jobId, taskId, ...logEntry })
  })

  child.stderr.on('data', (chunk) => {
    const text = chunk.toString()
    stderr += text
    const logEntry = { type: 'stderr', text, timestamp: Date.now() }
    logs.push(logEntry)
    emitPipelineEvent('executor:log', { jobId, taskId, ...logEntry })
  })

  child.on('close', (code) => {
    job.status = code === 0 ? 'done' : 'failed'
    job.exitCode = code
    job.completedAt = Date.now()
    job.output = stdout

    emitPipelineEvent('executor:completed', {
      jobId,
      taskId,
      status: job.status,
      exitCode: code,
      duration: job.completedAt - job.startedAt,
      outputLength: stdout.length,
    })
  })

  child.on('error', (err) => {
    job.status = 'error'
    job.completedAt = Date.now()
    const logEntry = { type: 'error', text: err.message, timestamp: Date.now() }
    logs.push(logEntry)
    emitPipelineEvent('executor:error', { jobId, taskId, error: err.message })
  })

  return job
}

export function getJob(jobId) {
  return runningJobs.get(jobId) || null
}

export function getJobsByTask(taskId) {
  return Array.from(runningJobs.values())
    .filter((j) => j.taskId === taskId)
    .sort((a, b) => b.startedAt - a.startedAt)
}

export function killJob(jobId) {
  const job = runningJobs.get(jobId)
  if (!job || !job.pid) return false
  try {
    process.kill(job.pid, 'SIGTERM')
    job.status = 'killed'
    job.completedAt = Date.now()
    emitPipelineEvent('executor:killed', { jobId, taskId: job.taskId })
    return true
  } catch {
    return false
  }
}

export function buildExecutionPrompt(task) {
  const parts = [`## 任务: ${task.title}\n`]

  if (task.description) {
    parts.push(`### 需求描述\n${task.description}\n`)
  }

  const prdStage = task.stages.find((s) => s.id === 'planning')
  if (prdStage?.output) {
    parts.push(`### PRD\n${prdStage.output}\n`)
  }

  const archStage = task.stages.find((s) => s.id === 'architecture')
  if (archStage?.output) {
    parts.push(`### 技术方案\n${archStage.output}\n`)
  }

  parts.push(`### 执行要求
- 严格按照 PRD 和技术方案实现
- 每个改动写清楚涉及的文件和原因
- 完成后输出修改的文件列表和验证步骤
- 如有偏差或疑问，明确标注而非自行决定`)

  return parts.join('\n')
}
