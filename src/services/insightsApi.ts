import { getAuthToken } from './api'

function getBaseUrl(): string {
  return import.meta.env.VITE_API_BASE || '/api'
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getAuthToken()
  const isEnterprise = import.meta.env.VITE_ENTERPRISE === 'true'
  const authHeaders: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {}
  const res = await fetch(`${getBaseUrl()}${path}`, {
    credentials: isEnterprise ? 'include' : 'same-origin',
    headers: { 'Content-Type': 'application/json', ...authHeaders, ...(options?.headers || {}) },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`)
  }
  return res.json()
}

// ───────── Observability dashboard ─────────

export interface DashboardSnapshot {
  window: { days: number; since: string }
  totals: {
    cost_usd: number
    tokens: number
    llm_calls: number
    tasks: number
    stages_executed: number
    rejects: number
    fails: number
  }
  trend: Array<{
    day: string
    cost_usd: number
    tokens: number
    llm_calls: number
    avg_duration_ms: number
  }>
  stage_heatmap: Array<{
    stage_id: string
    role: string
    samples: number
    avg_duration_ms: number
    pass_rate: number | null
    approve_rate: number | null
    avg_score: number | null
    retry_rate: number
    rejects: number
    fails: number
  }>
  agent_leaderboard: Array<{
    role: string
    stages: number
    approve_rate: number | null
    avg_score: number | null
    total_cost_usd: number
    total_tokens: number
    llm_calls: number
    fails: number
    rejects: number
  }>
  model_leaderboard: Array<{
    model: string
    tier: string
    calls: number
    total_cost_usd: number
    total_tokens: number
    avg_duration_ms: number
    failure_rate: number
  }>
  recent_failures: Array<{
    task_id: string
    task_title: string
    stage_id: string
    role: string
    status: string
    review_status: string | null
    retry_count: number
    last_error: string
    reviewer_feedback: string
    completed_at: string | null
  }>
  approvals: { total: number; by_status: Record<string, number>; by_risk: Record<string, number> }
  budget_events: Record<string, number>
  task_status: Record<string, number>
}

export function fetchDashboard(days = 14): Promise<DashboardSnapshot> {
  return apiFetch<DashboardSnapshot>(`/observability/dashboard?days=${days}`)
}

// ───────── Learning loop ─────────

export interface LearningSignal {
  id: string
  task_id: string
  stage_id: string
  role: string
  signal_type: string
  severity: string
  reviewer: string | null
  reviewer_feedback: string | null
  output_excerpt: string | null
  error_excerpt: string | null
  retry_count: number
  quality_score: number | null
  distilled: boolean
  distilled_into_id: string | null
  created_at: string | null
}

export interface PromptOverride {
  id: string
  stage_id: string
  role: string
  title: string
  addendum: string
  rationale: string | null
  status: string
  auto_apply: boolean
  sample_signal_ids: string[]
  distilled_from_n: number
  version: number
  parent_id: string | null
  activated_at: string | null
  activated_by: string | null
  archived_at: string | null
  /**
   * Optional segment filter. Empty (or empty arrays) means match-anything,
   * which is the legacy behaviour for overrides created before the
   * shadow-segmentation feature shipped.
   */
  targeting?: { templates?: string[]; complexities?: string[] }
  impact: { uses: number; approves: number; rejects: number; approve_rate: number | null }
  created_at: string | null
}

export interface LearningSummary {
  per_stage: Array<{
    stage_id: string
    signals_total: number
    signals_undistilled: number
    by_type: Record<string, number>
    active_override: { id: string; title: string; version: number; uses: number; approves: number; rejects: number } | null
    proposed_overrides: number
    archived_overrides: number
  }>
}

export function fetchLearningSummary(): Promise<LearningSummary> {
  return apiFetch<LearningSummary>(`/learning/summary`)
}

export function fetchSignals(opts?: {
  stageId?: string
  distilled?: boolean
  limit?: number
}): Promise<{ signal_types: Record<string, string>; signals: LearningSignal[] }> {
  const p = new URLSearchParams()
  if (opts?.stageId) p.set('stage_id', opts.stageId)
  if (opts?.distilled !== undefined) p.set('distilled', String(opts.distilled))
  if (opts?.limit) p.set('limit', String(opts.limit))
  const qs = p.toString() ? `?${p.toString()}` : ''
  return apiFetch(`/learning/signals${qs}`)
}

export function fetchOverrides(opts?: {
  stageId?: string
  status?: string
}): Promise<{ overrides: PromptOverride[] }> {
  const p = new URLSearchParams()
  if (opts?.stageId) p.set('stage_id', opts.stageId)
  if (opts?.status) p.set('status', opts.status)
  const qs = p.toString() ? `?${p.toString()}` : ''
  return apiFetch(`/learning/overrides${qs}`)
}

export function distillStage(
  stageId: string,
  autoApply = false,
): Promise<{ override: PromptOverride }> {
  return apiFetch(`/learning/distill`, {
    method: 'POST',
    body: JSON.stringify({ stage_id: stageId, auto_apply: autoApply }),
  })
}

export function activateOverride(id: string): Promise<{ override: PromptOverride }> {
  return apiFetch(`/learning/overrides/${id}/activate`, { method: 'POST' })
}
export function archiveOverride(id: string): Promise<{ override: PromptOverride }> {
  return apiFetch(`/learning/overrides/${id}/archive`, { method: 'POST' })
}
export function disableOverride(id: string): Promise<{ override: PromptOverride }> {
  return apiFetch(`/learning/overrides/${id}/disable`, { method: 'POST' })
}
export function shadowOverride(id: string): Promise<{ override: PromptOverride }> {
  return apiFetch(`/learning/overrides/${id}/shadow`, { method: 'POST' })
}

// ─── Skill sandbox ─────────────────────────────────────────────────────────
export interface SandboxRoleSummary {
  role: string
  policy: 'whitelist' | 'unrestricted'
  allowed: string[]
  denied: string[]
  common: string[]
  /**
   * Tools whose effective allow/deny diverges from the in-code baseline
   * because an admin has installed a DB override. Used for badge UI on
   * the matrix cells.
   */
  overrides?: { allow: string[]; deny: string[] }
}

export interface SandboxPolicy {
  common_tools: string[]
  all_tools: string[]
  roles: Record<string, SandboxRoleSummary>
}

/**
 * One persisted (role, tool) override row. Empty list = sandbox runs on
 * the in-code baseline.
 */
export interface SandboxRule {
  id: string
  role: string
  tool: string
  allowed: boolean
  note: string | null
  updated_by: string | null
  created_at: string | null
  updated_at: string | null
}

export interface SandboxDenial {
  id: string
  task_id: string | null
  stage_id: string | null
  tool: string
  actor: string | null
  details: string | null
  created_at: string | null
}

export function fetchSandboxPolicy(): Promise<SandboxPolicy> {
  return apiFetch('/sandbox/policy')
}

export function fetchSandboxDenials(opts?: {
  taskId?: string
  limit?: number
}): Promise<{ denials: SandboxDenial[] }> {
  const q = new URLSearchParams()
  if (opts?.taskId) q.set('task_id', opts.taskId)
  if (opts?.limit) q.set('limit', String(opts.limit))
  const qs = q.toString()
  return apiFetch(`/sandbox/denials${qs ? `?${qs}` : ''}`)
}

export function fetchSandboxRules(role?: string): Promise<{ rules: SandboxRule[] }> {
  const qs = role ? `?role=${encodeURIComponent(role)}` : ''
  return apiFetch(`/sandbox/rules${qs}`)
}

export function setSandboxRule(
  role: string,
  tool: string,
  allowed: boolean,
  note?: string,
): Promise<{ rule: SandboxRule; effective: SandboxRoleSummary }> {
  return apiFetch(`/sandbox/rules/${encodeURIComponent(role)}/${encodeURIComponent(tool)}`, {
    method: 'PUT',
    body: JSON.stringify({ allowed, note }),
  })
}

export function deleteSandboxRule(
  role: string,
  tool: string,
): Promise<{ ok: boolean; effective: SandboxRoleSummary }> {
  return apiFetch(`/sandbox/rules/${encodeURIComponent(role)}/${encodeURIComponent(tool)}`, {
    method: 'DELETE',
  })
}

// ─── Learning loop targeting (shadow segmentation) ───────────────────────────
export function setOverrideTargeting(
  id: string,
  body: { templates?: string[]; complexities?: string[] },
): Promise<{ override: PromptOverride }> {
  return apiFetch(`/learning/overrides/${id}/targeting`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

// ─── Scheduler ─────────────────────────────────────────────────────────────
export interface SchedulerStatus {
  maxConcurrent: number
  runningCount: number
  queueDepth: number
  running: Array<{
    submission_id: string
    task_id: string
    label: string
    queued_at: string
    started_at: string | null
  }>
  queued: Array<{
    submission_id: string
    task_id: string
    label: string
    queued_at: string
  }>
  lifetime: { submitted: number; finished: number; failed: number }
}

export function fetchSchedulerStatus(): Promise<SchedulerStatus> {
  return apiFetch('/scheduler/status')
}
