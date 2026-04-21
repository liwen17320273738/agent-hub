import type { PipelineTask, PipelineEvent, TaskArtifact } from '@/agents/types'
import {
  localFetchTasks,
  localFetchTask,
  localCreateTask,
  localAdvanceTask,
  localRejectTask,
  localDeleteTask,
  localUpdateTask,
} from './pipelineLocal'
import { getAuthToken } from './api'

let serverAvailable: boolean | null = null
let lastCheckTime = 0
const SERVER_CHECK_TTL = 30_000

function getBaseUrl(): string {
  return import.meta.env.VITE_API_BASE || '/api'
}

async function checkServer(): Promise<boolean> {
  const now = Date.now()
  if (serverAvailable !== null && now - lastCheckTime < SERVER_CHECK_TTL) {
    return serverAvailable
  }
  lastCheckTime = now
  try {
    const isEnterprise = import.meta.env.VITE_ENTERPRISE === 'true'
    const res = await fetch(`${getBaseUrl()}/pipeline/health`, {
      credentials: isEnterprise ? 'include' : 'same-origin',
      signal: AbortSignal.timeout(3000),
    })
    serverAvailable = res.ok
  } catch {
    serverAvailable = false
  }
  return serverAvailable
}

/** Normalize API date fields (ISO strings or ms) for UI math (durations, timeAgo). */
function mapTs(v: unknown): number | undefined {
  if (v == null || v === '') return undefined
  if (typeof v === 'number' && Number.isFinite(v)) return v
  if (typeof v === 'string') {
    const n = Date.parse(v)
    return Number.isNaN(n) ? undefined : n
  }
  return undefined
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
    const body = await res.json().catch(() => ({ error: res.statusText }))
    throw new Error(body.detail || body.error || `HTTP ${res.status}`)
  }
  return res.json()
}

/* eslint-disable @typescript-eslint/no-explicit-any */
function mapArtifacts(raw: any[] | undefined): TaskArtifact[] {
  if (!raw?.length) return []
  return raw.map((a: any) => ({
    id: String(a.id),
    type: String(a.artifact_type ?? a.type ?? ''),
    name: String(a.name ?? ''),
    content: String(a.content ?? ''),
    stageId: String(a.stage_id ?? a.stageId ?? ''),
    metadata: (a.metadata_extra ?? a.metadata ?? {}) as Record<string, unknown>,
    createdAt: a.created_at ? new Date(a.created_at).getTime() : Date.now(),
  }))
}

function mapTask(raw: any): PipelineTask {
  return {
    id: raw.id,
    title: raw.title,
    description: raw.description ?? '',
    source: raw.source ?? 'web',
    sourceMessageId: raw.source_message_id ?? raw.sourceMessageId,
    sourceUserId: raw.source_user_id ?? raw.sourceUserId,
    status: raw.status,
    currentStageId: raw.current_stage_id ?? raw.currentStageId ?? 'planning',
    stages: (raw.stages ?? []).map((s: any) => ({
      id: s.stage_id ?? s.id,
      label: s.label,
      status: s.status,
      ownerRole: s.owner_role ?? s.ownerRole,
      startedAt: mapTs(s.started_at ?? s.startedAt),
      completedAt: mapTs(s.completed_at ?? s.completedAt),
      output: s.output,
      sortOrder: s.sort_order ?? s.sortOrder,
      reviewStatus: s.review_status ?? s.reviewStatus ?? null,
      reviewerFeedback: s.reviewer_feedback ?? s.reviewerFeedback ?? null,
      reviewerAgent: s.reviewer_agent ?? s.reviewerAgent ?? null,
      reviewAttempts: s.review_attempts ?? s.reviewAttempts ?? 0,
      approvalId: s.approval_id ?? s.approvalId ?? null,
      verifyStatus: s.verify_status ?? s.verifyStatus ?? null,
      verifyChecks: s.verify_checks ?? s.verifyChecks ?? null,
      qualityScore: s.quality_score ?? s.qualityScore ?? null,
      gateStatus: s.gate_status ?? s.gateStatus ?? null,
      gateScore: s.gate_score ?? s.gateScore ?? null,
      gateDetails: s.gate_details ?? s.gateDetails ?? null,
    })),
    artifacts: mapArtifacts(raw.artifacts),
    template: raw.template ?? null,
    repoUrl: raw.repo_url ?? raw.repoUrl ?? null,
    projectPath: raw.project_path ?? raw.projectPath ?? null,
    qualityGateConfig: raw.quality_gate_config ?? raw.qualityGateConfig ?? null,
    overallQualityScore: raw.overall_quality_score ?? raw.overallQualityScore ?? null,
    createdBy: raw.created_by ?? raw.createdBy ?? '',
    createdAt: mapTs(raw.created_at ?? raw.createdAt) ?? Date.now(),
    updatedAt: mapTs(raw.updated_at ?? raw.updatedAt) ?? Date.now(),
  } as PipelineTask
}
/* eslint-enable @typescript-eslint/no-explicit-any */

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
  const data = await apiFetch<{ tasks: unknown[] }>(
    `/pipeline/tasks${qs ? `?${qs}` : ''}`,
  )
  return (data.tasks ?? []).map(mapTask)
}

