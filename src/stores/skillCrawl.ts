import { defineStore } from 'pinia'
import { ref, shallowRef } from 'vue'
import { triggerMarketplaceCrawl } from '@/services/pipelineApi'

let crawlWakeLock: WakeLockSentinel | null = null
let visibilityHooked = false

function releaseCrawlWakeLock() {
  crawlWakeLock?.release().catch(() => {})
  crawlWakeLock = null
}

async function acquireCrawlWakeLock(inProgress: () => boolean) {
  if (!('wakeLock' in navigator) || !inProgress()) return
  try {
    crawlWakeLock = await navigator.wakeLock.request('screen')
  } catch {
    crawlWakeLock = null
  }
}

function isAbortError(e: unknown): boolean {
  return (
    (e instanceof DOMException && e.name === 'AbortError') ||
    (e instanceof Error && e.name === 'AbortError')
  )
}

/**
 * Long-running marketplace crawl survives SPA navigation: state lives outside
 * AdminSkillReview.vue. Only {@link cancelCrawl} or a completed request ends the run.
 */
export const useSkillCrawlStore = defineStore('skillCrawl', () => {
  const inProgress = ref(false)
  const crawlStatus = ref<{ ok: boolean; summary: string } | null>(null)
  const crawlError = ref<string | null>(null)
  const crawlAborted = ref(false)
  const abortCtl = shallowRef<AbortController | null>(null)

  async function onVisibility() {
    if (document.visibilityState !== 'visible' || !inProgress.value) return
    await acquireCrawlWakeLock(() => inProgress.value)
  }

  function hookVisibility() {
    if (visibilityHooked) return
    visibilityHooked = true
    document.addEventListener('visibilitychange', onVisibility)
  }

  async function startCrawl(enableTopicSearch: boolean) {
    if (inProgress.value) return
    hookVisibility()
    crawlStatus.value = null
    crawlError.value = null
    crawlAborted.value = false
    const ac = new AbortController()
    abortCtl.value = ac
    inProgress.value = true
    await acquireCrawlWakeLock(() => inProgress.value)
    try {
      const res = await triggerMarketplaceCrawl({
        enableTopicSearch,
        signal: ac.signal,
      })
      crawlStatus.value = res
    } catch (e: unknown) {
      if (isAbortError(e)) {
        crawlAborted.value = true
      } else {
        crawlError.value = e instanceof Error ? e.message : String(e)
      }
    } finally {
      inProgress.value = false
      abortCtl.value = null
      releaseCrawlWakeLock()
    }
  }

  function cancelCrawl() {
    abortCtl.value?.abort()
  }

  return {
    inProgress,
    crawlStatus,
    crawlError,
    crawlAborted,
    startCrawl,
    cancelCrawl,
  }
})
