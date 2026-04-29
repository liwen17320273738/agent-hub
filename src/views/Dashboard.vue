<template>
  <div class="dashboard">
    <!-- ── Hero CTA ── -->
    <section class="hero">
      <div class="hero-content">
        <h1>{{ t('dashboard.title') }}</h1>
        <p class="hero-subtitle">{{ t('dashboard.subtitle') }}</p>
        <div class="hero-input-row">
          <el-input
            v-model="taskInput"
            :placeholder="t('dashboard.placeholder')"
            size="large"
            clearable
            :disabled="submitLoading !== null"
            @keyup.enter="submitTask(true)"
          />
        </div>
        <div class="hero-actions">
          <el-button
            type="primary"
            size="large"
            :loading="submitLoading === 'plan'"
            :disabled="submitLoading !== null"
            @click="submitTask(true)"
          >
            {{ t('dashboard.planFirst') }}
          </el-button>
          <el-button
            size="large"
            :loading="submitLoading === 'direct'"
            :disabled="submitLoading !== null"
            @click="submitTask(false)"
          >
            {{ t('dashboard.execute') }}
          </el-button>
          <el-button size="large" @click="$router.push('/inbox')">
            {{ t('dashboard.inbox') }}
            <el-tag v-if="pendingCount" type="danger" size="small" round class="hero-badge">{{ pendingCount }}</el-tag>
          </el-button>
        </div>
        <div class="hero-templates">
          <button
            v-for="tpl in templates"
            :key="tpl.key"
            class="tpl-chip"
            @click="taskInput = t(`dashboard.templatesText.${tpl.key}`)"
          >
            <span class="tpl-icon">{{ tpl.icon }}</span>
            {{ t(`dashboard.templates.${tpl.key}`) }}
          </button>
        </div>
      </div>
      <div class="hero-stats">
        <button
          v-for="s in statCards"
          :key="s.tab"
          type="button"
          class="stat"
          @click="goInbox(s.tab)"
          :title="t('dashboard.statTitle', { label: s.label })"
        >
          <span class="stat-num" :style="{ color: s.color }">{{ s.value }}</span>
          <span class="stat-label">{{ s.label }}</span>
        </button>
      </div>
    </section>

    <!-- ── Config warning ── -->
    <el-alert v-if="backendOffline" type="error" :closable="false" show-icon class="config-warn">
      <template #title>
        {{ t('dashboard.offlineMode') }}
      </template>
    </el-alert>

    <el-alert v-if="!settingsStore.isConfigured()" type="warning" :closable="false" show-icon class="config-warn">
      <template #title>
        <template v-if="isEnterpriseBuild">
          {{ t('dashboard.configWarnEnterprise') }}
        </template>
        <template v-else>
          {{ t('dashboard.configWarnBefore') }}
          <router-link to="/settings" class="link-accent">{{ t('dashboard.configWarnLink') }}</router-link>
          {{ t('dashboard.configWarnAfter') }}
        </template>
      </template>
    </el-alert>

    <!-- ── To-do: pending tasks ── -->
    <section v-if="pendingTasks.length" class="section">
      <h2 class="section-title">
        <el-icon><Bell /></el-icon>
        {{ t('dashboard.pending') }}
        <el-tag type="warning" size="small" round>{{ pendingTasks.length }}</el-tag>
      </h2>
      <div class="task-cards">
        <div
          v-for="task in pendingTasks"
          :key="task.id"
          class="task-card pending"
          @click="$router.push(`/pipeline/task/${task.id}`)"
        >
          <div class="task-card-header">
            <span class="task-title">{{ task.title }}</span>
            <el-tag type="warning" size="small">{{ statusLabel(task.status) }}</el-tag>
          </div>
          <div class="task-card-meta">
            <span>{{ task.source || '-' }}</span>
            <span>{{ formatDate(task.createdAt) }}</span>
          </div>
          <ArtifactCompletionBar v-if="task.stages?.length" :stages="task.stages" />
        </div>
      </div>
    </section>

    <!-- ── Recent tasks ── -->
    <section class="section">
      <h2 class="section-title">
        <el-icon><Clock /></el-icon>
        {{ t('dashboard.recent') }}
      </h2>
      <div v-if="recentTasks.length" class="task-cards">
        <div
          v-for="task in recentTasks"
          :key="task.id"
          class="task-card"
          :class="task.status"
          @click="$router.push(`/pipeline/task/${task.id}`)"
        >
          <div class="task-card-header">
            <span class="task-title">{{ task.title }}</span>
            <el-tag :type="statusType(task.status)" size="small">{{ statusLabel(task.status) }}</el-tag>
          </div>
          <div class="task-card-meta">
            <span>{{ task.source || '-' }}</span>
            <span>{{ task.currentStageId || '-' }}</span>
            <span>{{ formatDate(task.updatedAt || task.createdAt) }}</span>
          </div>
          <ArtifactCompletionBar v-if="task.stages?.length" :stages="task.stages" />
        </div>
      </div>
      <el-empty v-else :description="t('dashboard.emptyRecent')" />
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { appLocaleToBcp47 } from '@/i18n'
import { useSettingsStore } from '@/stores/settings'
import { isEnterpriseBuild } from '@/services/enterpriseApi'
import { fetchBackendTasks } from '@/services/pipelineApi'
import { openClawIntake } from '@/services/gatewayApi'
import type { PipelineTask } from '@/agents/types'
import ArtifactCompletionBar from '@/components/task/ArtifactCompletionBar.vue'
import { ElMessage } from 'element-plus'

