/**
 * Eval Suite API — wraps `/api/eval/*`.
 *
 * The runner is async on the backend: `createRun()` returns immediately with a
 * `run_id`, then poll `getRun(run_id)` (or refresh `listRuns()`) until
 * `status === 'completed' | 'failed'`.
 */
import { apiFetch } from './api'

export type ScorerKind = 'contains' | 'regex' | 'exact' | 'json_path' | 'llm_judge'

export interface EvalDataset {
  id: string
  name: string
  description: string
  target_role: string
  tags: string[]
  is_active: boolean
  case_count: number
  created_at: string | null
  updated_at: string | null
}

export interface EvalCase {
  id: string
  dataset_id: string
  name: string
  task: string
  role: string
  scorer: ScorerKind
  expected: Record<string, unknown>
  context: Record<string, unknown>
  weight: number
  timeout_seconds: number
  enabled: boolean
}

export interface EvalDatasetDetail extends EvalDataset {
  cases: EvalCase[]
}

export interface EvalRunSummary {
  id: string
  dataset_id: string | null
  label: string
  agent_role_override: string
  model_override: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'aborted'
  total_cases: number
  passed_cases: number
  failed_cases: number
  skipped_cases: number
  avg_score: number
  avg_latency_ms: number
  total_tokens: number
  error: string
  started_at: string | null
  completed_at: string | null
  metadata?: Record<string, unknown>
}

export interface EvalResult {
  id: string
  case_id: string | null
  case_name: string
  role: string
  seed_id: string
  score: number
  passed: boolean
  scorer: string
  scorer_detail: Record<string, unknown>
  output: string
  observations: string[]
  error: string
  steps: number
  latency_ms: number
  tokens: number
  created_at: string | null
}

export interface EvalRunDetail extends EvalRunSummary {
  results: EvalResult[]
}

// ───── Datasets ─────

export interface DatasetCreatePayload {
  name: string
  description?: string
  target_role?: string
  tags?: string[]
}

export interface DatasetUpdatePayload {
  description?: string
  target_role?: string
  tags?: string[]
  is_active?: boolean
}

export async function listDatasets(activeOnly = true): Promise<EvalDataset[]> {
  return apiFetch(`/eval/datasets?active_only=${activeOnly}`)
}

export async function getDataset(id: string): Promise<EvalDatasetDetail> {
  return apiFetch(`/eval/datasets/${encodeURIComponent(id)}`)
}

export async function createDataset(p: DatasetCreatePayload): Promise<EvalDataset> {
  return apiFetch('/eval/datasets', { method: 'POST', body: JSON.stringify(p) })
}

export async function updateDataset(
  id: string,
  p: DatasetUpdatePayload,
): Promise<EvalDataset> {
  return apiFetch(`/eval/datasets/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(p),
  })
}

export async function deleteDataset(id: string): Promise<void> {
  return apiFetch(`/eval/datasets/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

// ───── Cases ─────

export interface CaseCreatePayload {
  name?: string
  task: string
  role?: string
  scorer?: ScorerKind
  expected?: Record<string, unknown>
  context?: Record<string, unknown>
  weight?: number
  timeout_seconds?: number
}

export interface CaseUpdatePayload extends Partial<CaseCreatePayload> {
  enabled?: boolean
}

export async function addCase(datasetId: string, p: CaseCreatePayload): Promise<EvalCase> {
  return apiFetch(`/eval/datasets/${encodeURIComponent(datasetId)}/cases`, {
    method: 'POST',
    body: JSON.stringify(p),
  })
}

export async function updateCase(caseId: string, p: CaseUpdatePayload): Promise<EvalCase> {
  return apiFetch(`/eval/cases/${encodeURIComponent(caseId)}`, {
    method: 'PATCH',
    body: JSON.stringify(p),
  })
}

export async function deleteCase(caseId: string): Promise<void> {
  return apiFetch(`/eval/cases/${encodeURIComponent(caseId)}`, { method: 'DELETE' })
}

// ───── Runs ─────

export interface RunCreatePayload {
  dataset_id: string
  label?: string
  agent_role_override?: string
  model_override?: string
  metadata?: Record<string, unknown>
}

export async function createRun(p: RunCreatePayload): Promise<{
  ok: boolean
  run_id: string
  status: string
}> {
  return apiFetch('/eval/runs', { method: 'POST', body: JSON.stringify(p) })
}

export async function listRuns(datasetId?: string, limit = 50): Promise<EvalRunSummary[]> {
  const qs = new URLSearchParams()
  if (datasetId) qs.set('dataset_id', datasetId)
  qs.set('limit', String(limit))
  return apiFetch(`/eval/runs?${qs.toString()}`)
}

export async function getRun(id: string): Promise<EvalRunDetail> {
  return apiFetch(`/eval/runs/${encodeURIComponent(id)}`)
}

// ───── Curate (Wave 5) ─────

export interface CuratePayload {
  source?: 'pipeline_tasks' | 'feedback'
  role?: string
  since_days?: number
  limit?: number
  min_quality_score?: number
  scorer?: ScorerKind
}

export interface CurateResult {
  ok: boolean
  dataset_id: string
  scanned?: number
  appended: number
  skipped?: number
  cases: Array<{ case_name: string; task_title: string; role?: string; source_task_id?: string }>
}

export async function curateDataset(datasetId: string, p: CuratePayload): Promise<CurateResult> {
  return apiFetch(`/eval/datasets/${encodeURIComponent(datasetId)}/curate`, {
    method: 'POST',
    body: JSON.stringify(p),
  })
}
