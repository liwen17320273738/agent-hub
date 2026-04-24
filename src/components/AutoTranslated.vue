<template><span class="auto-translated">{{ translated }}</span></template>

<script setup lang="ts">
/**
 * Drop-in replacement for plain text when the content is user/AI generated.
 *
 * Usage:
 *   <AutoTranslated :text="task.title" />
 *
 * Renders the original immediately (no blank flicker) then swaps to the
 * translated version as soon as the batched request resolves.
 *
 * For Chinese locale (zh) this is a no-op — static bundle covers the UI
 * chrome and we just pass the original text through. Other locales that need
 * runtime translation use the same /api/translate/batch path (en/ja/ko/fr/de/es).
 */
import { toRef } from 'vue'
import { useAutoTranslate } from '@/composables/useAutoTranslate'

const props = defineProps<{ text: string | null | undefined }>()
const translated = useAutoTranslate(toRef(props, 'text'))
</script>

<style scoped>
.auto-translated {
  /* Inherit all styles from parent; we just pass through. */
  display: inline;
}
</style>
