import type { ApiResponse } from './pipelineApi'

export interface MetricDef {
  name: string
  source: string
  target_value: number
  direction: string
  measurement_window_days?: number
  baseline_value?: number
  description?: string
}

export interface CheckpointPlan {
  day: number
  method?: string
}

export interface RefundTriggerConfig {
  trigger: string
  ratio?: number
}

export interface DraftContractRequest {
  task_id: string
  business_goal: string
  success_metrics: MetricDef[]
  verification_plan: CheckpointPlan[]
  refund_policy: string
  refund_trigger?: RefundTriggerConfig
  price_usd?: number
  deposit_pct?: number
  delivery_deadline?: string
  drafted_by_agent?: string
}

export interface SignContractRequest {
  signed_by_customer: string
  signature_meta?: Record<string, any>
}

export interface OutcomeContract {
  id: string
  task_id: string
  workspace_id?: string
  business_goal: string
  success_metrics: MetricDef[]
  verification_plan: CheckpointPlan[]
  refund_policy: string
  refund_trigger: Record<string, any>
  price_usd?: number
  deposit_pct?: number
  delivery_deadline?: string
  status: string
  drafted_by_agent?: string
  drafted_at?: string
  signed_by_customer?: string
  signed_at?: string
  fulfilled_at?: string
  breached_at?: string
  refunded_at?: string
  refund_amount_usd?: number
  notes: string
  created_at?: string
  updated_at?: string
  checkpoints?: any[]
  readings_count_by_metric?: Record<string, number>
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const base = (import.meta.env.VITE_API_BASE || '').replace(/\/+$/, '')
  const url = `${base}/api/outcome-contracts${path}`
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`outcome_contract_api_error: ${res.status} ${text}`)
  }
  return res.json()
}

export async function createContract(req: DraftContractRequest): Promise<OutcomeContract> {
  return apiFetch<OutcomeContract>('/draft', {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export async function proposeContract(contractId: string): Promise<OutcomeContract> {
  return apiFetch<OutcomeContract>(`/${contractId}/propose`, { method: 'POST' })
}

export async function signContract(
  contractId: string,
  req: SignContractRequest,
): Promise<OutcomeContract> {
  return apiFetch<OutcomeContract>(`/${contractId}/sign`, {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export async function getContract(contractId: string): Promise<OutcomeContract> {
  return apiFetch<OutcomeContract>(`/${contractId}`)
}

export async function getContractByTask(taskId: string): Promise<OutcomeContract> {
  return apiFetch<OutcomeContract>(`/by-task/${taskId}`)
}
