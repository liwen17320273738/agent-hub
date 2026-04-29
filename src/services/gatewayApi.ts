import { mapTask } from './pipelineApi'
import { getAuthToken } from './api'
import type { PipelineTask } from '@/agents/types'

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

export interface OpenClawIntakeResponse {
  ok: boolean
  action?: string
  taskId?: string
  planMode: boolean
  pipelineTriggered: boolean
  autoFinalAccept?: boolean
  task?: PipelineTask
  plan?: Record<string, unknown>
  planSession?: {
    source: string
    userId: string
    links: Record<string, string>
  }
}

function gatewayToken(): string {
  const fromEnv = import.meta.env.VITE_PIPELINE_API_KEY || ''
  const fromStorage = localStorage.getItem('agent-hub-pipeline-key') || ''
  return String(fromEnv || fromStorage).trim()
}

export async function openClawIntake(payload: {
  title: string
  description?: string
  source?: string
  userId?: string
  messageId?: string
  planMode?: boolean
  autoFinalAccept?: boolean
}): Promise<OpenClawIntakeResponse> {
  const token = gatewayToken()
  if (!token) {
    throw new Error('OpenClaw gateway key missing. Set VITE_PIPELINE_API_KEY or localStorage agent-hub-pipeline-key.')
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  }
  const sessionJwt = getAuthToken()
  if (sessionJwt) {
    headers['X-Agent-Hub-Session'] = `Bearer ${sessionJwt}`
  }

  const res = await fetch(`${API_BASE}/gateway/openclaw/intake`, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  })

  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      detail = String(body.detail || body.error || detail)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }

  const data = await res.json()
  return {
    ...data,
    task: data.task ? mapTask(data.task) : undefined,
  }
}

/** Approve a pending plan (same as IM「开干」). Requires pipeline gateway key. */
export async function openClawApprovePlan(
  source: string,
  userId: string,
): Promise<{
  ok: boolean
  action?: string
  taskId?: string
  pipelineTriggered?: boolean
  autoFinalAccept?: boolean
}> {
  const token = gatewayToken()
  if (!token) {
    throw new Error('OpenClaw gateway key missing. Set VITE_PIPELINE_API_KEY or localStorage agent-hub-pipeline-key.')
  }
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
  }
  const sessionJwt = getAuthToken()
  if (sessionJwt) {
    headers['X-Agent-Hub-Session'] = `Bearer ${sessionJwt}`
  }
  const res = await fetch(
    `${API_BASE}/gateway/openclaw/plans/${encodeURIComponent(source)}/${encodeURIComponent(userId)}/approve`,
    { method: 'POST', headers },
  )
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      detail = String(body.detail || body.error || detail)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return res.json()
}

/** Discard a pending plan. Requires pipeline gateway key. */
export async function openClawRejectPlan(source: string, userId: string): Promise<{ ok: boolean; action?: string }> {
  const token = gatewayToken()
  if (!token) {
    throw new Error('OpenClaw gateway key missing. Set VITE_PIPELINE_API_KEY or localStorage agent-hub-pipeline-key.')
  }
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
  }
  const sessionJwt = getAuthToken()
  if (sessionJwt) {
    headers['X-Agent-Hub-Session'] = `Bearer ${sessionJwt}`
  }
  const res = await fetch(
    `${API_BASE}/gateway/openclaw/plans/${encodeURIComponent(source)}/${encodeURIComponent(userId)}/reject`,
    { method: 'POST', headers },
  )
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      detail = String(body.detail || body.error || detail)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return res.json()
}