const { t, locale } = useI18n()
const router = useRouter()
const settingsStore = useSettingsStore()
const tasks = ref<PipelineTask[]>([])
const taskInput = ref('')
/** Which CTA is in flight — avoids both buttons showing loading (shared flag looked like "both ran"). */
const submitLoading = ref<'plan' | 'direct' | null>(null)
const backendOffline = ref(false)

// Template `label` and `text` are resolved through t() at render time so
// they react to locale changes without a remount.
const templates = [
  { key: 'research', icon: '📊' },
  { key: 'weeklyReport', icon: '📝' },
  { key: 'prdToCode', icon: '🛠' },
  { key: 'support', icon: '💬' },
  { key: 'analytics', icon: '📈' },
]

onMounted(async () => {
  try {
    tasks.value = await fetchBackendTasks()
    backendOffline.value = false
  } catch {
    tasks.value = []
    backendOffline.value = true
  }
})

const pendingTasks = computed(() =>
  tasks.value.filter(t => t.status === 'plan_pending' || t.status === 'awaiting_final_acceptance')
)
const runningTasks = computed(() =>
  tasks.value.filter(t => t.status === 'active' || t.status === 'running')
)
const doneTasks = computed(() =>
  tasks.value.filter(t => t.status === 'done' || t.status === 'accepted')
)
const failedTasks = computed(() =>
  tasks.value.filter(t => t.status === 'failed' || t.status === 'rejected')
)
const recentTasks = computed(() =>
  [...tasks.value]
    .sort((a, b) => (b.updatedAt || b.createdAt) - (a.updatedAt || a.createdAt))
    .slice(0, 10)
)
const pendingCount = computed(() => pendingTasks.value.length)

// `tab` matches the Inbox view's tab names so clicking a card jumps you
// straight to the right list. Without this the card was a dead pixel —
// users would see "失败 3" and have no way to reach those 3 tasks.
const statCards = computed(() => [
  { tab: 'pending', label: t('dashboard.stats.pending'), value: pendingTasks.value.length, color: '#e6a23c' },
  { tab: 'running', label: t('dashboard.stats.running'), value: runningTasks.value.length, color: '#409eff' },
  { tab: 'done',    label: t('dashboard.stats.done'),    value: doneTasks.value.length,    color: '#67c23a' },
  { tab: 'failed',  label: t('dashboard.stats.failed'),  value: failedTasks.value.length,  color: '#f56c6c' },
])

function goInbox(tab: string) {
  router.push({ path: '/inbox', query: { tab } })
}

function statusType(s: string) {
  if (s === 'done' || s === 'accepted') return 'success'
  if (s === 'failed' || s === 'rejected') return 'danger'
  if (s === 'plan_pending' || s === 'awaiting_final_acceptance') return 'warning'
  return 'primary'
}

function statusLabel(s: string) {
  const key = `status.${s}`
  const translated = t(key)
  // `t()` returns the key itself when no translation exists, which would
  // leak "status.foo" into the UI — fall back to the raw string instead.
  return translated === key ? s : translated
}

