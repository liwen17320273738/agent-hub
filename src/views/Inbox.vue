<template>
  <div class="inbox-view">
    <h1>{{ t('inbox.title') }}</h1>
    <p class="inbox-subtitle">{{ t('inbox.subtitle') }}</p>

    <el-alert
      v-if="backendOffline"
      class="offline-alert"
      type="error"
      :title="t('inbox.offlineMode')"
      show-icon
      :closable="false"
    />

    <!-- 调度队列深度 — 显示有多少任务在排队等待执行 -->
    <div v-if="queueDepth > 0" class="queue-banner">
      <el-icon><Clock /></el-icon>
      <span>{{ $t('inbox.queueDepth', { n: queueDepth }) }}</span>
    </div>

    <div class="stat-cards">
      <button
        v-for="card in statCards"
        :key="card.tab"
        type="button"
        class="stat-card"
        :class="[card.tab, { active: activeTab === card.tab }]"
        @click="activeTab = card.tab"
        :aria-pressed="activeTab === card.tab"
      >
        <span class="stat-num">{{ stats[card.tab] }}</span>
        <span class="stat-label">{{ card.label }}</span>
      </button>
    </div>

    <el-tabs v-model="activeTab">
      <el-tab-pane :label="t('inbox.pending')" name="pending">
        <TaskTable :tasks="pending" :empty-text="t('inbox.emptyPending')" @click-task="goTask" />
      </el-tab-pane>
      <el-tab-pane :label="t('inbox.running')" name="running">
        <TaskTable :tasks="running" :empty-text="t('inbox.emptyRunning')" @click-task="goTask" />
      </el-tab-pane>
      <el-tab-pane :label="t('inbox.done')" name="done">
        <TaskTable :tasks="done" :empty-text="t('inbox.emptyDone')" @click-task="goTask" />
      </el-tab-pane>
      <el-tab-pane :label="t('inbox.failed')" name="failed">
        <TaskTable :tasks="failed" :empty-text="t('inbox.emptyFailed')" @click-task="goTask" />
      </el-tab-pane>
      <el-tab-pane :label="t('inbox.cancelled')" name="cancelled">
        <TaskTable :tasks="cancelled" :empty-text="t('inbox.emptyCancelled')" @click-task="goTask" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useLiveTasks } from '@/composables/useLiveTasks'
import { getAuthToken } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import type { PipelineTask } from '@/agents/types'
import TaskTable from '@/components/inbox/TaskTable.vue'

const { t } = useI18n()
const authStore = useAuthStore()
const router = useRouter()
const route = useRoute()
const { tasks, backendOffline } = useLiveTasks()
const queueDepth = ref(0)

// ── Scheduler queue depth — polled so the inbox shows waiting tasks ──
let queueTimer: ReturnType<typeof setInterval> | null = null

async function refreshQueueDepth() {
  if (!authStore.isLoggedIn) return
  try {
    const r = await fetch('/api/scheduler/status', {
      headers: { Authorization: `Bearer ${getAuthToken()}` },
    })
    if (r.ok) queueDepth.value = (await r.json()).queueDepth || 0
  } catch { /* ignore */ }
}

onMounted(async () => {
  if (!authStore.initialized) {
    try { await authStore.hydrate() } catch { /* ignore */ }
  }
  if (!authStore.isLoggedIn) return
  await refreshQueueDepth()
  queueTimer = setInterval(refreshQueueDepth, 10_000)
})

onUnmounted(() => {
  if (queueTimer !== null) {
    clearInterval(queueTimer)
    queueTimer = null
  }
})
type InboxTab = 'pending' | 'running' | 'done' | 'failed' | 'cancelled'

function tabFromQuery(): InboxTab {
  const q = String(route.query.tab || '')
  return (['pending', 'running', 'done', 'failed', 'cancelled'] as InboxTab[]).includes(q as InboxTab)
    ? (q as InboxTab)
    : 'running'
}
const activeTab = ref<InboxTab>(tabFromQuery())

watch(() => route.query.tab, () => { activeTab.value = tabFromQuery() })
watch(activeTab, (cur) => {
  if (route.query.tab !== cur) {
    router.replace({ path: '/inbox', query: { ...route.query, tab: cur } })
  }
})

