<template>
  <div class="health-bar" :class="{ 'health-offline': sseStatus === 'disconnected' }">
    <div class="health-left">
      <!-- SSE 连接状态 -->
      <span class="health-item" :title="sseTooltip">
        <span class="health-dot" :class="sseStatus"></span>
        <span class="health-label">{{ sseLabel }}</span>
      </span>

      <!-- 排队深度 -->
      <span v-if="queueDepth > 0" class="health-item health-queue" :title="$t('health.queueTooltip', { n: queueDepth })">
        <el-icon><Clock /></el-icon>
        <span>{{ $t('health.queueLabel', { n: queueDepth }) }}</span>
      </span>
    </div>

    <div class="health-right">
      <!-- 最后事件时间 -->
      <span v-if="lastEventSecs !== null" class="health-item health-muted">
        {{ $t('health.lastEvent', { secs: lastEventSecs }) }}
      </span>

      <!-- 事件计数 -->
      <span v-if="eventCount > 0" class="health-item health-muted">
        {{ $t('health.eventCount', { n: eventCount }) }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Clock } from '@element-plus/icons-vue'
import { useGlobalSSE } from '@/composables/useGlobalSSE'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const authStore = useAuthStore()
const { sseStatus, queueDepth, lastEventAt, eventCount, start } = useGlobalSSE()

onMounted(async () => {
  // 确保认证状态已初始化
  if (!authStore.initialized) {
    try { await authStore.hydrate() } catch { /* ignore */ }
  }
  // 只有在已登录时才启动SSE连接
  if (authStore.isLoggedIn) {
    start()
  }
})
// Don't stop on unmount — the singleton persists across pages

const now = ref(Date.now())
let tick: ReturnType<typeof setInterval> | null = null
onMounted(() => { tick = setInterval(() => { now.value = Date.now() }, 5_000) })
onUnmounted(() => { if (tick) clearInterval(tick) })

const lastEventSecs = computed(() => {
  if (!lastEventAt.value) return null
  return Math.floor((now.value - lastEventAt.value) / 1000)
})

const sseLabel = computed(() => {
  switch (sseStatus.value) {
    case 'connected': return t('health.sseConnected')
    case 'connecting': return t('health.sseConnecting')
    default: return t('health.sseDisconnected')
  }
})

const sseTooltip = computed(() => {
  switch (sseStatus.value) {
    case 'connected': return t('health.sseConnectedTip')
    case 'connecting': return t('health.sseConnectingTip')
    default: return t('health.sseDisconnectedTip')
  }
})
</script>

<style scoped>
.health-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 28px;
  padding: 0 16px;
  font-size: 11px;
  background: var(--bg-tertiary, #1e2130);
  border-bottom: 1px solid var(--border-color, #2a2f3a);
  user-select: none;
  flex-shrink: 0;
}

.health-bar.health-offline {
  background: rgba(248, 113, 113, 0.06);
  border-bottom-color: rgba(248, 113, 113, 0.15);
}

.health-left,
.health-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.health-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-secondary, #a0a4ae);
}

.health-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.health-dot.connected {
  background: #34d399;
  box-shadow: 0 0 4px rgba(52, 211, 153, 0.5);
}

.health-dot.connecting {
  background: #f59e0b;
  animation: health-pulse 1s infinite;
}

.health-dot.disconnected {
  background: #f87171;
}

.health-label {
  font-weight: 500;
}

.health-queue {
  color: #f59e0b;
  font-weight: 600;
}

.health-muted {
  color: var(--text-muted, #6b7280);
  font-variant-numeric: tabular-nums;
}

@keyframes health-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
</style>