function formatDate(ts: number | string | undefined | null) {
  if (!ts) return '-'
  return new Date(ts).toLocaleString(appLocaleToBcp47(locale.value), {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function submitTask(planMode: boolean) {
  const text = taskInput.value.trim()
  if (!text) {
    ElMessage.warning(t('dashboard.inputEmpty'))
    return
  }
  if (submitLoading.value !== null) return
  submitLoading.value = planMode ? 'plan' : 'direct'
  try {
    const result = await openClawIntake({
      title: text.slice(0, 80),
      description: text,
      source: 'web',
      userId: 'dashboard',
      messageId: `web-${Date.now()}`,
      planMode,
      autoFinalAccept: false,
    })
    taskInput.value = ''
    backendOffline.value = false

    if (result.task) {
      tasks.value = [result.task, ...tasks.value.filter(t => t.id !== result.task?.id)]
    }

    if (planMode) {
      ElMessage.success(t('dashboard.submitOkPlan'))
      if (result.taskId) router.push(`/pipeline/task/${result.taskId}`)
      else router.push({ path: '/inbox', query: { tab: 'pending' } })
    } else {
      ElMessage.success(t('dashboard.submitOkExec'))
      if (result.taskId) router.push(`/pipeline/task/${result.taskId}`)
      else router.push({ path: '/inbox', query: { tab: 'running' } })
    }
  } catch (e: any) {
    backendOffline.value = true
    ElMessage.error(e.message || t('dashboard.submitError'))
  } finally {
    submitLoading.value = null
  }
}
</script>

<style scoped>
.dashboard {
  padding: 32px 40px;
  max-width: 1100px;
  margin: 0 auto;
}

/* ── Hero ── */
.hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 32px;
  margin-bottom: 32px;
  padding: 28px 32px;
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08), rgba(59, 130, 246, 0.06));
  border: 1px solid rgba(99, 102, 241, 0.15);
}

.hero h1 {
  font-size: 28px;
  font-weight: 800;
  background: linear-gradient(135deg, #6366f1, #3b82f6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 6px;
}

.hero-subtitle {
  color: var(--el-text-color-secondary);
  font-size: 14px;
  margin-bottom: 14px;
}

.hero-input-row {
  margin-bottom: 14px;
  max-width: 520px;
}

.hero-templates {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.tpl-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 12px;
  border-radius: 16px;
  font-size: 12px;
  background: rgba(99, 102, 241, 0.08);
  border: 1px solid rgba(99, 102, 241, 0.18);
  color: var(--el-text-color-regular);
  cursor: pointer;
  transition: all 0.15s;
}

.tpl-chip:hover {
  background: rgba(99, 102, 241, 0.15);
  border-color: rgba(99, 102, 241, 0.3);
}

.tpl-icon {
  font-size: 14px;
}

.hero-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.hero-badge {
  margin-left: 6px;
}

.hero-stats {
  display: flex;
  gap: 20px;
  flex-shrink: 0;
}

.stat {
  text-align: center;
  min-width: 64px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
  cursor: pointer;
  font: inherit;
  transition: background 0.15s, transform 0.12s, border-color 0.15s;
}
.stat:hover {
  background: rgba(99, 102, 241, 0.08);
  transform: translateY(-1px);
}
.stat:focus-visible {
  outline: none;
  border-color: rgba(99, 102, 241, 0.5);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15);
}

.stat-num {
  display: block;
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
}

.stat-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* ── Config ── */
.config-warn {
  margin-bottom: 24px;
}

.link-accent {
  color: var(--el-color-primary);
  font-weight: 600;
}

/* ── Section ── */
.section {
  margin-bottom: 32px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 16px;
}

/* ── Task Cards ── */
.task-cards {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-card {
  padding: 16px 20px;
  border-radius: 12px;
  border: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color);
  cursor: pointer;
  transition: all 0.2s;
}

.task-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  transform: translateY(-1px);
}

.task-card.pending {
  border-left: 3px solid #e6a23c;
}

.task-card.failed, .task-card.rejected {
  border-left: 3px solid #f56c6c;
}

.task-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.task-title {
  font-weight: 600;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  margin-right: 12px;
}

.task-card-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

@media (max-width: 768px) {
  .hero {
    flex-direction: column;
  }
  .hero-stats {
    width: 100%;
    justify-content: space-around;
  }
}
</style>
