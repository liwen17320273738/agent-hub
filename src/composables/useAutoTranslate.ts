/**
 * useAutoTranslate — render runtime-generated text (task titles, AI output,
 * SKILL.md descriptions loaded from disk) in the user's current UI locale.
 *
 * Why not just `$t()`? Because these strings are produced at runtime (or
 * authored in Chinese in the DB) and we can't ship them in `src/i18n/*.ts`.
 *
 * How it works:
 *   1. The composable returns a `Ref<string>` that starts with the original
 *      text — so first paint is never blank.
 *   2. A module-level in-memory Map caches `(text, target) → translated` so
 *      switching views is free.
 *   3. A tiny debouncer coalesces multiple requests into a single batch
 *      POST /api/translate/batch, saving LLM round-trips on lists.
 *   4. Failures fall back to the original string silently — translation is
 *      a progressive enhancement, never a blocker.
 *
 * Usage:
 *   const title = useAutoTranslate(() => task.title)
 *   // in template: {{ title }}
 *
 * Multi-field pattern (preferred for lists):
 *   const { translated } = useAutoTranslateMap(() => ({ title, summary }))
 */

import { ref, watch, onScopeDispose, computed, isRef, type Ref, type MaybeRefOrGetter, toValue } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiFetch } from '@/services/api'

type Target = 'en' | 'ja' | 'ko' | 'fr' | 'de' | 'es' | 'zh'

/** Static languages we already have full static bundles for — no need to call the API. */
const STATIC_LOCALES = new Set<string>(['zh'])

const cache = new Map<string, string>()

function cacheKey(text: string, target: Target): string {
  return `${target}::${text}`
}

/**
 * Coalesces incoming translation requests into a single batch call every
 * ~40ms. A single Map per target collects the unique texts that still
 * need translating, and all subscribers get resolved when the response
 * lands. Mirrors the "request batching" pattern used by dataloaders.
 */
const pending = new Map<Target, Map<string, Array<(v: string) => void>>>()
let flushTimer: ReturnType<typeof setTimeout> | null = null

function scheduleFlush() {
  if (flushTimer) return
  flushTimer = setTimeout(flush, 40)
}

async function flush() {
  flushTimer = null
  const snapshot = new Map(pending)
  pending.clear()

  for (const [target, jobs] of snapshot) {
    const texts = Array.from(jobs.keys())
    if (!texts.length) continue
    try {
      const res = await apiFetch<{ texts: string[]; target: Target }>(
        '/translate/batch',
        {
          method: 'POST',
          body: JSON.stringify({ texts, target }),
        },
      )
      const outs = res.texts || []
      texts.forEach((src, i) => {
        const translated = outs[i] ?? src
        cache.set(cacheKey(src, target), translated)
        const resolvers = jobs.get(src) || []
        resolvers.forEach((r) => r(translated))
      })
    } catch {
      // Silent fail: resolve with original so the UI keeps moving.
      texts.forEach((src) => {
        const resolvers = jobs.get(src) || []
        resolvers.forEach((r) => r(src))
      })
    }
  }
}

function enqueue(text: string, target: Target): Promise<string> {
  const k = cacheKey(text, target)
  const hit = cache.get(k)
  if (hit !== undefined) return Promise.resolve(hit)

  return new Promise<string>((resolve) => {
    let perTarget = pending.get(target)
    if (!perTarget) {
      perTarget = new Map()
      pending.set(target, perTarget)
    }
    const list = perTarget.get(text) || []
    list.push(resolve)
    perTarget.set(text, list)
    scheduleFlush()
  })
}

/**
 * Is a string worth auto-translating? Reuses the same heuristics as the
 * backend so we never fire pointless requests.
 */
function needsTranslation(text: string, target: Target): boolean {
  const s = (text ?? '').trim()
  if (!s) return false
  if (STATIC_LOCALES.has(target)) return false
  const hasHan = /[\u4e00-\u9fff]/.test(s)
  if (!hasHan && /^[\x00-\x7F]*$/.test(s)) return false
  return true
}

/** Translate a single source into the current locale. Reactive. */
export function useAutoTranslate(source: MaybeRefOrGetter<string | null | undefined>): Ref<string> {
  const { locale } = useI18n()
  const out = ref('')

  let disposed = false
  async function update() {
    const raw = (toValue(source) ?? '') + ''
    out.value = raw
    const target = (locale.value as Target) || 'zh'
    if (!needsTranslation(raw, target)) return
    const translated = await enqueue(raw, target)
    if (!disposed) out.value = translated
  }

  watch(
    () => [isRef(source) ? source.value : toValue(source), locale.value] as const,
    update,
    { immediate: true },
  )

  onScopeDispose(() => {
    disposed = true
  })

  return out
}

/**
 * Translate multiple named fields in one shot. Useful in list rows, where
 * you want `title` and `summary` translated together so they stay in sync.
 */
export function useAutoTranslateMany<K extends string>(
  source: MaybeRefOrGetter<Partial<Record<K, string | null | undefined>>>,
): Ref<Record<K, string>> {
  const { locale } = useI18n()
  const out = ref({}) as Ref<Record<K, string>>

  let disposed = false
  async function update() {
    const obj = toValue(source) || {}
    const initial = {} as Record<K, string>
    for (const k of Object.keys(obj) as K[]) initial[k] = (obj[k] ?? '') + ''
    out.value = initial

    const target = (locale.value as Target) || 'zh'
    const tasks = (Object.keys(obj) as K[])
      .map((k) => ({ k, src: initial[k] }))
      .filter((t) => needsTranslation(t.src, target))

    if (!tasks.length) return

    const results = await Promise.all(tasks.map((t) => enqueue(t.src, target)))
    if (disposed) return

    const next = { ...initial }
    tasks.forEach((t, i) => { next[t.k] = results[i] })
    out.value = next
  }

  watch(
    () => [JSON.stringify(toValue(source)), locale.value] as const,
    update,
    { immediate: true },
  )

  onScopeDispose(() => {
    disposed = true
  })

  return out
}

/** Imperative helper for rare, non-reactive cases (toast messages, etc.). */
export async function translateNow(text: string, target?: Target): Promise<string> {
  const t = target || (useI18n().locale.value as Target) || 'zh'
  if (!needsTranslation(text, t)) return text
  return enqueue(text, t)
}

/** Expose the cache map for debugging / tests only. */
export const __TRANSLATE_CACHE__ = cache
