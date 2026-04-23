<template>
  <div class="inbox-view">
    <h1>收件箱</h1>

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
      <el-tab-pane label="待审批" name="pending">
        <TaskTable :tasks="pending" empty-text="暂无待审批任务" @click-task="goTask" />
      </el-tab-pane>
      <el-tab-pane label="进行中" name="running">
        <TaskTable :tasks="running" empty-text="暂无执行中任务" @click-task="goTask" />
      </el-tab-pane>
      <el-tab-pane label="已完成" name="done">
        <TaskTable :tasks="done" empty-text="暂无已完成任务" @click-task="goTask" />
      </el-tab-pane>
      <el-tab-pane label="失败" name="failed">
        <TaskTable :tasks="failed" empty-text="暂无失败任务" @click-task="goTask" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { fetchTasks } from '@/services/pipelineApi'
import type { PipelineTask } from '@/agents/types'
import TaskTable from '@/components/inbox/TaskTable.vue'

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

// Honor deep-links from Dashboard / external sources. Also keep the URL
// in sync when the user clicks a tab so the page is shareable / refreshable.
watch(() => route.query.tab, () => { activeTab.value = tabFromQuery() })
watch(activeTab, (t) => {
  if (route.query.tab !== t) {
    router.replace({ path: '/inbox', query: { ...route.query, tab: t } })
  }
})

// Single source of truth for the stat cards. Each card owns the tab it
// switches to so they can't visually drift from the underlying tabs (the
// previous version had cards but no "失败" tab, so clicking it would have
// been a dead-end even if the click had worked).
const statCards: { tab: InboxTab; label: string }[] = [
  { tab: 'pending', label: '待审批' },
  { tab: 'running', label: '执行中' },
  { tab: 'done', label: '已完成' },
  { tab: 'failed', label: '失败' },
]

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
