import { ref, onMounted, onUnmounted, type Ref } from 'vue'
import { fetchBackendTasks } from '@/services/pipelineApi'
import { useAuthStore } from '@/stores/auth'
import { useGlobalSSE } from '@/composables/useGlobalSSE'
import type { PipelineTask } from '@/agents/types'

const POLL_INTERVAL_MS = 5_000

/**
 * Live-updating task list via polling. Refetches every 5 seconds while the
 * component is mounted so Dashboard / Inbox never show stale state.
 *
 * This is intentionally polling instead of SSE-based because:
 *  1. SSE requires a persistent EventSource per page and doesn't survive
 *     page navigation cleanly.
 *  2. Polling gives us a reliable baseline that works even when SSE flakes.
 *  3. The backend /pipeline/tasks endpoint is cheap — a single SELECT.
 *
 * A future iteration should layer SSE for sub-second latency on top of
 * polling as a safety net, but this fixes the "no feedback" UX gap now.
 */
export function useLiveTasks(filters?: () => {
  status?: string
  stage?: string
  source?: string
}): {
  tasks: Ref<PipelineTask[]>
  loading: Ref<boolean>
  error: Ref<string | null>
  /** True when the backend was unreachable on the most recent fetch. */
  backendOffline: Ref<boolean>
  refresh: () => Promise<void>
  /** Timestamp (ms) of the last successful fetch. */
  lastRefreshAt: Ref<number | null>
} {
  const authStore = useAuthStore()
  const tasks = ref<PipelineTask[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const backendOffline = ref(false)
  const lastRefreshAt = ref<number | null>(null)

  let timer: ReturnType<typeof setInterval> | null = null
  let unsubEvent: (() => void) | null = null

  async function refresh() {
    if (!authStore.isLoggedIn) return
    lastRefreshAt.value = Date.now()
    loading.value = true
    error.value = null
    try {
      tasks.value = await fetchBackendTasks(filters?.())
      backendOffline.value = false
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
      backendOffline.value = true
    } finally {
      loading.value = false
    }
  }

  // SSE 订阅必须在 await 之前同步注册 — 若组件在异步初始化期间卸载，
  // 在 async 回调中注册 onUnmounted 会触发 Vue 警告：
  // "onUnmounted is called when there is no active component instance"
  const { onEvent } = useGlobalSSE()
  unsubEvent = onEvent((evt) => {
    const relevant = [
      'task:created', 'task:updated', 'task:stage-advanced',
      'task:rejected', 'task:deleted',
      'stage:completed', 'stage:error', 'stage:processing',
      'pipeline:dag-completed', 'pipeline:dag-start',
      'pipeline:awaiting-final-acceptance',
    ]
    if (relevant.includes(evt.event)) {
      refresh()
    }
  })

  onMounted(() => {
    void (async () => {
      if (!authStore.initialized) {
        try { await authStore.hydrate() } catch { /* ignore */ }
      }
      if (!authStore.isLoggedIn) return
      await refresh()
      timer = setInterval(refresh, POLL_INTERVAL_MS)
    })()
  })

  onUnmounted(() => {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
    if (unsubEvent) {
      unsubEvent()
      unsubEvent = null
    }
  })

  return { tasks, loading, error, backendOffline, lastRefreshAt, refresh }
}
