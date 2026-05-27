<template>
  <div class="dashboard">
    <!-- ── Hero CTA ── -->
    <section class="hero">
      <div class="hero-top">
        <div class="hero-header">
          <h1>{{ t('dashboard.title') }}</h1>
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
      </div>
      <div class="hero-content">
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
          <VoiceInput class="voice-btn" @fill-input="taskInput = $event" />
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
      <div v-if="lastRefreshSecs !== null && !backendOffline" class="freshness-indicator">
        <span class="freshness-dot"></span>
        {{ $t('dashboard.autoRefreshing', { secs: lastRefreshSecs }) }}
        <el-button size="small" text @click="refresh" :loading="loading" class="freshness-refresh-btn">
          <el-icon><Refresh /></el-icon>
        </el-button>
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

    <!-- ── Clarify Gate Dialog ── -->
    <ClarifyGateDialog
      v-model="showClarify"
      :task-text="taskInput"
      :plan-mode="clarifyPlanMode"
      @submitted="onContractSubmitted"
      @cancelled="onClarifyCancelled"
    />

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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { appLocaleToBcp47 } from '@/i18n'
import { useSettingsStore } from '@/stores/settings'
import { useAuthStore } from '@/stores/auth'
import { isEnterpriseBuild } from '@/services/enterpriseApi'
import { useLiveTasks } from '@/composables/useLiveTasks'
import { openClawIntake } from '@/services/gatewayApi'
import type { PipelineTask } from '@/agents/types'
import ArtifactCompletionBar from '@/components/task/ArtifactCompletionBar.vue'
import VoiceInput from '@/components/voice/VoiceInput.vue'
import ClarifyGateDialog from '@/components/contract/ClarifyGateDialog.vue'
const { t, locale } = useI18n()
const router = useRouter()
const settingsStore = useSettingsStore()
const authStore = useAuthStore()
const { tasks, backendOffline, refresh, loading, lastRefreshAt } = useLiveTasks()
const taskInput = ref('')
/** Which CTA is in flight — avoids both buttons showing loading (shared flag looked like "both ran"). */
const submitLoading = ref<'plan' | 'direct' | null>(null)
const showClarify = ref(false)
/** true = 先给方案 (plan gate); false = 直接执行 (auto-start pipeline). */
const clarifyPlanMode = ref(true)

// Template `label` and `text` are resolved through t() at render time so
// they react to locale changes without a remount.
const templates = [
  { key: 'research', icon: '📊' },
  { key: 'weeklyReport', icon: '📝' },
  { key: 'prdToCode', icon: '🛠' },
  { key: 'support', icon: '💬' },
  { key: 'analytics', icon: '📈' },
]

// Data freshness — how many seconds since last auto-refresh
const now = ref(Date.now())
let freshnessTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => { freshnessTimer = setInterval(() => { now.value = Date.now() }, 3_000) })
onUnmounted(() => { if (freshnessTimer) clearInterval(freshnessTimer) })

const lastRefreshSecs = computed(() => {
  if (!lastRefreshAt.value) return null
  return Math.max(0, Math.floor((now.value - lastRefreshAt.value) / 1000))
})

const pendingTasks = computed(() =>
  tasks.value.filter(t =>
    t.status === 'plan_pending'
    || t.status === 'awaiting_final_acceptance'
    || t.status === 'awaiting_evidence',
  )
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
const cancelledTasks = computed(() =>
  tasks.value.filter(t => t.status === 'cancelled')
)
/** Pending / awaiting acceptance are listed in「待办任务」— keep「最近任务」from duplicating them. */
const recentTasks = computed(() =>
  [...tasks.value]
    .filter(t =>
      t.status !== 'plan_pending'
      && t.status !== 'awaiting_final_acceptance'
      && t.status !== 'awaiting_evidence',
    )
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
  { tab: 'cancelled', label: t('dashboard.stats.cancelled'), value: cancelledTasks.value.length, color: '#909399' },
])

