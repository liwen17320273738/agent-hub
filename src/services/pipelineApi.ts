import type { PipelineTask, PipelineEvent } from '@/agents/types'
import {
  localFetchTasks,
  localFetchTask,
  localCreateTask,
  localAdvanceTask,
  localRejectTask,
  localDeleteTask,
  localUpdateTask,
} from './pipelineLocal'
import { apiFetch as unifiedApiFetch, getAuthToken } from './api'

let serverAvailable: boolean | null = null
let lastCheckTime = 0
const SERVER_CHECK_TTL = 30_000

function getBaseUrl(): string {
  return import.meta.env.VITE_API_BASE || '/api'
}

async function checkServer(): Promise<boolean> {
  const now = Date.now()
  if (serverAvailable !== null && (serverAvailable || now - lastCheckTime < SERVER_CHECK_TTL)) {
    return serverAvailable
  }
  lastCheckTime = now
  try {
    const res = await fetch(`${getBaseUrl()}/pipeline/health`, {
      credentials: 'include',
      signal: AbortSignal.timeout(3000),
    })
    serverAvailable = res.ok
  } catch {
    serverAvailable = false
  }
  return serverAvailable
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getAuthToken()
  const authHeaders: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {}

  const res = await fetch(`${getBaseUrl()}${path}`, {
    headers: { 'Content-Type': 'application/json', ...authHeaders, ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }))
    throw new Error(body.detail || body.error || `HTTP ${res.status}`)
  }
  return res.json()
}

export async function fetchTasks(filters?: {
  status?: string
  stage?: string
  source?: string
}): Promise<PipelineTask[]> {
  if (!(await checkServer())) return localFetchTasks(filters)

  const params = new URLSearchParams()
  if (filters?.status) params.set('status', filters.status)
  if (filters?.stage) params.set('stage', filters.stage)
  if (filters?.source) params.set('source', filters.source)
  const qs = params.toString()
  const data = await apiFetch<{ tasks: PipelineTask[] }>(
    `/pipeline/tasks${qs ? `?${qs}` : ''}`,
  )
  return data.tasks
}

export async function fetchTask(id: string): Promise<PipelineTask> {
  if (!(await checkServer())) {
    const task = localFetchTask(id)
    if (!task) throw new Error('任务不存在')
    return task
  }

  const data = await apiFetch<{ task: PipelineTask }>(`/pipeline/tasks/${id}`)
  return data.task
}