const statCards = computed<{ tab: InboxTab; label: string }[]>(() => [
  { tab: 'pending', label: t('inbox.pending') },
  { tab: 'running', label: t('inbox.running') },
  { tab: 'done',    label: t('inbox.done') },
  { tab: 'failed',  label: t('inbox.failed') },
  { tab: 'cancelled', label: t('inbox.cancelled') },
])

const pending = computed(() => tasks.value.filter(t =>
  t.status === 'plan_pending'
  || t.status === 'awaiting_final_acceptance'
  || t.status === 'awaiting_evidence',
))
const running = computed(() => tasks.value.filter(t =>
  t.status === 'active' || t.status === 'running'
))
const done = computed(() => tasks.value.filter(t =>
  t.status === 'done' || t.status === 'accepted'
))
const failed = computed(() => tasks.value.filter(t =>
  t.status === 'failed' || t.status === 'rejected'
))
const cancelled = computed(() => tasks.value.filter(t => t.status === 'cancelled'))

const stats = computed(() => ({
  pending: pending.value.length,
  running: running.value.length,
  done: done.value.length,
  failed: failed.value.length,
  cancelled: cancelled.value.length,
}))

function goTask(task: PipelineTask) {
  router.push(`/pipeline/task/${task.id}`)
}
</script>

<style scoped>
.inbox-view {
  padding: 28px 36px;
  max-width: 1200px;
  width: 100%;
}

.inbox-view h1 {
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -0.4px;
  margin-bottom: 4px;
  background: linear-gradient(135deg, var(--text-primary), var(--text-secondary));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.inbox-subtitle {
  color: var(--text-muted);
  font-size: 14px;
  margin-bottom: 24px;
}

.offline-alert {
  margin-bottom: 16px;
  border-radius: 12px;
}

.queue-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  padding: 10px 16px;
  border-radius: 10px;
  background: rgba(129, 140, 248, 0.08);
  border: 1px solid rgba(129, 140, 248, 0.15);
  color: var(--accent);
  font-size: 13px;
  font-weight: 500;
}

.queue-banner .el-icon {
  color: var(--accent);
}

.stat-cards {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 26px;
}

.stat-card {
  flex: 1 1 140px;
  padding: 18px 16px;
  border-radius: 14px;
  text-align: center;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  font: inherit;
  position: relative;
  overflow: hidden;
}

.stat-card::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  opacity: 0;
  transition: opacity 0.2s;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
}

.stat-card:hover::after {
  opacity: 1;
}

.stat-card:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.3);
}

.stat-card.active {
  box-shadow: 0 0 0 2px currentColor, 0 6px 20px rgba(0, 0, 0, 0.15);
}

.stat-num {
  display: block;
  font-size: 32px;
  font-weight: 800;
  letter-spacing: -1px;
  position: relative;
  z-index: 1;
}

.stat-label {
  font-size: 13px;
  font-weight: 600;
  opacity: 0.8;
  position: relative;
  z-index: 1;
}

.stat-card.pending {
  background: linear-gradient(135deg, rgba(251, 191, 36, 0.12), rgba(245, 158, 11, 0.06));
  border-color: rgba(251, 191, 36, 0.15);
  color: var(--amber);
}

.stat-card.running {
  background: linear-gradient(135deg, rgba(129, 140, 248, 0.12), rgba(99, 102, 241, 0.06));
  border-color: rgba(129, 140, 248, 0.15);
  color: var(--accent);
}

.stat-card.done {
  background: linear-gradient(135deg, rgba(52, 211, 153, 0.12), rgba(16, 185, 129, 0.06));
  border-color: rgba(52, 211, 153, 0.15);
  color: var(--green);
}

.stat-card.failed {
  background: linear-gradient(135deg, rgba(248, 113, 113, 0.12), rgba(239, 68, 68, 0.06));
  border-color: rgba(248, 113, 113, 0.15);
  color: var(--red);
}

.stat-card.cancelled {
  background: rgba(255, 255, 255, 0.03);
  border-color: rgba(255, 255, 255, 0.05);
  color: var(--text-muted);
}
</style>