export async function fetchTask(id: string): Promise<PipelineTask> {
  if (!(await checkServer())) {
    const task = localFetchTask(id)
    if (!task) throw new Error('任务不存在')
    return task
  }

  const data = await apiFetch<{ task: unknown }>(`/pipeline/tasks/${id}`)
  return mapTask(data.task)
}

export async function fetchTemplates(): Promise<Record<string, {
  label: string
  description: string
  icon: string
  stages: Array<{ id: string; label: string; role: string; dependsOn: string[] }>
  stageCount: number
}>> {
  const data = await apiFetch<{ templates: any }>('/pipeline/templates')
  return data.templates ?? {}
}

export async function compileDeliverables(taskId: string): Promise<{
  name: string
  title: string
  content: string
  updatedAt: number
}> {
  return apiFetch(`/delivery-docs/compile/${taskId}`, { method: 'POST' })
}

export function attachmentDownloadUrl(taskId: string, artifactId: string): string {
  return `${getBaseUrl()}/pipeline/tasks/${taskId}/attachments/${artifactId}/file`
}

export async function uploadTaskAttachment(taskId: string, file: File): Promise<PipelineTask> {
  const token = getAuthToken()
  const isEnterprise = import.meta.env.VITE_ENTERPRISE === 'true'
  const form = new FormData()
  form.append('file', file)
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`

  const res = await fetch(`${getBaseUrl()}/pipeline/tasks/${taskId}/attachments/upload`, {
    method: 'POST',
    credentials: isEnterprise ? 'include' : 'same-origin',
    headers,
    body: form,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }))
    throw new Error(
      (Array.isArray(body.detail) ? body.detail[0]?.msg : body.detail) ||
        body.error ||
        `HTTP ${res.status}`,
    )
  }
  const data = await res.json()
  return mapTask(data.task)
}

export async function downloadTaskAttachment(
  taskId: string,
  artifactId: string,
  filename: string,
): Promise<void> {
  const token = getAuthToken()
  const isEnterprise = import.meta.env.VITE_ENTERPRISE === 'true'
  const res = await fetch(attachmentDownloadUrl(taskId, artifactId), {
    credentials: isEnterprise ? 'include' : 'same-origin',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) {
    throw new Error(`下载失败 HTTP ${res.status}`)
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || 'download'
  a.click()
  URL.revokeObjectURL(url)
}

export interface CustomStageSpec {
  stage_id: string
  label: string
  role: string
  depends_on?: string[]
  max_retries?: number
  on_failure?: 'halt' | 'rollback' | 'skip'
  human_gate?: boolean
  skip_condition?: string | null
  model_override?: string | null
  quality_gate_min?: number | null
}

export async function createTask(payload: {
  title: string
  description?: string
  source?: string
  template?: string
  repo_url?: string
  project_path?: string
  custom_stages?: CustomStageSpec[]
}): Promise<PipelineTask> {
  // Custom-stages flows REQUIRE the backend (local fallback only knows
  // the canonical SDLC stages), so don't silently downgrade to local.
  if (payload.custom_stages?.length) {
    const data = await apiFetch<{ task: unknown }>('/pipeline/tasks', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    return mapTask(data.task)
  }

  if (!(await checkServer())) return localCreateTask(payload)

  const data = await apiFetch<{ task: unknown }>('/pipeline/tasks', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return mapTask(data.task)
}

export async function runDagPipeline(
  taskId: string,
  payload?: { template?: string; complexity?: string; custom_stages?: CustomStageSpec[] },
): Promise<{ ok: boolean; taskId: string; submissionId: string; template: string }> {
  return apiFetch(`/pipeline/tasks/${taskId}/dag-run`, {
    method: 'POST',
    body: JSON.stringify(payload ?? { template: 'full' }),
  })
}

export async function advanceTask(
  id: string,
  output?: string,
): Promise<PipelineTask> {
  if (!(await checkServer())) return localAdvanceTask(id, output)

  const data = await apiFetch<{ task: unknown }>(
    `/pipeline/tasks/${id}/advance`,
    {
      method: 'POST',
      body: JSON.stringify({ output }),
    },
  )
  return mapTask(data.task)
}

export async function rejectTask(
  id: string,
  targetStageId: string,
  reason?: string,
): Promise<PipelineTask> {
  if (!(await checkServer())) return localRejectTask(id, targetStageId, reason)

  const data = await apiFetch<{ task: unknown }>(
    `/pipeline/tasks/${id}/reject`,
    {
      method: 'POST',
      body: JSON.stringify({ target_stage_id: targetStageId, reason }),
    },
  )
  return mapTask(data.task)
}

export async function updateTask(
  id: string,
  updates: Partial<Pick<PipelineTask, 'title' | 'description' | 'status'>>,
): Promise<PipelineTask> {
  if (!(await checkServer())) return localUpdateTask(id, updates)

  const data = await apiFetch<{ task: unknown }>(
    `/pipeline/tasks/${id}`,
    {
      method: 'PATCH',
      body: JSON.stringify(updates),
    },
  )
  return mapTask(data.task)
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
  const data = await apiFetch<{ task: unknown }>(
    `/pipeline/tasks/${taskId}/artifacts`,
    {
      method: 'POST',
      body: JSON.stringify(artifact),
    },
  )
  return mapTask(data.task)
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

export async function validateLocalPath(path: string): Promise<{
  ok: boolean
  resolved: string | null
  detail: string | null
}> {
  const q = encodeURIComponent(path)
  return apiFetch(`/pipeline/utils/validate-local-path?path=${q}`)
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

export interface TraceSpan {
  span_id: string
  stage_id: string
  role: string
  model: string
  tier: string
  status: string
  duration_ms?: number
  total_tokens?: number
  cost_usd?: number
  started_at?: number
}

export interface TraceInfo {
  trace_id: string
  task_id: string
  task_title: string
  status: string
  duration_ms: number
  total_tokens: number
  total_cost_usd: number
  total_llm_calls: number
  models_used: Record<string, number>
  stage_durations: Record<string, number>
  span_count: number
  started_at: number
  completed_at: number
}

export async function fetchTraces(): Promise<{ traces: TraceInfo[] }> {
  return apiFetch('/observability/traces')
}

export async function fetchTracesByTask(taskId: string): Promise<{ traces: TraceInfo[] }> {
  return apiFetch(`/observability/traces/task/${taskId}`)
}

// ===== Guardrails: Approvals =====

export interface ApprovalItem {
  id: string
  task_id: string
  stage_id: string
  action: string
  description: string
  risk_level: string
  requested_by: string
  status: string
  reviewer?: string
  review_comment?: string
  created_at: string
  resolved_at?: string
  metadata: Record<string, unknown>
}

export async function fetchApprovals(): Promise<{ approvals: ApprovalItem[] }> {
  return apiFetch('/observability/approvals')
}

export async function resolveApproval(
  approvalId: string,
  approved: boolean,
  comment?: string,
): Promise<{ approval: ApprovalItem }> {
  return apiFetch(`/observability/approvals/${approvalId}/resolve`, {
    method: 'POST',
    body: JSON.stringify({ approved, comment }),
  })
}

export async function approveStage(
  taskId: string,
  stageId: string,
  approved: boolean,
  comment?: string,
): Promise<{ ok: boolean; approved: boolean; stage_id: string }> {
  return apiFetch(`/pipeline/tasks/${taskId}/stages/${stageId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approved, comment: comment || '' }),
  })
}