function goInbox(tab: string) {
  router.push({ path: '/inbox', query: { tab } })
}

function statusType(s: string) {
  if (s === 'done' || s === 'accepted') return 'success'
  if (s === 'failed' || s === 'rejected') return 'danger'
  if (s === 'cancelled') return 'info'
  if (s === 'plan_pending' || s === 'awaiting_final_acceptance' || s === 'awaiting_evidence') return 'warning'
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

function onContractSubmitted(result: { taskId?: string; contractId?: string }) {
  ElMessage.success(t('dashboard.submitted'))
  taskInput.value = ''
  submitLoading.value = null
  if (result.taskId) {
    router.push(`/pipeline/task/${result.taskId}`)
  } else {
    router.push({ path: '/inbox', query: { tab: 'running' } })
  }
}

function onClarifyCancelled() {
  submitLoading.value = null
}

async function submitTask(planMode: boolean) {
  const text = taskInput.value.trim()
  if (!text) {
    ElMessage.warning(t('dashboard.inputEmpty'))
    return
  }
  if (submitLoading.value !== null) return

  clarifyPlanMode.value = planMode
  showClarify.value = true
}
</script>

<style scoped>
.dashboard {
  padding: 36px 44px;
  max-width: 1040px;
  width: 100%;
  margin: 0 auto;
}

/* ── Hero ── */
.hero {
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin-bottom: 36px;
  padding: 40px;
  border-radius: 20px;
  background: linear-gradient(160deg, rgba(129, 140, 248, 0.1) 0%, rgba(34, 211, 238, 0.04) 40%, rgba(244, 114, 182, 0.06) 100%);
  border: 1px solid rgba(129, 140, 248, 0.12);
  box-shadow: var(--glow-accent), inset 0 1px 0 rgba(255, 255, 255, 0.03);
  position: relative;
  overflow: hidden;
}

.hero-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  position: relative;
  z-index: 1;
  flex-wrap: nowrap;
}

.hero::before {
  content: '';
  position: absolute;
  top: -50%;
  right: -20%;
  width: 400px;
  height: 400px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(129, 140, 248, 0.08) 0%, transparent 70%);
  pointer-events: none;
}

.hero::after {
  content: '';
  position: absolute;
  bottom: -30%;
  left: 10%;
  width: 300px;
  height: 300px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(34, 211, 238, 0.06) 0%, transparent 70%);
  pointer-events: none;
}

.hero-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: 0;
  position: relative;
  z-index: 1;
}

.hero-header {
  display: flex;
  align-items: baseline;
  gap: 16px;
  flex: 1 1 auto;
  min-width: 0;
  max-width: 100%;
  position: relative;
  z-index: 1;
}

.hero h1 {
  font-size: 36px;
  font-weight: 800;
  letter-spacing: -0.5px;
  background: linear-gradient(135deg, var(--accent) 0%, var(--accent-2) 60%, var(--accent-3) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin: 0;
  line-height: 1.2;
  white-space: normal;
  word-break: keep-all;
  min-width: 0;
}

.hero-subtitle {
  color: var(--text-secondary);
  font-size: 16px;
  margin: 0 0 12px 0;
  line-height: 1.6;
}

.hero-input-row {
  margin-bottom: 0;
  max-width: 100%;
  width: 100%;
}

.hero-input-row :deep(.el-input__wrapper) {
  border-radius: 14px;
  padding: 10px 18px;
  box-shadow: 0 0 0 1px rgba(129, 140, 248, 0.25) inset !important;
  transition: all 0.2s;
  background: rgba(255, 255, 255, 0.05);
}

.hero-input-row :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 2px rgba(129, 140, 248, 0.25) inset !important;
}

.hero-input-row :deep(.el-input__inner) {
  font-size: 16px;
  color: var(--text-primary);
}

.hero-templates {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 0;
}

