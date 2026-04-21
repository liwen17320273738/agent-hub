import { computed, onBeforeUnmount, ref, type ComputedRef, type Ref } from 'vue'
import type { PipelineTask } from '@/agents/types'

/**
 * Tracks how long each `awaiting_approval` stage in a pipeline has been
 * blocked, so the UI can nag the operator when an approval is overdue.
 *
 * We do this purely client-side for two reasons:
 *
 *   1. The backend has no scheduler/cron for stuck approvals (verified —
 *      ``guardrails.py`` only sets ``APPROVAL_TTL`` for cache eviction, not
 *      escalation). Adding a real scheduler is a big lift; a 30-second
 *      ticker on the dashboard solves 90% of the perceived problem with
 *      <50 lines of code.
 *
 *   2. Each operator's "what counts as overdue" can differ. Doing it
 *      client-side lets us slap thresholds on per-page later without a
 *      schema migration.
 *
 * Threshold semantics (default):
 *   - normal:    < warnAfter
 *   - warn:      warnAfter ≤ elapsed < critAfter — the row gets a yellow tint
 *   - critical:  elapsed ≥ critAfter — yellow becomes red, plus optional
 *                                       IM-ping callback fires once per stage
 *
 * The IM-ping firing is one-shot per stage per session — we keep a `Set`
 * of already-pinged ids so the operator doesn't get spammed every tick.
 */
export interface UseApprovalSLAOptions {
  /** Elapsed time before a stage moves from "normal" to "warn", ms. Default 5min. */
  warnAfter?: number
  /** Elapsed time before "critical". Default 15min. */
  critAfter?: number
  /** Polling interval for the ticker, ms. Default 30s. */
  tickInterval?: number
  /** Optional callback fired ONCE per stage when it crosses the critical threshold. */
  onCritical?: (stageId: string, elapsedMs: number) => void
}

export interface ApprovalSLAStatus {
  stageId: string
  level: 'normal' | 'warn' | 'critical'
  elapsedMs: number
  startedAt: number
}

const DEFAULT_WARN = 5 * 60 * 1000
const DEFAULT_CRIT = 15 * 60 * 1000
const DEFAULT_TICK = 30 * 1000

export function useApprovalSLA(
  task: Ref<PipelineTask | null> | ComputedRef<PipelineTask | null>,
  opts: UseApprovalSLAOptions = {},
): {
  byStage: ComputedRef<Map<string, ApprovalSLAStatus>>
  formatElapsed: (ms: number) => string
} {
  const warnAfter = opts.warnAfter ?? DEFAULT_WARN
  const critAfter = opts.critAfter ?? DEFAULT_CRIT
  const tickInterval = opts.tickInterval ?? DEFAULT_TICK
  const onCritical = opts.onCritical

  const now = ref(Date.now())
  const pinged = new Set<string>()

  const tick = window.setInterval(() => {
    now.value = Date.now()
  }, tickInterval)

  onBeforeUnmount(() => {
    window.clearInterval(tick)
  })

  const byStage = computed<Map<string, ApprovalSLAStatus>>(() => {
    const out = new Map<string, ApprovalSLAStatus>()
    const t = task.value
    if (!t) return out
    for (const s of t.stages) {
      if (s.status !== 'awaiting_approval') continue
      // Use startedAt if present; if not, fall back to "now" (which gives
      // 0 elapsed — i.e. don't flag a stage we have no timing info for).
      const startedAt = s.startedAt || now.value
      const elapsed = Math.max(0, now.value - startedAt)
      const level: ApprovalSLAStatus['level'] =
        elapsed >= critAfter ? 'critical' : elapsed >= warnAfter ? 'warn' : 'normal'

      if (level === 'critical' && onCritical && !pinged.has(s.id)) {
        pinged.add(s.id)
        try {
          onCritical(s.id, elapsed)
        } catch {
          // Swallow — we don't want a flaky callback to break the ticker.
        }
      }
      out.set(s.id, { stageId: s.id, level, elapsedMs: elapsed, startedAt })
    }
    return out
  })

  function formatElapsed(ms: number): string {
    const sec = Math.floor(ms / 1000)
    if (sec < 60) return `${sec}s`
    const min = Math.floor(sec / 60)
    if (min < 60) return `${min}min`
    const hr = Math.floor(min / 60)
    const remM = min % 60
    return `${hr}h${remM ? ` ${remM}min` : ''}`
  }

  return { byStage, formatElapsed }
}
