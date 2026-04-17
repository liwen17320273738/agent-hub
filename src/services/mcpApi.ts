/**
 * MCP server admin API — wraps `/api/mcps/*`.
 *
 * Workflow:
 *   1. probeAnonymous(url) — try a URL before committing to it
 *   2. createMcp({agent_id, name, server_url, ...}) — bind to an agent
 *      (auto_refresh=true by default → tool catalog cached immediately)
 *   3. refreshTools(id) — re-pull catalog after server-side updates
 *   4. callTool(id, name, args) — debug ad-hoc invocation
 */
import { apiFetch } from './api'

export interface McpToolSpec {
  name: string
  description?: string
  inputSchema?: Record<string, unknown>
}

export interface McpRecord {
  id: string
  agent_id: string
  name: string
  server_url: string
  tools: McpToolSpec[]
  tool_count: number
  config: Record<string, unknown>
  enabled: boolean
}

export interface ProbeResult {
  ok: boolean
  server_url: string
  session_id?: string | null
  server_info?: Record<string, unknown>
  protocol_version?: string
  capabilities?: Record<string, unknown>
  tools?: McpToolSpec[]
  elapsed_ms: number
  error?: string
}

export interface McpCreatePayload {
  agent_id: string
  name: string
  server_url: string
  config?: Record<string, unknown>
  enabled?: boolean
  auto_refresh?: boolean
}

export interface McpUpdatePayload {
  name?: string
  server_url?: string
  config?: Record<string, unknown>
  enabled?: boolean
}

export async function listMcps(agentId?: string): Promise<McpRecord[]> {
  const qs = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ''
  return apiFetch(`/mcps${qs}`)
}

export async function getMcp(id: string): Promise<McpRecord> {
  return apiFetch(`/mcps/${encodeURIComponent(id)}`)
}

export async function createMcp(payload: McpCreatePayload): Promise<McpRecord> {
  return apiFetch('/mcps', { method: 'POST', body: JSON.stringify(payload) })
}

export async function updateMcp(id: string, payload: McpUpdatePayload): Promise<McpRecord> {
  return apiFetch(`/mcps/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function deleteMcp(id: string): Promise<void> {
  return apiFetch(`/mcps/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export async function probeAnonymous(
  serverUrl: string,
  config?: Record<string, unknown>,
  timeout = 10,
): Promise<ProbeResult> {
  return apiFetch('/mcps/probe', {
    method: 'POST',
    body: JSON.stringify({ server_url: serverUrl, config: config || {}, timeout }),
  })
}

export async function probeStored(id: string): Promise<ProbeResult> {
  return apiFetch(`/mcps/${encodeURIComponent(id)}/probe`, { method: 'POST' })
}

export async function refreshTools(id: string): Promise<{
  ok: boolean
  mcp_id: string
  tool_count: number
  tools: string[]
}> {
  return apiFetch(`/mcps/${encodeURIComponent(id)}/refresh-tools`, { method: 'POST' })
}

export async function callTool(
  id: string,
  name: string,
  args: Record<string, unknown>,
): Promise<unknown> {
  return apiFetch(`/mcps/${encodeURIComponent(id)}/call`, {
    method: 'POST',
    body: JSON.stringify({ name, arguments: args }),
  })
}