.tpl-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 20px;
  font-size: 14px;
  font-weight: 500;
  background: rgba(129, 140, 248, 0.08);
  border: 1px solid rgba(129, 140, 248, 0.2);
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.tpl-chip:hover {
  background: rgba(129, 140, 248, 0.15);
  border-color: rgba(129, 140, 248, 0.35);
  color: var(--accent);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(129, 140, 248, 0.2);
}

.tpl-icon {
  font-size: 16px;
}

.hero-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.hero-badge {
  margin-left: 6px;
}

.hero-stats {
  display: flex;
  flex-wrap: nowrap;
  align-items: flex-start;
  justify-content: flex-end;
  gap: 8px;
  flex-shrink: 0;
  position: relative;
  z-index: 1;
  min-width: 0;
}

.stat {
  text-align: center;
  flex: 0 0 auto;
  min-width: 90px;
  padding: 12px 10px;
  border-radius: 12px;
  border: 1px solid rgba(129, 140, 248, 0.15);
  background: rgba(255, 255, 255, 0.04);
  cursor: pointer;
  font: inherit;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.stat:hover {
  background: rgba(129, 140, 248, 0.12);
  border-color: rgba(129, 140, 248, 0.3);
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.3);
}

.stat:focus-visible {
  outline: none;
  border-color: rgba(129, 140, 248, 0.4);
  box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.12);
}

.stat-num {
  display: block;
  font-size: 30px;
  font-weight: 800;
  line-height: 1.2;
  letter-spacing: -0.5px;
  margin-bottom: 4px;
}

.stat-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  white-space: normal;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  line-height: 1.3;
  word-break: keep-all;
}

/* ── Config ── */
.config-warn {
  margin-bottom: 28px;
  border-radius: 12px;
}

.link-accent {
  color: var(--accent);
  font-weight: 600;
}

/* ── Section ── */
.freshness-indicator {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
  width: 100%;
  padding-top: 8px;
  border-top: 1px solid rgba(129, 140, 248, 0.08);
}

.freshness-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 4px var(--green);
  animation: freshness-pulse 2s infinite;
}

.freshness-refresh-btn {
  margin-left: 4px;
  padding: 2px 4px !important;
}

@keyframes freshness-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.section {
  margin-bottom: 36px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 18px;
  letter-spacing: -0.2px;
}

.section-title .el-icon {
  color: var(--accent);
}

/* ── Task Cards ── */
.task-cards {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.task-card {
  padding: 18px 22px;
  border-radius: var(--card-radius);
  border: 1px solid var(--card-border);
  background: var(--card-bg);
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: var(--card-shadow);
}

.task-card:hover {
  box-shadow: var(--card-shadow-hover);
  transform: translateY(-2px);
  border-color: var(--card-border-hover);
}

.task-card.pending {
  border-left: 4px solid var(--amber);
  background: linear-gradient(90deg, rgba(251, 191, 36, 0.06) 0%, var(--card-bg) 30%);
}

.task-card.failed, .task-card.rejected {
  border-left: 4px solid var(--red);
  background: linear-gradient(90deg, rgba(248, 113, 113, 0.06) 0%, var(--card-bg) 30%);
}

.task-card.cancelled {
  border-left: 4px solid var(--border-light);
  opacity: 0.7;
}

.task-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.task-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  margin-right: 14px;
}

.task-card-meta {
  display: flex;
  gap: 20px;
  font-size: 12px;
  color: var(--text-muted);
}

@media (max-width: 768px) {
  .dashboard {
    padding: 20px 16px;
  }

  .hero {
    padding: 24px;
  }

  .hero-top {
    flex-direction: column;
    gap: 20px;
  }

  .hero-stats {
    width: 100%;
    justify-content: flex-start;
  }

  .hero h1 {
    font-size: 24px;
  }

  .hero-stats {
    gap: 6px;
  }

  .stat {
    min-width: 70px;
    padding: 10px 8px;
  }

  .stat-num {
    font-size: 24px;
  }
}
</style>
