/**
 * Unified API client for Python backend (FastAPI).
 * Handles JWT auth, base URL resolution, and error normalization.
 */

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

let _token: string | null = null

export function setAuthToken(token: string | null) {
  _token = token
  if (token) {
    localStorage.setItem('agent-hub-token', token)
  } else {
    localStorage.removeItem('agent-hub-token')
  }
}

export function getAuthToken(): string | null {
  if (_token) return _token
  _token = localStorage.getItem('agent-hub-token')
  return _token
}

/** JWT (web) or `PIPELINE_API_KEY` (gateway-style) — both satisfy `get_pipeline_auth` on the backend. */
export function getAuthTokenOrPipelineKey(): string | null {
  const jwt = getAuthToken()
  if (jwt) return jwt
  const fromEnv = import.meta.env.VITE_PIPELINE_API_KEY || ''
  const fromStorage = localStorage.getItem('agent-hub-pipeline-key') || ''
  const k = String(fromEnv || fromStorage).trim()
  return k || null
}

function authHeaders(): Record<string, string> {
  const token = getAuthToken()
  if (!token) return {}
  return { Authorization: `Bearer ${token}` }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail)
    this.name = 'ApiError'
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const url = `${API_BASE}${path}`
  // When body is FormData, browser auto-sets multipart/form-data with boundary;
  // we must NOT override Content-Type or the boundary info gets lost.
  const isFormData = options?.body instanceof FormData
  const defaultHeaders: Record<string, string> = isFormData
    ? {}
    : { 'Content-Type': 'application/json' }

  const res = await fetch(url, {
    headers: {
      ...defaultHeaders,
      ...authHeaders(),
      ...options?.headers,
    },
    ...options,
  })

  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      const raw = body.detail || body.error || detail
      detail = Array.isArray(raw)
        ? raw.map((e: Record<string, unknown>) => e.msg ?? JSON.stringify(e)).join('; ')
        : String(raw)
    } catch {
      /* empty */
    }

    if (res.status === 401) {
      setAuthToken(null)
    }
    throw new ApiError(res.status, detail)
  }

  if (res.status === 204) return undefined as T
  return res.json()
}

// ----- Auth -----

export interface UserInfo {
  id: string
  email: string
  display_name: string
  role: string
  org_id: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user: UserInfo
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const data = await apiFetch<LoginResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  setAuthToken(data.access_token)
  return data
}

export async function fetchMe(): Promise<UserInfo> {
  return apiFetch<UserInfo>('/auth/me')
}

export function logout() {
  setAuthToken(null)
}

// ----- Agents -----

export interface AgentConfig {
  id: string
  name: string
  title: string
  icon: string
  color: string
  description: string
  system_prompt: string
  quick_prompts: string[]
  category: 'core' | 'support' | 'pipeline'
  pipeline_role?: string
  capabilities: Record<string, unknown>
  preferred_model?: string
  max_tokens: number
  temperature: number
  is_active: boolean
  skills: AgentSkillRef[]
  rules: AgentRuleRef[]
  hooks: AgentHookRef[]
  plugins: AgentPluginRef[]
  mcps: AgentMcpRef[]
}

export interface AgentSkillRef {
  id: string
  skill_id: string
  config: Record<string, unknown>
  enabled: boolean
}
export interface AgentRuleRef {
  id: string
  name: string
  rule_type: string
  content: string
  enabled: boolean
}
export interface AgentHookRef {
  id: string
  name: string
  hook_type: string
  handler: string
  enabled: boolean
}
export interface AgentPluginRef {
  id: string
  name: string
  plugin_type: string
  config: Record<string, unknown>
  enabled: boolean
}
export interface AgentMcpRef {
  id: string
  name: string
  server_url: string
  tools: string[]
  enabled: boolean
}

export async function fetchAgents(category?: string): Promise<AgentConfig[]> {
  const params = category ? `?category=${category}` : ''
  return apiFetch<AgentConfig[]>(`/agents/${params}`)
}

export async function fetchAgent(id: string): Promise<AgentConfig> {
  return apiFetch<AgentConfig>(`/agents/${id}`)
}

// ----- Models (Live) -----

export interface ModelInfo {
  id: string
  provider: string
  label: string
  owned_by?: string
  description?: string
  context_window?: number
  max_output?: number
  created?: number
}

export interface LiveModelsResponse {
  providers: Record<string, ModelInfo[]>
  total: number
}

export async function fetchLiveModels(): Promise<LiveModelsResponse> {
  return apiFetch<LiveModelsResponse>('/models/live')
}

export async function refreshModels(): Promise<LiveModelsResponse> {
  return apiFetch<LiveModelsResponse>('/models/refresh', { method: 'POST' })
}

// ----- Token Usage -----

export interface TokenUsageSummary {
  provider: string
  model: string
  total_prompt_tokens: number
  total_completion_tokens: number
  total_tokens: number
  total_cost_usd: number
  request_count: number
}

export interface TokenUsageReport {
  period: string
  summaries: TokenUsageSummary[]
  total_cost_usd: number
  total_tokens: number
}

export async function fetchTokenUsage(days = 30): Promise<TokenUsageReport> {
  return apiFetch<TokenUsageReport>(`/models/usage?days=${days}`)
}

// ----- Skills -----

export interface SkillInfo {
  id: string
  name: string
  category: string
  description: string
  version: string
  author: string
  prompt_template: string
  config: Record<string, unknown>
  tags: string[]
  rules: unknown[]
  hooks: unknown[]
  plugins: unknown[]
  mcp_tools: unknown[]
  enabled: boolean
  is_builtin: boolean
  install_count: number
}

export async function fetchSkills(category?: string): Promise<SkillInfo[]> {
  const params = category ? `?category=${category}` : ''
  return apiFetch<SkillInfo[]>(`/skills/${params}`)
}

export async function fetchSkill(id: string): Promise<SkillInfo> {
  return apiFetch<SkillInfo>(`/skills/${id}`)
}

// ----- LLM Chat -----

export interface ChatRequest {
  messages: { role: string; content: string }[]
  model?: string
  temperature?: number
  max_tokens?: number
  stream?: boolean
  agent_id?: string
  api_url?: string
}

export interface ChatResponse {
  choices: { message: { content: string } }[]
  usage?: {
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
  }
  provider?: string
  latency_ms?: number
}

export async function chatCompletion(body: ChatRequest): Promise<ChatResponse> {
  return apiFetch<ChatResponse>('/llm/chat', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function chatOnce(body: ChatRequest): Promise<{
  content: string
  latency_ms: number
  usage?: Record<string, number>
  error?: string
}> {
  return apiFetch('/llm/chat-once', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

// ----- Config -----

export interface AppConfig {
  providers: string[]
  default_model: string
  features: {
    pipeline: boolean
    skill_center: boolean
    token_tracking: boolean
    multi_provider: boolean
    memory_layer: boolean
    dag_orchestrator: boolean
    skill_marketplace: boolean
    self_verify: boolean
    guardrails: boolean
    observability: boolean
  }
}

export async function fetchAppConfig(): Promise<AppConfig> {
  return apiFetch<AppConfig>('/config')
}
