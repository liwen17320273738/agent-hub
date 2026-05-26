/**
 * useDesignTokens — composable for fetching and applying design tokens.
 *
 * Usage:
 *   const { tokens, loading, apply, clear } = useDesignTokens()
 *   await apply(taskId)  // fetches + applies as CSS variables
 *   clear()              // removes CSS variables
 */
import { ref, type Ref } from 'vue'
import { fetchDesignTokens, applyDesignTokens, clearDesignTokens, type DesignTokens } from '@/services/designTokensApi'

export function useDesignTokens() {
  const tokens: Ref<DesignTokens> = ref({ colors: {}, typography: {}, spacing: {} })
  const loading = ref(false)
  const error = ref<string | null>(null)
  const applied = ref(false)

  async function apply(taskId: string) {
    loading.value = true
    error.value = null
    try {
      tokens.value = await fetchDesignTokens(taskId)
      applyDesignTokens(tokens.value)
      applied.value = true
    } catch (e: any) {
      error.value = e?.message || String(e)
      applied.value = false
    } finally {
      loading.value = false
    }
  }

  function clear() {
    clearDesignTokens()
    tokens.value = { colors: {}, typography: {}, spacing: {} }
    applied.value = false
  }

  const hasTokens = () =>
    Object.keys(tokens.value.colors).length > 0 ||
    Object.keys(tokens.value.typography).length > 0 ||
    Object.keys(tokens.value.spacing).length > 0

  return {
    tokens,
    loading,
    error,
    applied,
    apply,
    clear,
    hasTokens,
  }
}