export async function createTask(payload: {
  title: string
  description?: string
  source?: string
}): Promise<PipelineTask> {
  if (!(await checkServer())) return localCreateTask(payload)

  const data = await apiFetch<{ task: PipelineTask }>('/pipeline/tasks', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return data.task
}

export async function advanceTask(
  id: string,
  output?: string,
): Promise<PipelineTask> {
  if (!(await checkServer())) return localAdvanceTask(id, output)

  const data = await apiFetch<{ task: PipelineTask }>(
    `/pipeline/tasks/${id}/advance`,
    {
      method: 'POST',
      body: JSON.stringify({ output }),
    },
  )
  return data.task
}

export async function rejectTask(
  id: string,
  targetStageId: string,
  reason?: string,
): Promise<PipelineTask> {
  if (!(await checkServer())) return localRejectTask(id, targetStageId, reason)

  const data = await apiFetch<{ task: PipelineTask }>(
    `/pipeline/tasks/${id}/reject`,
    {
      method: 'POST',
      body: JSON.stringify({ targetStageId, reason }),
    },
  )
  return data.task
}

export async function updateTask(
  id: string,
  updates: Partial<Pick<PipelineTask, 'title' | 'description' | 'status'>>,
): Promise<PipelineTask> {
  if (!(await checkServer())) return localUpdateTask(id, updates)

  const data = await apiFetch<{ task: PipelineTask }>(
    `/pipeline/tasks/${id}`,
    {
      method: 'PATCH',
      body: JSON.stringify(updates),
    },
  )
  return data.task
}

export async function deleteTask(id: string): Promise<void> {
  if (!(await checkServer())) {
    localDeleteTask(id)
    return
  }
  await apiFetch(`/pipeline/tasks/${id}`, { method: 'DELETE' })
}

export async function addArtifact(
  taskId: string,
  artifact: { type: string; name: string; content: string; stageId?: string },
): Promise<PipelineTask> {
  const data = await apiFetch<{ task: PipelineTask }>(
    `/pipeline/tasks/${taskId}/artifacts`,
    {
      method: 'POST',
      body: JSON.stringify(artifact),
    },
  )
  return data.task
}

export async function executeTask(taskId: string): Promise<{ jobId: string }> {
  return apiFetch('/executor/run', {
    method: 'POST',
    body: JSON.stringify({ taskId }),
  })
}

export async function runStage(
  taskId: string,
  stageId?: string,
): Promise<{ ok: boolean; taskId: string; stageId: string }> {
  return apiFetch(`/pipeline/tasks/${taskId}/run-stage`, {
    method: 'POST',
    body: JSON.stringify({ stageId }),
  })
}

export async function autoRunPipeline(
  taskId: string,
): Promise<{ ok: boolean; taskId: string }> {
  return apiFetch(`/pipeline/tasks/${taskId}/auto-run`, {
    method: 'POST',
  })
}

export async function resumeAfterBuild(
  taskId: string,
): Promise<{ ok: boolean; taskId: string }> {
  return apiFetch(`/pipeline/tasks/${taskId}/resume-after-build`, {
    method: 'POST',
  })
}

export async function fetchPipelineHealth(): Promise<{
  pipeline: string
  sseClients: number
  feishu: boolean
  qq: boolean
  executor: boolean
}> {
  if (!(await checkServer())) {
    return {
      pipeline: 'local',
      sseClients: 0,
      feishu: false,
      qq: false,
      executor: false,
    }
  }
  return apiFetch('/pipeline/health')
}

// ===== Lead Agent 智能流水线 (deer-flow 风格) =====

export async function smartRunPipeline(
  taskId: string,
): Promise<{ ok: boolean; taskId: string }> {
  return apiFetch(`/pipeline/tasks/${taskId}/smart-run`, {
    method: 'POST',
  })
}

export async function analyzeTask(
  taskId: string,
): Promise<{ ok: boolean; taskId: string }> {
  return apiFetch(`/pipeline/tasks/${taskId}/analyze`, {
    method: 'POST',
  })
}

// ===== Skills 技能系统 =====

export interface Skill {
  name: string
  description: string
  category: 'public' | 'custom'
  enabled: boolean
  license: string
  content: string
  path: string
}

export async function fetchSkills(): Promise<Skill[]> {
  const data = await apiFetch<{ skills: Skill[] }>('/pipeline/skills')
  return data.skills
}

export async function toggleSkill(
  skillName: string,
  enabled: boolean,
): Promise<{ ok: boolean }> {
  return apiFetch(`/pipeline/skills/${skillName}`, {
    method: 'PUT',
    body: JSON.stringify({ enabled }),
  })
}

// ===== 中间件监控 =====

export async function fetchMiddlewareStats(): Promise<Record<string, unknown>> {
  return apiFetch('/pipeline/middleware/stats')
}

// ===== Observability: Traces =====

export async function fetchTraces(): Promise<{ traces: any[] }> {
  return apiFetch('/pipeline/traces')
}

export async function fetchTracesByTask(taskId: string): Promise<{ taskId: string; spans: any[] }> {
  return apiFetch(`/pipeline/traces/${taskId}`)
}

// ===== Guardrails: Approvals =====

export async function fetchApprovals(): Promise<{ approvals: any[] }> {
  return apiFetch('/pipeline/approvals')
}

export async function resolveApproval(
  approvalId: string,
  approved: boolean,
  comment?: string,
): Promise<{ approval: any }> {
  return apiFetch(`/pipeline/approvals/${approvalId}/resolve`, {
    method: 'POST',
    body: JSON.stringify({ approved, comment }),
  })
}

// ===== Audit Log =====

export async function fetchAuditLog(limit = 100): Promise<{ entries: any[] }> {
  return apiFetch(`/pipeline/audit-log?limit=${limit}`)
}

// ===== Planner-Worker: Model Resolution =====

export async function resolveModel(
  role: string,
  stageId?: string,
): Promise<{ resolution: { model: string; tier: string } }> {
  return apiFetch('/pipeline/planner/resolve-model', {
    method: 'POST',
    body: JSON.stringify({ role, stageId }),
  })
}

export type SSEStatus = 'connecting' | 'connected' | 'disconnected'

export function subscribePipelineEvents(
  onEvent: (event: PipelineEvent) => void,
  onStatusChange?: (status: SSEStatus) => void,
): () => void {
  if (serverAvailable === false) return () => {}

  const baseUrl = getBaseUrl()
  const token = getAuthToken()
  onStatusChange?.('connecting')

  const url = token
    ? `${baseUrl}/pipeline/events?token=${encodeURIComponent(token)}`
    : `${baseUrl}/pipeline/events`
  const source = new EventSource(url)

  source.onopen = () => {
    onStatusChange?.('connected')
  }

  source.onmessage = (e) => {
    try {
      const parsed = JSON.parse(e.data) as PipelineEvent
      onEvent(parsed)
    } catch {
      // ignore parse errors
    }
  }

  source.onerror = () => {
    onStatusChange?.('disconnected')
  }

  return () => {
    source.close()
    onStatusChange?.('disconnected')
  }
}