export async function getPendingApprovals(taskId: string): Promise<Array<{
  id: string
  stage_id: string
  action: string
  description: string
  risk_level: string
  created_at: string
}>> {
  return apiFetch(`/pipeline/tasks/${taskId}/pending-approvals`)
}

export async function getReviewConfig(): Promise<Record<string, {
  has_peer_review: boolean
  reviewer: string | null
  human_gate: boolean
}>> {
  return apiFetch(`/pipeline/tasks/_/review-config`)
}

// ===== Quality Gate APIs =====

export interface QualityGateStageReport {
  stage_id: string
  label: string
  gate_status: string
  gate_score: number | null
  verify_status: string | null
  quality_score: number | null
  review_status: string | null
  has_output: boolean
  output_length: number
  pass_threshold: number
  fail_threshold: number
}

export interface QualityReport {
  task_id: string
  task_title: string
  template: string | null
  overall_quality_score: number | null
  stages: QualityGateStageReport[]
  summary: {
    total_stages: number
    gates_evaluated: number
    average_score: number
    all_passed: boolean
    any_failed: boolean
    overall_verdict: string
  }
}

export async function fetchQualityReport(taskId: string): Promise<QualityReport> {
  return apiFetch(`/pipeline/tasks/${taskId}/quality-report`)
}

