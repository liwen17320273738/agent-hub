<template>
  <div class="inbox-view">
    <h1>{{ t('inbox.title') }}</h1>
    <p class="inbox-subtitle">{{ t('inbox.subtitle') }}</p>

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
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { fetchTasks } from '@/services/pipelineApi'
import type { PipelineTask } from '@/agents/types'
import TaskTable from '@/components/inbox/TaskTable.vue'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const tasks = ref<PipelineTask[]>([])
type InboxTab = 'pending' | 'running' | 'done' | 'failed'

function tabFromQuery(): InboxTab {
  const q = String(route.query.tab || '')
  return (['pending', 'running', 'done', 'failed'] as InboxTab[]).includes(q as InboxTab)
    ? (q as InboxTab)
    : 'pending'
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
])

onMounted(async () => {
  try { tasks.value = await fetchTasks() } catch { /* empty */ }
})

const pending = computed(() => tasks.value.filter(t =>
  t.status === 'plan_pending' || t.status === 'awaiting_final_acceptance'
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

const stats = computed(() => ({
  pending: pending.value.length,
  running: running.value.length,
  done: done.value.length,
  failed: failed.value.length,
}))

function goTask(task: PipelineTask) {
  router.push(`/pipeline/task/${task.id}`)
}
</script>

<style scoped>
.inbox-view {
  padding: 24px 32px;
  max-width: 1200px;
}

.inbox-view h1 {
  font-size: 22px;
  margin-bottom: 4px;
}

.inbox-subtitle {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-bottom: 20px;
}

.stat-cards {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  flex: 1;
  padding: 16px 20px;
  border-radius: 10px;
  text-align: center;
  border: 2px solid transparent;
  cursor: pointer;
  transition: transform 0.12s ease, border-color 0.12s ease, box-shadow 0.12s ease;
  font: inherit;
}

.stat-card:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.12);
}

.stat-card:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.35);
}

.stat-card.active {
  border-color: currentColor;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.10);
}

.stat-num {
  display: block;
  font-size: 28px;
  font-weight: 700;
}

.stat-label {
  font-size: 13px;
  opacity: 0.8;
}

.stat-card.pending { background: #fdf6ec; color: #e6a23c; }
.stat-card.running { background: #ecf5ff; color: #409eff; }
.stat-card.done    { background: #f0f9eb; color: #67c23a; }
.stat-card.failed  { background: #fef0f0; color: #f56c6c; }
</style>
