/**
 * Agent runtime API — wraps `/agents/run-by-role`, `/agents/{id}/run/stream`,
 * `/agents/runtime/roles`, and `/agents/runtime/tools`.
 *
 * The streaming variant returns an async iterator of typed events so the UI
 * can render progress incrementally.
 */
import { apiFetch, getAuthToken } from './api'

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

export interface RuntimeRole {
  role: string
  seed_id: string
  short_prompt: string
  is_primary: boolean
}

export interface RuntimeTool {
  name: string
  description: string
  permissions: string[]
  parameters: Record<string, unknown>
}

export interface AgentRunRequest {
  task: string
  context?: Record<string, unknown>
  max_steps?: number
  temperature?: number
  tools_override?: string[]
  system_prompt_override?: string
  model_override?: string
}

export interface AgentRunResponse {
  ok: boolean
  agent_id: string
  content: string
  steps: number
  observations: string[]
  model: string
  verification?: string | null
  error?: string | null
  elapsed_ms: number
  mcp_tools_loaded?: string[]
}

export type AgentStreamEvent =
  | { event: 'started'; agent_id: string; task: string }
  | {
      event: 'progress'
      phase: string
      data: Record<string, unknown>
    }
  | (Omit<AgentRunResponse, 'agent_id'> & { event: 'completed'; agent_id: string })
  | { event: 'error'; error: string }

export async function listRuntimeRoles(): Promise<{ roles: RuntimeRole[]; count: number }> {
  return apiFetch('/agents/runtime/roles')
}

export async function listRuntimeTools(): Promise<{ tools: RuntimeTool[]; count: number }> {
  return apiFetch('/agents/runtime/tools')
}

export async function runAgentByRole(
  role: string,
  body: AgentRunRequest,
): Promise<AgentRunResponse> {
  return apiFetch('/agents/run-by-role', {
    method: 'POST',
    body: JSON.stringify({ role, ...body }),
  })
}

export async function runAgentById(
  agentId: string,
  body: AgentRunRequest,
): Promise<AgentRunResponse> {
  return apiFetch(`/agents/${encodeURIComponent(agentId)}/run`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

// ───── Prompt Optimizer (Wave 5) ─────

export interface PromptRevision {
  ok: boolean
  agent_id: string
  run_id?: string | null
  old_prompt: string
  new_prompt?: string
  rationale?: string
  diff_summary?: string[]
  failures_considered?: number
  skipped?: boolean
  reason?: string
}

export async function optimizePrompt(
  agentId: string,
  body: { run_id?: string; score_threshold?: number } = {},
): Promise<PromptRevision> {
  return apiFetch(`/agents/${encodeURIComponent(agentId)}/optimize-prompt`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function applyPromptRevision(
  agentId: string,
  body: { new_prompt: string; note?: string },
): Promise<{ ok: boolean; agent_id: string; applied: boolean; history_size: number }> {
  return apiFetch(`/agents/${encodeURIComponent(agentId)}/apply-prompt`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function rollbackPromptRevision(
  agentId: string,
  steps = 1,
): Promise<{ ok: boolean; agent_id: string; restored_from: string }> {
  return apiFetch(`/agents/${encodeURIComponent(agentId)}/rollback-prompt?steps=${steps}`, {
    method: 'POST',
  })
}

/**
 * Stream an agent run. Yields parsed JSON events from the SSE response.
 * Use AbortController to cancel a long-running stream.
 */
export async function* runAgentStream(
  agentIdOrRole: string,
  body: AgentRunRequest,
  signal?: AbortSignal,
): AsyncGenerator<AgentStreamEvent, void, void> {
  const token = getAuthToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  if (token) headers.Authorization = `Bearer ${token}`

  const res = await fetch(
    `${API_BASE}/agents/${encodeURIComponent(agentIdOrRole)}/run/stream`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
    },
  )

  if (!res.ok || !res.body) {
    let detail = `HTTP ${res.status}`
    try {
      const j = await res.json()
      detail = j.detail || j.error || detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let nlIdx: number
    while ((nlIdx = buffer.indexOf('\n\n')) !== -1) {
      const chunk = buffer.slice(0, nlIdx).trim()
      buffer = buffer.slice(nlIdx + 2)
      if (!chunk) continue
      const dataLine = chunk
        .split('\n')
        .filter((l) => l.startsWith('data:'))
        .map((l) => l.slice(5).trimStart())
        .join('\n')
      if (!dataLine) continue
      try {
        yield JSON.parse(dataLine) as AgentStreamEvent
      } catch (e) {
        console.warn('[agentApi] failed to parse SSE chunk', dataLine, e)
      }
    }
  }
}