export async function overrideQualityGate(
  taskId: string,
  stageId: string,
  reason?: string,
): Promise<{ ok: boolean; stage_id: string; gate_status: string }> {
  return apiFetch(`/pipeline/tasks/${taskId}/stages/${stageId}/gate-override`, {
    method: 'POST',
    body: JSON.stringify({ reason: reason || '' }),
  })
}

export interface SDLCTemplate {
  label: string
  description: string
  icon: string
  stageCount: number
  hasCustomGates: boolean
  stages: Array<{
    id: string
    label: string
    role: string
    dependsOn: string[]
    qualityGate: {
      passThreshold: number
      failThreshold: number
      minLength: number
      requiredSections: string[]
    }
  }>
}

export async function fetchSDLCTemplates(): Promise<Record<string, SDLCTemplate>> {
  const data = await apiFetch<{ templates: Record<string, SDLCTemplate> }>('/pipeline/sdlc-templates')
  return data.templates ?? {}
}

export async function resumePipeline(
  taskId: string,
  fromStage?: string,
  forceContinue?: boolean,
): Promise<{ ok: boolean; resumed_from: string; remaining_stages: string[] }> {
  return apiFetch(`/pipeline/tasks/${taskId}/resume`, {
    method: 'POST',
    body: JSON.stringify({ from_stage: fromStage || null, force_continue: forceContinue || false }),
  })
}

/**
 * Resume the DAG-based pipeline from its last checkpoint. Distinct from
 * `resumePipeline`, which targets the linear engine.
 *
 * Use this after a stage failed with `on_failure: rollback`, or after a
 * `human_gate` paused the run with status `awaiting_approval`. The backend
 * will:
 *   1. Treat `awaiting_approval` stages as approved (idempotent).
 *   2. Restore DONE stages from the checkpoint (and any newer DB updates).
 *   3. Re-execute everything from the first non-DONE stage.
 */
export async function resumeDagPipeline(
  taskId: string,
): Promise<{ ok: boolean; taskId: string; resumedFromCheckpoint: boolean; template: string }> {
  return apiFetch(`/pipeline/tasks/${taskId}/resume-dag`, { method: 'POST' })
}

// ===== RCA report (Wave 5) =====

export interface RcaStage {
  stage_id: string
  label: string
  owner_role: string
  status: string
  retry_count: number
  max_retries: number
  last_error: string
  verify_status?: string | null
  output_preview: string
}

export interface RcaReport {
  ok: boolean
  task_id: string
  task_title: string
  task_status: string
  has_failure: boolean
  stages: RcaStage[]
  failed_stages: RcaStage[]
  spans_examined: number
  audits_examined: number
  bus_msgs_examined: number
  generated_at: string
  summary?: string
  root_cause?: string | null
  contributing_factors?: string[]
  recommended_actions?: string[]
  severity?: string
  blast_radius?: string
  evidence?: string
  llm_error?: string
  llm_raw?: string
}

export async function getTaskRca(
  taskId: string,
  useLlm = true,
): Promise<RcaReport> {
  return apiFetch(`/pipeline/tasks/${taskId}/rca?use_llm=${useLlm ? 'true' : 'false'}`)
}

// ===== Audit Log =====

export interface AuditEntry {
  id: string
  task_id: string
  stage_id: string
  action: string
  actor: string
  risk_level: string
  outcome: string
  details: string
  created_at: string
}

export async function fetchAuditLog(limit = 100): Promise<{ entries: AuditEntry[] }> {
  return apiFetch(`/observability/audit-log?limit=${limit}`)
}

// ===== Planner-Worker: Model Resolution =====

export async function resolveModel(
  role: string,
  stageId?: string,
): Promise<{ resolution: { model: string; tier: string } }> {
  return apiFetch('/observability/planner/resolve-model', {
    method: 'POST',
    body: JSON.stringify({ role, stageId }),
  })
}

export type SSEStatus = 'connecting' | 'connected' | 'disconnected'

async function fetchSSETicket(): Promise<string | null> {
  try {
    const res = await apiFetch<{ ticket: string }>('/pipeline/events/ticket', { method: 'POST' })
    return res.ticket
  } catch {
    return null
  }
}

export function subscribePipelineEvents(
  onEvent: (event: PipelineEvent) => void,
  onStatusChange?: (status: SSEStatus) => void,
): () => void {
  if (serverAvailable === false) return () => {}

  let source: EventSource | null = null
  let cancelled = false

  onStatusChange?.('connecting')

  const baseUrl = getBaseUrl()

  fetchSSETicket().then((ticket) => {
    if (cancelled) return
    const url = ticket
      ? `${baseUrl}/pipeline/events?ticket=${encodeURIComponent(ticket)}`
      : `${baseUrl}/pipeline/events`
    source = new EventSource(url)

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
  })

  return () => {
    cancelled = true
    source?.close()
    onStatusChange?.('disconnected')
  }
}
