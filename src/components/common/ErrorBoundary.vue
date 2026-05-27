<script setup lang="ts">
/**
 * ErrorBoundary — catches errors from child components and displays
 * a friendly fallback instead of crashing the entire app.
 *
 * Usage:
 *   <ErrorBoundary>
 *     <SomeComplexComponent />
 *   </ErrorBoundary>
 */
import { ref, onErrorCaptured } from 'vue'

const hasError = ref(false)
const errorMessage = ref('')

onErrorCaptured((err, _instance, info) => {
  hasError.value = true
  errorMessage.value = err instanceof Error ? err.message : String(err)
  console.error('[ErrorBoundary]', info, err)
  // Return false to stop the error from propagating further
  return false
})

function retry() {
  hasError.value = false
  errorMessage.value = ''
}
</script>

<template>
  <slot v-if="!hasError" />
  <div v-else class="error-boundary">
    <div class="error-boundary__icon">⚠️</div>
    <p class="error-boundary__title">{{ $t('common.renderError') }}</p>
    <p class="error-boundary__message">{{ errorMessage }}</p>
    <button class="error-boundary__retry" @click="retry">{{ $t('common.retry') }}</button>
  </div>
</template>

<style scoped>
.error-boundary {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2rem;
  margin: 1rem;
  border: 1px solid var(--el-color-danger-light-5, #fbc4c4);
  border-radius: 8px;
  background: var(--el-color-danger-light-9, #fef0f0);
  text-align: center;
}
.error-boundary__icon {
  font-size: 2rem;
  margin-bottom: 0.5rem;
}
.error-boundary__title {
  font-weight: 600;
  margin-bottom: 0.25rem;
}
.error-boundary__message {
  font-size: 0.85rem;
  color: var(--el-text-color-secondary, #909399);
  max-max-width: 400px; width: 100%;
  word-break: break-all;
}
.error-boundary__retry {
  margin-top: 1rem;
  padding: 0.4rem 1.2rem;
  border: 1px solid var(--el-color-primary, #409eff);
  border-radius: 4px;
  background: var(--el-color-primary, #409eff);
  color: #fff;
  cursor: pointer;
  font-size: 0.85rem;
}
.error-boundary__retry:hover {
  opacity: 0.85;
}
</style>
