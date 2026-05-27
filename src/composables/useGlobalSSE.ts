import { ref, readonly, type Ref } from 'vue'
import { subscribePipelineEvents, fetchPipelineSchedulerStatus, type SSEStatus } from '@/services/pipelineApi'
import type { PipelineEvent } from '@/agents/types'

/** How often to re-check scheduler queue depth while connected, ms. */
const QUEUE_POLL_MS = 10_000

/**
 * Singleton global SSE connection + system health state.
 *
 * Only one EventSource exists for the entire app. Pages don't tear it down
 * on navigation — so Dashboard, Inbox, and PipelineTaskDetail all share
 * the same stream, and no events are lost during route transitions.
 *
 * Components that need task-list updates should use `useLiveTasks` instead;
 * this composable is for the health bar and low-level event subscribers.
 */
let unsubSSE: (() => void) | null = null
let queueTimer: ReturnType<typeof setInterval> | null = null
let started = false

const sseStatus = ref<SSEStatus>('disconnected')
const queueDepth = ref(0)
const lastEventAt = ref<number | null>(null)
const eventCount = ref(0)

/** Singleton event bus — subscribers get every PipelineEvent. */
type EventHandler = (evt: PipelineEvent) => void
const listeners = new Set<EventHandler>()

export function useGlobalSSE() {
  function start() {
    if (started) return
    started = true

    sseStatus.value = 'connecting'
    unsubSSE = subscribePipelineEvents(
      (evt) => {
        lastEventAt.value = Date.now()
        eventCount.value++
        for (const fn of listeners) fn(evt)
      },
      (status) => {
        sseStatus.value = status
      },
    )

    // Poll queue depth on a fixed cadence
    queueTimer = setInterval(async () => {
      try {
        const s = await fetchPipelineSchedulerStatus()
        queueDepth.value = s.queueDepth
      } catch { /* ignore */ }
    }, QUEUE_POLL_MS)
  }

  function stop() {
    unsubSSE?.()
    unsubSSE = null
    if (queueTimer !== null) {
      clearInterval(queueTimer)
      queueTimer = null
    }
    started = false
    sseStatus.value = 'disconnected'
  }

  /** Subscribe to every SSE event. Returns unsubscribe function. */
  function onEvent(fn: EventHandler): () => void {
    listeners.add(fn)
    return () => { listeners.delete(fn) }
  }

  return {
    sseStatus: readonly(sseStatus) as Ref<SSEStatus>,
    queueDepth: readonly(queueDepth) as Ref<number>,
    lastEventAt: readonly(lastEventAt) as Ref<number | null>,
    eventCount: readonly(eventCount) as Ref<number>,
    start,
    stop,
    onEvent,
  }
}
