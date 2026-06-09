<template>
  <div v-if="visible" class="stage-live-output" :class="{ writing: isWriting }">
    <div class="live-header">
      <div class="live-header-left">
        <span v-if="isWriting" class="live-dot" />
        <span class="live-icon">{{ agentIcon }}</span>
        <span class="live-agent">{{ agentName }}</span>
        <span class="live-phase">{{ phaseLabel }}</span>
      </div>
      <div class="live-header-right">
        <span v-if="isWriting" class="live-badge writing">{{ $t('stageLive.writing') }}</span>
        <span v-else class="live-badge done">{{ $t('stageLive.completed') }}</span>
        <span class="live-chars">{{ outputLength }}</span>
      </div>
    </div>

    <div ref="outputEl" class="live-output">
      <div v-if="!outputText && isWriting" class="live-skeleton">
        <span class="skeleton-line shimmer" />
        <span class="skeleton-line shimmer short" />
        <span class="skeleton-line shimmer medium" />
        <p class="live-waiting">{{ $t('stageLive.waitingForTokens') }}</p>
      </div>
      <div v-else class="live-output-inner">
        <pre class="live-content">{{ outputText }}</pre>
        <span v-if="isWriting" class="cursor-blink">▍</span>
      </div>
    </div>

    <div v-if="isWriting" class="live-footer">
      <el-progress :percentage="100" :indeterminate="true" :stroke-width="2" :show-text="false" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps<{
  /** Current stage ID this panel watches. */
  stageId: string
  /** Human-readable agent name. */
  agentName?: string
  /** Emoji icon for the agent. */
  agentIcon?: string
  /** Phase label (e.g. "需求规划", "UI设计"). */
  phaseLabel?: string
}>()

const outputText = ref('')
const isWriting = ref(false)
const outputLength = ref(0)
const outputEl = ref<HTMLElement | null>(null)
const visible = ref(false)

// Auto-scroll to bottom when new content arrives
watch(outputText, async () => {
  await nextTick()
  if (outputEl.value) {
    outputEl.value.scrollTop = outputEl.value.scrollHeight
  }
})

/** Called when stage:processing / heartbeat arrives — show panel before tokens. */
function onProcessingStart(_data?: Record<string, unknown>) {
  isWriting.value = true
  visible.value = true
}

/** Called by parent when stage:output-start event arrives. */
function onOutputStart(_data?: Record<string, unknown>) {
  outputText.value = ''
  outputLength.value = 0
  isWriting.value = true
  visible.value = true
}

/** Called by parent when stage:output-chunk event arrives. */
function onOutputChunk(data?: Record<string, unknown>) {
  if (!data) return
  const text = (data.text as string) || ''
  if (!text) return
  outputText.value += text
  outputLength.value += text.length
}

/** Called by parent when stage:output-end event arrives. */
function onOutputEnd(_data?: Record<string, unknown>) {
  isWriting.value = false
  // Keep visible for 5 more seconds so user can read
  setTimeout(() => { visible.value = false }, 5000)
}

defineExpose({ onProcessingStart, onOutputStart, onOutputChunk, onOutputEnd })
</script>

<style scoped>
.stage-live-output {
  border-radius: 10px;
  border: 1px solid var(--border-color, #2a2f3a);
  background: var(--bg-card, #1a1d24);
  overflow: hidden;
  margin-bottom: 12px;
}

.stage-live-output.writing {
  border-color: rgba(124, 92, 255, 0.4);
  box-shadow: 0 0 0 1px rgba(124, 92, 255, 0.1);
}

.live-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-color, #2a2f3a);
  background: var(--bg-tertiary, #1e2130);
}

.live-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary, #e8eaed);
}

.live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #7c5cff;
  animation: live-pulse 1.4s infinite;
  flex-shrink: 0;
}

.live-icon { font-size: 14px; }
.live-agent { font-weight: 600; }
.live-phase {
  color: var(--text-muted, #8a8f99);
  margin-left: 4px;
  font-size: 12px;
}

.live-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.live-badge {
  padding: 1px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
}

.live-badge.writing {
  background: rgba(124, 92, 255, 0.12);
  color: #7c5cff;
}

.live-badge.done {
  background: rgba(52, 211, 153, 0.1);
  color: #34d399;
}

.live-chars {
  font-size: 11px;
  color: var(--text-muted, #6b7280);
  font-variant-numeric: tabular-nums;
}

.live-output {
  max-height: 400px;
  overflow-y: auto;
  padding: 14px;
  background: #0d1117;
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', ui-monospace, monospace;
}

.live-output-inner {
  display: flex;
  align-items: flex-start;
  gap: 0;
}

.live-content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.6;
  color: #c9d1d9;
  flex: 1;
}

.cursor-blink {
  color: #7c5cff;
  font-size: 14px;
  line-height: 1.6;
  animation: blink 0.8s infinite;
  flex-shrink: 0;
  margin-right: 2px;
}

.live-footer {
  padding: 0;
}

.live-skeleton {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0;
}

.skeleton-line {
  display: block;
  height: 12px;
  border-radius: 6px;
  background: rgba(124, 92, 255, 0.12);
}

.skeleton-line.short { width: 42%; }
.skeleton-line.medium { width: 68%; }
.skeleton-line:not(.short):not(.medium) { width: 88%; }

.shimmer {
  background: linear-gradient(
    90deg,
    rgba(124, 92, 255, 0.08) 0%,
    rgba(124, 92, 255, 0.22) 50%,
    rgba(124, 92, 255, 0.08) 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.4s ease-in-out infinite;
}

.live-waiting {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-muted, #8a8f99);
}

@keyframes live-pulse {
  0% { box-shadow: 0 0 0 0 rgba(124, 92, 255, 0.5); }
  70% { box-shadow: 0 0 0 6px rgba(124, 92, 255, 0); }
  100% { box-shadow: 0 0 0 0 rgba(124, 92, 255, 0); }
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
</style>
