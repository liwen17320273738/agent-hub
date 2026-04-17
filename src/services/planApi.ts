/**
 * Plan Inbox API — wraps `/api/plans/*` for web-side approval of pending IM plans.
 */
import { apiFetch } from './api'

export interface PlanStep {
  no: number
  title: string
  detail?: string
  role?: string
  estimate_min?: number
}

export interface ExecutionPlanDoc {
  title: string
  summary: string
  steps: PlanStep[]
  template?: string
  deploy_target?: string
  risks: string[]
  estimate_min_total: number
  confidence: string
}

export interface PlanSummary {
  source: string
  user_id: string
  title: string
  description_snippet: string
  step_count: number
  rotation_count: number
  started_at: number | null
  max_rotations: number
}

export interface PlanDetail {
  source: string
  user_id: string
  title: string
  description: string
  plan: ExecutionPlanDoc
  rotation_count: number
  started_at: number | null
  max_rotations: number
}

export async function listPlans(): Promise<{ count: number; items: PlanSummary[] }> {
  return apiFetch('/plans')
}

export async function getPlan(source: string, userId: string): Promise<PlanDetail> {
  return apiFetch(`/plans/${encodeURIComponent(source)}/${encodeURIComponent(userId)}`)
}

export async function approvePlan(
  source: string,
  userId: string,
): Promise<{ ok: boolean; action: string; taskId: string; pipelineTriggered: boolean }> {
  return apiFetch(
    `/plans/${encodeURIComponent(source)}/${encodeURIComponent(userId)}/approve`,
    { method: 'POST' },
  )
}

export async function rejectPlan(
  source: string,
  userId: string,
): Promise<{ ok: boolean; action: string }> {
  return apiFetch(
    `/plans/${encodeURIComponent(source)}/${encodeURIComponent(userId)}/reject`,
    { method: 'POST' },
  )
}

export async function revisePlan(
  source: string,
  userId: string,
  feedback: string,
): Promise<{ ok: boolean; action: string; rotation_count: number }> {
  return apiFetch(
    `/plans/${encodeURIComponent(source)}/${encodeURIComponent(userId)}/revise`,
    { method: 'POST', body: JSON.stringify({ feedback }) },
  )
}
