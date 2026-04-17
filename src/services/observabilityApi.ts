/**
 * Observability API — wraps `/api/observability/*`.
 *
 * Today only the Wave 5 weekly digest endpoint is needed; other observability
 * tools live elsewhere in the app and can be migrated here progressively.
 */
import { apiFetch } from './api'

export interface DigestDelta {
  current: number
  previous: number
  delta: number
  rel_delta: number
}

export interface DigestRoleRow {
  role: string
  current: Record<string, number>
  previous: Record<string, number>
  deltas: {
    eval_pass_rate: DigestDelta
    eval_avg_score: DigestDelta
    span_p95_ms: DigestDelta
    stage_failure_rate: DigestDelta
  }
}

export interface DigestRegression {
  role: string
  reasons: string[]
}

export interface WeeklyDigest {
  ok: boolean
  generated_at: string
  current_window: { since: string; until: string; days: number }
  previous_window: { since: string; until: string; days: number }
  roles: DigestRoleRow[]
  regressions: DigestRegression[]
  regressions_count: number
}

export async function getWeeklyDigest(params?: {
  since_days?: number
  prev_days?: number
  pass_rate_drop?: number
  score_drop?: number
  latency_increase?: number
}): Promise<WeeklyDigest> {
  const qs = new URLSearchParams()
  if (params?.since_days) qs.set('since_days', String(params.since_days))
  if (params?.prev_days) qs.set('prev_days', String(params.prev_days))
  if (params?.pass_rate_drop !== undefined) qs.set('pass_rate_drop', String(params.pass_rate_drop))
  if (params?.score_drop !== undefined) qs.set('score_drop', String(params.score_drop))
  if (params?.latency_increase !== undefined) qs.set('latency_increase', String(params.latency_increase))
  const tail = qs.toString()
  return apiFetch(`/observability/digest${tail ? `?${tail}` : ''}`)
}
