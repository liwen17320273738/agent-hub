<template>
  <div class="pipeline-dashboard">
    <header class="pipeline-header">
      <div class="header-top">
        <h1>{{ t('pipelineDashboard.text_1') }}</h1>
        <div class="header-actions">
          <el-tag :type="healthStatus.pipeline === 'online' ? 'success' : 'danger'" size="small">
            {{
              healthStatus.pipeline === 'online'
                ? t('pipelineDashboard.healthOnline')
                : t('pipelineDashboard.healthOffline')
            }}
          </el-tag>
          <el-tag v-if="healthStatus.feishu" type="info" size="small">{{ t('pipelineDashboard.text_2') }}</el-tag>
          <el-tag v-if="healthStatus.qq" type="info" size="small">QQ</el-tag>
          <el-button type="primary" @click="showCreateDialog = true">
            <el-icon><Plus /></el-icon>
            {{ t('pipelineDashboard.createTaskCta') }}
          </el-button>
        </div>
      </div>
      <p class="subtitle">
        {{ t('pipelineDashboard.headerSubtitle') }}
      </p>
    </header>

    <section class="pipeline-stats">
      <div class="stat-card stat-card--clickable" @click="router.push('/plan-inbox')">
        <div class="stat-number" :class="{ 'stat-highlight': pendingPlanCount > 0 }">{{ pendingPlanCount }}</div>
        <div class="stat-label">{{ t('pipelineDashboard.text_3') }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{{ pipelineStore.activeTasks.length }}</div>
        <div class="stat-label">{{ t('pipelineDashboard.text_4') }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{{ pipelineStore.doneTasks.length }}</div>
        <div class="stat-label">{{ t('pipelineDashboard.text_5') }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{{ pipelineStore.tasks.length }}</div>
        <div class="stat-label">{{ t('pipelineDashboard.text_6') }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{{ pipelineStore.eventLog.length }}</div>
        <div class="stat-label">{{ t('pipelineDashboard.text_7') }}</div>
      </div>
    </section>

    <section class="pipeline-board">
      <h2 class="section-title">{{ t('pipelineDashboard.text_8') }}</h2>
      <div class="stage-columns-scroll">
        <div class="stage-columns">
          <div
            v-for="stage in stages"
            :key="stage.id"
            class="stage-column"
            :class="{ 'has-tasks': (pipelineStore.tasksByStage[stage.id] || []).length > 0 }"
          >
            <div class="stage-header">
              <span class="stage-dot" :style="{ background: stageColor(stage.id) }"></span>
              <el-badge
                :value="(pipelineStore.tasksByStage[stage.id] || []).length"
                :hidden="!(pipelineStore.tasksByStage[stage.id] || []).length"
                type="primary"
                class="stage-badge-wrap"
              >
                <span class="stage-name">{{ stage.label }}</span>
              </el-badge>
            </div>
            <div
              v-if="stage.id === 'planning' && (pipelineStore.tasksByStage[stage.id] || []).length"
              class="planning-bulk-bar"
              @click.stop
            >
              <el-checkbox
                :model-value="planningSelectAllChecked"
                :indeterminate="planningSelectIndeterminate"
                @change="onPlanningSelectAll"
              >
                {{ t('pipelineDashboard.selectAllPlanning') }}
              </el-checkbox>
              <el-button
                type="danger"
                size="small"
                plain
                :disabled="planningSelectedCount === 0"
                @click="confirmDeletePlanningBulk"
              >
                {{ t('pipelineDashboard.deleteSelectedPlanning', { n: planningSelectedCount }) }}
              </el-button>
            </div>
            <div class="stage-tasks">
            <div
              v-for="task in (pipelineStore.tasksByStage[stage.id] || [])"
              :key="task.id"
              class="task-card"
              @click="$router.push(`/pipeline/task/${task.id}`)"
            >
              <div class="task-card-body">
                <el-checkbox
                  v-if="stage.id === 'planning'"
                  class="task-planning-check"
                  :model-value="planningSelectedIds.has(task.id)"
                  @change="(v) => onPlanningRowCheck(task.id, v)"
                  @click.stop
                />
                <div class="task-card-main">
                  <div class="task-card-top">
                    <div class="task-title"><AutoTranslated :text="task.title" /></div>
                    <button
                      v-if="stage.id === 'planning'"
                      type="button"
                      class="task-delete"
                      :title="t('pipelineDashboard.title_1')"
                      :aria-label="t('pipelineDashboard.title_1')"
                      @click.stop="confirmDeletePlanningTask(task)"
                    >
                      <el-icon :size="14"><Delete /></el-icon>
                    </button>
                  </div>
                  <div class="task-meta">
                    <el-tag :type="sourceTagType(task.source)" size="small">{{ task.source }}</el-tag>
                    <span class="task-time">{{ timeAgo(task.updatedAt) }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="!(pipelineStore.tasksByStage[stage.id] || []).length" class="stage-empty">
              {{ t('inbox.empty') }}
            </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ===== Observability Panel ===== -->
    <section class="observability-panel">
      <div class="panel-tabs">
        <button
          v-for="tab in obsTabs"
          :key="tab.id"
          class="panel-tab"
          :class="{ active: activeObsTab === tab.id }"
          @click="activeObsTab = tab.id"
        >
          {{ tab.label }}
          <span v-if="tab.badge" class="tab-badge">{{ tab.badge }}</span>
        </button>
      </div>

      <!-- Traces Tab -->
      <div v-if="activeObsTab === 'traces'" class="panel-content">
        <div v-if="!traces.length" class="empty-state">{{ t('pipelineDashboard.text_9') }}</div>
        <div v-else class="trace-list">
          <div v-for="trace in traces" :key="trace.trace_id" class="trace-card">
            <div class="trace-header">
              <span class="trace-task">{{ trace.task_title || trace.task_id?.slice(0, 8) + '...' }}</span>
              <el-tag :type="trace.status === 'completed' ? 'success' : trace.status === 'failed' ? 'danger' : 'warning'" size="small">
                {{ trace.status }}
              </el-tag>
            </div>
            <div class="trace-metrics">
              <span class="metric">
                <span class="metric-label">Spans</span>
                <span class="metric-value">{{ trace.span_count }}</span>
              </span>
              <span class="metric" v-if="trace.duration_ms">
                <span class="metric-label">{{ t('pipelineDashboard.text_10') }}</span>
                <span class="metric-value">{{ (trace.duration_ms / 1000).toFixed(1) }}s</span>
              </span>
              <span class="metric" v-if="trace.total_tokens">
                <span class="metric-label">Tokens</span>
                <span class="metric-value">{{ trace.total_tokens.toLocaleString() }}</span>
              </span>
              <span class="metric" v-if="trace.total_cost_usd">
                <span class="metric-label">{{ t('pipelineDashboard.text_11') }}</span>
                <span class="metric-value">${{ trace.total_cost_usd.toFixed(4) }}</span>
              </span>
              <span class="metric" v-if="trace.total_llm_calls">
                <span class="metric-label">{{ t('pipelineDashboard.text_12') }}</span>
                <span class="metric-value">{{ trace.total_llm_calls }}</span>
              </span>
            </div>
            <div class="trace-models" v-if="trace.models_used && Object.keys(trace.models_used).length">
              <span class="metric-label">{{ t('pipelineDashboard.text_13') }}</span>
              <el-tag v-for="(count, model) in trace.models_used" :key="model" size="small" class="model-tag">
                {{ model }} ×{{ count }}
              </el-tag>
            </div>
          </div>
        </div>
      </div>

      <!-- Approvals Tab -->
      <div v-if="activeObsTab === 'approvals'" class="panel-content">
        <div v-if="!approvals.length" class="empty-state">{{ t('pipelineDashboard.text_14') }}</div>
        <div v-else class="approval-list">
          <div v-for="a in approvals" :key="a.id" class="approval-card">
            <div class="approval-info">
              <span class="approval-action">{{ a.action }}</span>
              <span class="approval-desc">{{ a.description }}</span>
              <span class="approval-role">{{ a.requested_by }}</span>
              <span class="approval-time">{{ timeAgo(a.created_at) }}</span>
            </div>
            <div class="approval-actions">
              <el-button type="success" size="small" @click="handleApproval(a.id, true)">{{ t('pipelineDashboard.text_15') }}</el-button>
              <el-button type="danger" size="small" @click="handleApproval(a.id, false)">{{ t('pipelineDashboard.text_16') }}</el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- Audit Log Tab -->
      <div v-if="activeObsTab === 'audit'" class="panel-content">
        <div v-if="!auditEntries.length" class="empty-state">{{ t('pipelineDashboard.text_17') }}</div>
        <div v-else class="audit-list">
          <div v-for="(entry, idx) in auditEntries" :key="entry.id || idx" class="audit-entry">
            <span class="audit-outcome" :class="'outcome-' + entry.outcome">{{ entry.outcome }}</span>
            <span class="audit-action">{{ entry.action }}</span>
            <span class="audit-role">{{ entry.actor }}</span>
            <span class="audit-time">{{ formatTime(entry.created_at) }}</span>
          </div>
        </div>
      </div>

      <!-- Model Tiers Tab -->
      <div v-if="activeObsTab === 'tiers'" class="panel-content">
        <div class="tier-info">
          <div class="tier-group" v-for="tier in modelTiers" :key="tier.key">
            <h4 class="tier-name" :class="'tier-' + tier.key">{{ tier.label }}</h4>
            <div class="tier-roles">
              <el-tag v-for="role in tier.roles" :key="role" size="small" class="tier-role-tag">{{ role }}</el-tag>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="pipeline-events" v-if="pipelineStore.eventLog.length">
      <h2 class="section-title">{{ t('pipelineDashboard.text_18') }}</h2>
      <div class="event-list">
        <div
          v-for="(event, idx) in recentEvents"
          :key="idx"
          class="event-item"
        >
          <span class="event-dot" :style="{ background: eventColor(event.event) }"></span>
          <span class="event-type">{{ eventLabel(event.event) }}</span>
          <span class="event-detail">{{ eventDetail(event) }}</span>
          <span class="event-time">{{ formatTime(event.timestamp) }}</span>
        </div>
      </div>
    </section>

    <el-dialog
      v-model="showCreateDialog"
      :title="t('pipelineDashboard.title_2')"
      width="720px"
      class="create-task-dialog"
      destroy-on-close
      align-center
    >
      <el-form label-position="top">
        <el-form-item :label="t('pipelineDashboard.label_1')">
          <el-input v-model="newTask.title" :placeholder="t('pipelineDashboard.placeholder_1')" />
        </el-form-item>
        <el-form-item :label="t('pipelineDashboard.label_2')">
          <el-input
            v-model="newTask.description"
            type="textarea"
            :rows="4"
            :placeholder="t('pipelineDashboard.placeholder_2')"
          />
        </el-form-item>
        <el-form-item :label="t('pipelineDashboard.label_3')">
          <div class="template-grid">
            <div
              v-for="(tmpl, key) in sdlcTemplates"
              :key="key"
              class="template-card"
              :class="{ active: newTask.template === key }"
              @click="selectTemplate(String(key))"
            >
              <span class="template-icon">{{ tmpl.icon }}</span>
              <div class="template-info">
                <span class="template-label">{{ tmpl.label }}</span>
                <span class="template-desc">{{ tmpl.description }}</span>
              </div>
              <div class="template-badges">
                <el-tag size="small" type="info">{{ t('pipelineDashboard.stageCount', { n: tmpl.stageCount }) }}</el-tag>
                <el-tag v-if="tmpl.hasCustomGates" size="small" type="warning">{{ t('pipelineDashboard.text_19') }}</el-tag>
              </div>
            </div>
          </div>
          <div v-if="selectedTemplateStages.length" class="template-preview">
            <div class="template-preview-title">{{ t('pipelineDashboard.text_20') }}</div>
            <div class="template-stage-list">
              <div v-for="(st, idx) in selectedTemplateStages" :key="st.id" class="template-stage-item">
                <span class="tps-idx">{{ idx + 1 }}</span>
                <span class="tps-label">{{ st.label }}</span>
                <span class="tps-role">{{ st.role }}</span>
                <span class="tps-gate">🚦 {{ (st.qualityGate.passThreshold * 100).toFixed(0) }}%</span>
              </div>
            </div>
          </div>
        </el-form-item>
        <el-form-item :label="t('pipelineDashboard.label_4')">
          <el-radio-group v-model="newTask.projectMode" style="margin-bottom: 8px">
            <el-radio-button value="none">{{ t('pipelineDashboard.text_21') }}</el-radio-button>
            <el-radio-button value="git">{{ t('pipelineDashboard.text_22') }}</el-radio-button>
            <el-radio-button value="local">{{ t('pipelineDashboard.text_23') }}</el-radio-button>
          </el-radio-group>
          <el-input
            v-if="newTask.projectMode === 'git'"
            v-model="newTask.repoUrl"
            placeholder="https://github.com/user/repo.git"
            style="margin-top: 4px"
          >
            <template #prepend>Git URL</template>
          </el-input>
          <div v-if="newTask.projectMode === 'local'" class="local-path-field">
            <div class="local-path-inner">
              <span class="path-prepend">{{ t('pipelineDashboard.pathPrepend') }}</span>
              <el-autocomplete
                v-model="newTask.projectPath"
                :fetch-suggestions="fetchPathSuggestions"
                :trigger-on-focus="true"
                clearable
                :placeholder="t('pipelineDashboard.localPathPlaceholder')"
                value-key="value"
                class="path-autocomplete"
              />
            </div>
            <div class="local-path-actions">
              <el-button size="small" @click="pasteProjectPathFromClipboard">{{
                t('pipelineDashboard.pasteFromClipboard')
              }}</el-button>
              <el-button size="small" type="primary" plain @click="pickLocalDirectoryAssist">
                {{ t('pipelineDashboard.pickFolder') }}
              </el-button>
            </div>
            <el-input
              v-model="localProjectParent"
              :placeholder="t('pipelineDashboard.parentPathPlaceholder')"
              size="small"
              class="local-project-parent-input"
              clearable
              @blur="persistLocalProjectParent"
            />
            <p class="form-tip-small">{{ t('pipelineDashboard.localPathTip1') }}</p>
            <p class="form-tip-small">{{ t('pipelineDashboard.localPathTip2') }}</p>
          </div>
        </el-form-item>
        <el-form-item :label="t('pipelineDashboard.labelAttachment')">
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :limit="8"
            multiple
            :on-change="onPendingFileChange"
            :on-remove="onPendingFileRemove"
          >
            <el-button type="default" size="small">{{ t('pipelineDashboard.selectFiles') }}</el-button>
            <template #tip>
              <p class="form-tip-small">
                {{ t('pipelineDashboard.attachmentTip') }}
              </p>
            </template>
          </el-upload>
        </el-form-item>
        <el-form-item :label="t('pipelineDashboard.labelSource')">
          <el-select v-model="newTask.source" style="width: 100%">
            <el-option :label="t('pipelineDashboard.sourceWeb')" value="web" />
            <el-option :label="t('pipelineDashboard.sourceApi')" value="api" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="newTask.autoRun">{{ t('pipelineDashboard.autoRunLabel') }}</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleCreateTask" :loading="creating">
          {{ newTask.autoRun ? t('pipelineDashboard.createAndRun') : t('pipelineDashboard.createTask') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import { Delete, Plus } from '@element-plus/icons-vue'
import { usePipelineStore } from '@/stores/pipeline'
import AutoTranslated from '@/components/AutoTranslated.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fetchPipelineHealth, autoRunPipeline, smartRunPipeline,
  fetchTraces, fetchApprovals, resolveApproval as apiResolveApproval, fetchAuditLog,
  fetchTemplates, fetchSDLCTemplates,
  uploadTaskAttachment,
  validateLocalPath,
} from '@/services/pipelineApi'
import { listPlans } from '@/services/planApi'
import type { UploadFile, UploadFiles, UploadInstance } from 'element-plus'
import type { SDLCTemplate } from '@/services/pipelineApi'
import type { PipelineEvent, PipelineTask } from '@/agents/types'
import { useI18n } from 'vue-i18n'
import { appLocaleToBcp47 } from '@/i18n'

const { t, locale } = useI18n()

const router = useRouter()

const pipelineStore = usePipelineStore()

const pendingPlanCount = ref(0)

const showCreateDialog = ref(false)
const creating = ref(false)
const uploadRef = ref<UploadInstance>()
const pendingFiles = ref<File[]>([])

function onPendingFileChange(_f: UploadFile, fileList: UploadFiles) {
  pendingFiles.value = fileList.map((x) => x.raw).filter((u): u is File => u instanceof File)
}
function onPendingFileRemove(_f: UploadFile, fileList: UploadFiles) {
  pendingFiles.value = fileList.map((x) => x.raw).filter((u): u is File => u instanceof File)
}

const RECENT_PROJECT_PATHS_KEY = 'agenthub-recent-project-paths'
const LOCAL_PROJECT_PARENT_KEY = 'agenthub-local-project-parent'
const MAX_RECENT_PATHS = 14

const localProjectParent = ref('')

function pathBasename(p: string): string {
  const normalized = p.replace(/\\/g, '/').replace(/\/+$/, '')
  const i = normalized.lastIndexOf('/')
  return i >= 0 ? normalized.slice(i + 1) : normalized
}

function pathDirname(p: string): string {
  const normalized = p.replace(/\\/g, '/').replace(/\/+$/, '')
  const i = normalized.lastIndexOf('/')
  if (i <= 0) return i === 0 ? '/' : ''
  return normalized.slice(0, i)
}

function persistLocalProjectParent() {
  const t = localProjectParent.value.trim()
  if (t) localStorage.setItem(LOCAL_PROJECT_PARENT_KEY, t)
  else localStorage.removeItem(LOCAL_PROJECT_PARENT_KEY)
}

function loadRecentProjectPaths(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_PROJECT_PATHS_KEY)
    const arr = raw ? JSON.parse(raw) : []
    return Array.isArray(arr) ? arr.filter((x: unknown) => typeof x === 'string' && (x as string).length > 1) : []
  } catch {
    return []
  }
}

function rememberProjectPath(p: string) {
  const t = p.trim()
  if (t.length < 2) return
  const next = [t, ...loadRecentProjectPaths().filter((x) => x !== t)].slice(0, MAX_RECENT_PATHS)
  localStorage.setItem(RECENT_PROJECT_PATHS_KEY, JSON.stringify(next))
}

function fetchPathSuggestions(queryString: string, cb: (rows: { value: string }[]) => void) {
  const recent = loadRecentProjectPaths()
  const q = queryString.trim().toLowerCase()
  const filtered = q ? recent.filter((p) => p.toLowerCase().includes(q)) : recent
  cb(filtered.slice(0, MAX_RECENT_PATHS).map((value) => ({ value })))
}

async function pasteProjectPathFromClipboard() {
  try {
    const t = await navigator.clipboard.readText()
    if (t?.trim()) {
      newTask.value.projectPath = t.trim()
      ElMessage.success(t('pipelineDashboard.elMessage_1'))
    } else {
      ElMessage.warning(t('pipelineDashboard.elMessage_2'))
    }
  } catch {
    ElMessage.warning(t('pipelineDashboard.elMessage_3'))
  }
}

async function pickLocalDirectoryAssist() {
  const w = window as Window & { showDirectoryPicker?: () => Promise<FileSystemDirectoryHandle> }
  if (typeof w.showDirectoryPicker !== 'function') {
    ElMessage.info(t('pipelineDashboard.elMessage_4'))
    return
  }
  try {
    const handle = await w.showDirectoryPicker()
    const name = handle.name
    const candidates: string[] = []
    const seen = new Set<string>()
    const add = (p: string | undefined) => {
      const t = p?.trim()
      if (!t) return
      if (seen.has(t)) return
      seen.add(t)
      candidates.push(t)
    }
    const recent = loadRecentProjectPaths()
    for (const p of recent) {
      if (pathBasename(p) === name) add(p)
    }
    const cur = newTask.value.projectPath?.trim()
    if (cur) {
      const d = pathDirname(cur)
      if (d) add(`${d.replace(/\/+$/, '')}/${name}`)
    }
    const parent = localProjectParent.value.trim() || localStorage.getItem(LOCAL_PROJECT_PARENT_KEY)?.trim()
    if (parent) add(`${parent.replace(/\/+$/, '')}/${name}`)
    for (const r of recent) {
      const d = pathDirname(r)
      if (d) add(`${d.replace(/\/+$/, '')}/${name}`)
    }
    for (const c of candidates) {
      try {
        const r = await validateLocalPath(c)
        if (r.ok && r.resolved) {
          newTask.value.projectPath = r.resolved
          rememberProjectPath(r.resolved)
          ElMessage.success(t('pipelineDashboard.elMessage_5'))
          return
        }
      } catch {
        /* try next candidate */
      }
    }
    await ElMessageBox.alert(
      t('pipelineDashboard.absPathMessage', { name }),
      t('pipelineDashboard.absPathTitle'),
      { confirmButtonText: t('pipelineDashboard.gotIt') },
    )
  } catch (e) {
    if ((e as Error).name === 'AbortError') return
    ElMessage.error(
      t('pipelineDashboard.elMessagePickDir', { message: e instanceof Error ? e.message : String(e) }),
    )
  }
}
const healthStatus = ref<Record<string, unknown>>({})

const activeObsTab = ref('traces')
const traces = ref<import('@/services/pipelineApi').TraceInfo[]>([])
const approvals = ref<import('@/services/pipelineApi').ApprovalItem[]>([])
const auditEntries = ref<import('@/services/pipelineApi').AuditEntry[]>([])

const obsTabs = computed(() => [
  { id: 'traces', label: t('pipelineDashboard.tabTraces'), badge: traces.value.length || null },
  { id: 'approvals', label: t('pipelineDashboard.tabApprovals'), badge: approvals.value.length || null },
  { id: 'audit', label: t('pipelineDashboard.tabAudit'), badge: null },
  { id: 'tiers', label: t('pipelineDashboard.tabTiers'), badge: null },
])

const modelTiers = computed(() => [
  {
    key: 'planning' as const,
    label: t('pipelineDashboard.tier1'),
    roles: ['orchestrator', 'lead-agent', 'Agent-ceo', 'Agent-cto', 'Agent-acceptance'],
  },
  {
    key: 'execution' as const,
    label: t('pipelineDashboard.tier2'),
    roles: ['product-manager', 'developer', 'qa-lead', 'Agent-product', 'Agent-developer'],
  },
  {
    key: 'routine' as const,
    label: t('pipelineDashboard.tier3'),
    roles: ['Agent-marketing', 'Agent-finance', 'Agent-devops', 'openclaw'],
  },
])

async function loadObsData() {
  try {
    const [t, a, al] = await Promise.all([
      fetchTraces().catch(() => ({ traces: [] })),
      fetchApprovals().catch(() => ({ approvals: [] })),
      fetchAuditLog().catch(() => ({ entries: [] })),
    ])
    traces.value = t.traces || []
    approvals.value = a.approvals || []
    auditEntries.value = al.entries || []
  } catch { /* ignore */ }
}

async function handleApproval(id: string, approved: boolean) {
  try {
    await apiResolveApproval(id, approved)
    ElMessage.success(approved ? t('pipelineDashboard.elMessageApproved') : t('pipelineDashboard.elMessageRejected'))
    await loadObsData()
  } catch (e) {
    ElMessage.error(
      t('pipelineDashboard.elMessageApprovalError', { message: e instanceof Error ? e.message : String(e) }),
    )
  }
}

const templates = ref<Record<string, { label: string; description: string; icon: string; stageCount: number; stages: any[] }>>({})
const sdlcTemplates = ref<Record<string, SDLCTemplate>>({})

const selectedTemplateStages = computed(() => {
  const tmpl = sdlcTemplates.value[newTask.value.template]
  return tmpl?.stages ?? []
})

function selectTemplate(key: string) {
  newTask.value.template = key
}

const newTask = ref({
  title: '',
  description: '',
  source: 'web',
  template: 'full',
  autoRun: true,
  projectMode: 'none' as 'none' | 'git' | 'local',
  repoUrl: '',
  projectPath: '',
})

const stages = computed(() => [
  { id: 'planning', label: t('pipelineDashboard.stagePlanning') },
  { id: 'architecture', label: t('pipelineDashboard.stageArchitecture') },
  { id: 'development', label: t('pipelineDashboard.stageDevelopment') },
  { id: 'testing', label: t('pipelineDashboard.stageTesting') },
  { id: 'reviewing', label: t('pipelineDashboard.stageReviewing') },
  { id: 'deployment', label: t('pipelineDashboard.stageDeployment') },
  { id: 'done', label: t('pipelineDashboard.stageDone') },
])

const stageColors: Record<string, string> = {
  planning: '#6366f1',
  architecture: '#3b82f6',
  development: '#14b8a6',
  testing: '#f59e0b',
  reviewing: '#ef4444',
  deployment: '#8b5cf6',
  done: '#22c55e',
}

function stageColor(id: string) {
  return stageColors[id] || '#666'
}

const planningTasksList = computed(() => pipelineStore.tasksByStage['planning'] ?? [])

const planningSelectedIds = shallowRef(new Set<string>())

const planningSelectedCount = computed(() => {
  let n = 0
  for (const task of planningTasksList.value) {
    if (planningSelectedIds.value.has(task.id)) n++
  }
  return n
})

const planningSelectAllChecked = computed(() => {
  const list = planningTasksList.value
  return list.length > 0 && planningSelectedCount.value === list.length
})

const planningSelectIndeterminate = computed(() => {
  const list = planningTasksList.value
  const c = planningSelectedCount.value
  return c > 0 && c < list.length
})

watch(planningTasksList, (list) => {
  const idSet = new Set(list.map((t) => t.id))
  const next = new Set<string>()
  for (const id of planningSelectedIds.value) {
    if (idSet.has(id)) next.add(id)
  }
  if (next.size !== planningSelectedIds.value.size) {
    planningSelectedIds.value = next
  }
})

function onPlanningSelectAll(checked: boolean | string | number) {
  const on = Boolean(checked)
  const list = planningTasksList.value
  planningSelectedIds.value = on ? new Set(list.map((t) => t.id)) : new Set()
}

function onPlanningRowCheck(taskId: string, val: boolean | string | number) {
  const next = new Set(planningSelectedIds.value)
  if (Boolean(val)) next.add(taskId)
  else next.delete(taskId)
  planningSelectedIds.value = next
}

async function confirmDeletePlanningBulk() {
  const ids = planningTasksList.value
    .map((t) => t.id)
    .filter((id) => planningSelectedIds.value.has(id))
  if (!ids.length) return
  try {
    await ElMessageBox.confirm(
      t('pipelineDashboard.confirmBulkDeletePlanningMessage', { count: ids.length }),
      t('pipelineDashboard.titleBulkDeletePlanning'),
      {
        type: 'warning',
        confirmButtonText: t('common.delete'),
        cancelButtonText: t('common.cancel'),
      },
    )
    for (const id of ids) {
      await pipelineStore.removeTask(id)
    }
    planningSelectedIds.value = new Set()
    ElMessage.success(t('pipelineDashboard.elMessageBulkDeletedPlanning', { count: ids.length }))
  } catch (e: unknown) {
    if (e === 'cancel') return
    ElMessage.error(
      t('pipelineDashboard.elMessageDeleteError', { message: e instanceof Error ? e.message : String(e) }),
    )
  }
}

function sourceTagType(source: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' {
  const map: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
    feishu: 'warning',
    qq: 'success',
    web: 'info',
    api: 'primary',
 }
  return map[source] ?? 'info'
}

async function confirmDeletePlanningTask(task: PipelineTask) {
  try {
    await ElMessageBox.confirm(
      t('pipelineDashboard.confirmDeleteTaskMessage', { title: task.title }),
      t('pipelineDashboard.title_1'),
      {
        type: 'warning',
        confirmButtonText: t('common.delete'),
        cancelButtonText: t('common.cancel'),
      },
    )
    await pipelineStore.removeTask(task.id)
    const next = new Set(planningSelectedIds.value)
    next.delete(task.id)
    planningSelectedIds.value = next
    ElMessage.success(t('pipelineDashboard.elMessage_6'))
  } catch (e: unknown) {
    if (e === 'cancel') return
    ElMessage.error(
      t('pipelineDashboard.elMessageDeleteError', { message: e instanceof Error ? e.message : String(e) }),
    )
  }
}

function timeAgo(ts: number | string | undefined) {
  if (!ts) return ''
  const ms = typeof ts === 'string' ? new Date(ts).getTime() : (ts < 1e12 ? ts * 1000 : ts)
  const diff = Date.now() - ms
  if (diff < 60_000) return t('taskTable.justNow')
  if (diff < 3600_000) return t('taskTable.minutesAgo', { n: Math.floor(diff / 60_000) })
  if (diff < 86400_000) return t('taskTable.hoursAgo', { n: Math.floor(diff / 3600_000) })
  return t('taskTable.daysAgo', { n: Math.floor(diff / 86400_000) })
}

function formatTime(ts: number | string | undefined) {
  if (!ts) return ''
  const date = typeof ts === 'string' ? new Date(ts) : new Date(ts < 1e12 ? ts * 1000 : ts)
  return date.toLocaleTimeString(appLocaleToBcp47(locale.value), {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

const recentEvents = computed(() => {
  return [...pipelineStore.eventLog].reverse().slice(0, 20)
})

function eventColor(event: string) {
  if (event.includes('completed') || event.includes('created')) return '#22c55e'
  if (event.includes('advanced') || event.includes('processing')) return '#3b82f6'
  if (event.includes('rejected') || event.includes('error')) return '#ef4444'
  if (event.includes('executor') || event.includes('building')) return '#f59e0b'
  if (event.includes('auto-start') || event.includes('queued')) return '#8b5cf6'
  return '#666'
}

function eventLabel(event: string) {
  switch (event) {
    case 'task:created': return t('pipelineDashboard.events.taskCreated')
    case 'task:updated': return t('pipelineDashboard.events.taskUpdated')
    case 'task:stage-advanced': return t('pipelineDashboard.events.stageAdvanced')
    case 'task:rejected': return t('pipelineDashboard.events.taskRejected')
    case 'task:deleted': return t('pipelineDashboard.events.taskDeleted')
    case 'openclaw:intake': return t('pipelineDashboard.events.openclawIntake')
    case 'stage:queued': return t('pipelineDashboard.events.stageQueued')
    case 'stage:processing': return t('pipelineDashboard.events.stageProcessing')
    case 'stage:completed': return t('pipelineDashboard.events.stageCompleted')
    case 'stage:error': return t('pipelineDashboard.events.stageError')
    case 'pipeline:auto-start': return t('pipelineDashboard.events.autoStart')
    case 'pipeline:auto-completed': return t('pipelineDashboard.events.autoCompleted')
    case 'pipeline:auto-paused': return t('pipelineDashboard.events.autoPaused')
    case 'pipeline:auto-error': return t('pipelineDashboard.events.autoError')
    case 'executor:started': return t('pipelineDashboard.events.executorStarted')
    case 'executor:completed': return t('pipelineDashboard.events.executorCompleted')
    case 'executor:error': return t('pipelineDashboard.events.executorError')
    case 'stage:quality-gate': return t('pipelineDashboard.events.qualityGate')
    case 'stage:gate-overridden': return t('pipelineDashboard.events.gateOverridden')
    case 'stage:peer-reviewing': return t('pipelineDashboard.events.peerReviewing')
    case 'stage:peer-review-approved': return t('pipelineDashboard.events.peerReviewApproved')
    case 'stage:peer-review-rejected': return t('pipelineDashboard.events.peerReviewRejected')
    case 'stage:peer-review-error': return t('pipelineDashboard.events.peerReviewError')
    case 'stage:rework': return t('pipelineDashboard.events.rework')
    case 'stage:awaiting-approval': return t('pipelineDashboard.events.awaitingApproval')
    case 'stage:approval-granted': return t('pipelineDashboard.events.approvalGranted')
    case 'stage:approval-denied': return t('pipelineDashboard.events.approvalDenied')
    case 'pipeline:resumed': return t('pipelineDashboard.events.pipelineResumed')
    case 'connected': return t('pipelineDashboard.events.connected')
    default: return event
  }
}

function eventDetail(event: PipelineEvent) {
  const data = event.data as Record<string, unknown>
  if (data?.title) return String(data.title)
  if (data?.taskId) {
    return t('pipelineDashboard.eventTaskPrefix', { id: `${String(data.taskId).slice(0, 8)}...` })
  }
  return ''
}

async function handleCreateTask() {
  if (!newTask.value.title.trim()) {
    ElMessage.warning(t('pipelineDashboard.elMessage_7'))
    return
  }
  creating.value = true
  try {
    const task = await pipelineStore.createTask({
      title: newTask.value.title,
      description: newTask.value.description,
      source: newTask.value.source,
      template: newTask.value.template || undefined,
      repo_url: newTask.value.projectMode === 'git' ? newTask.value.repoUrl || undefined : undefined,
      project_path: newTask.value.projectMode === 'local' ? newTask.value.projectPath || undefined : undefined,
    })

    if (newTask.value.projectMode === 'local' && newTask.value.projectPath?.trim()) {
      rememberProjectPath(newTask.value.projectPath.trim())
    }

    const files = [...pendingFiles.value]
    for (const f of files) {
      try {
        await uploadTaskAttachment(task.id, f)
      } catch (err) {
        ElMessage.warning(
          t('pipelineDashboard.elMessageUploadFail', {
            name: f.name,
            message: err instanceof Error ? err.message : String(err),
          }),
        )
      }
    }
    pendingFiles.value = []
    uploadRef.value?.clearFiles()
    await pipelineStore.loadTasks()

    showCreateDialog.value = false

    if (newTask.value.autoRun) {
      await smartRunPipeline(task.id)
      router.push(`/pipeline/task/${task.id}`)
    }

    newTask.value = { title: '', description: '', source: 'web', template: 'full', autoRun: true, projectMode: 'none', repoUrl: '', projectPath: '' }
  } catch (e: unknown) {
    ElMessage.error(
      t('pipelineDashboard.elMessageCreateError', { message: e instanceof Error ? e.message : String(e) }),
    )
  } finally {
    creating.value = false
  }
}

let planPollTimer: ReturnType<typeof setInterval> | null = null

async function refreshPendingPlanCount() {
  try {
    const res = await listPlans()
    pendingPlanCount.value = res.count ?? res.items?.length ?? 0
  } catch {
    /* plan inbox optional */
  }
}

onMounted(async () => {
  localProjectParent.value = localStorage.getItem(LOCAL_PROJECT_PARENT_KEY) || ''
  pipelineStore.loadTasks()
  pipelineStore.startEventStream()
  try {
    healthStatus.value = await fetchPipelineHealth()
  } catch {
    healthStatus.value = { pipeline: 'offline' }
  }
  try {
    templates.value = await fetchTemplates()
  } catch {
    /* templates optional */
  }
  try {
    sdlcTemplates.value = await fetchSDLCTemplates()
  } catch {
    /* sdlc templates optional */
  }
  loadObsData()
  refreshPendingPlanCount()
  planPollTimer = setInterval(refreshPendingPlanCount, 15_000)
})

onUnmounted(() => {
  pipelineStore.stopEventStream()
  if (planPollTimer) clearInterval(planPollTimer)
})
</script>

<style scoped>
.pipeline-dashboard {
  padding: 32px;
  max-width: 1400px;
  margin: 0 auto;
}

.pipeline-header {
  margin-bottom: 28px;
}

.header-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.pipeline-header h1 {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.subtitle {
  color: var(--text-muted);
  margin-top: 6px;
  font-size: 14px;
}

.pipeline-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 16px;
  margin-bottom: 32px;
}

.stat-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 20px;
  text-align: center;
}

.stat-card--clickable {
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.stat-card--clickable:hover {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 20%, transparent);
}

.stat-number {
  font-size: 32px;
  font-weight: 700;
  color: var(--accent);
}

.stat-highlight {
  color: #e6a23c;
  animation: pulse-glow 2s ease-in-out infinite;
}

@keyframes pulse-glow {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.65; }
}

.stat-label {
  font-size: 13px;
  color: var(--text-muted);
  margin-top: 4px;
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 16px;
}

.pipeline-board {
  margin-bottom: 32px;
}

.stage-columns-scroll {
  overflow-x: auto;
  overflow-y: visible;
  padding-bottom: 8px;
  margin: 0 -8px;
  padding-left: 8px;
  padding-right: 8px;
  -webkit-overflow-scrolling: touch;
}

.stage-columns {
  display: flex;
  flex-direction: row;
  flex-wrap: nowrap;
  align-items: stretch;
  gap: 12px;
  min-height: 220px;
}

.stage-column {
  flex: 0 0 232px;
  width: 232px;
  min-width: 232px;
  max-width: 232px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  min-height: 200px;
}

.stage-column.has-tasks {
  border-color: var(--accent);
}

.stage-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-color);
  min-width: 0;
}

.stage-badge-wrap {
  flex: 1;
  min-width: 0;
}

.stage-badge-wrap :deep(.el-badge__content) {
  top: 2px;
  right: 0;
}

.stage-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.stage-name {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding-right: 4px;
}

.stage-tasks {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  max-height: min(52vh, 520px);
  overflow-y: auto;
  overflow-x: hidden;
}

.task-card {
  flex-shrink: 0;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
  position: relative;
  z-index: 0;
}

.planning-bulk-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  padding: 4px 2px 10px;
  margin: 0 0 4px;
  border-bottom: 1px solid var(--border-color);
}

.planning-bulk-bar :deep(.el-checkbox) {
  margin-right: 0;
}

.task-card-body {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  min-width: 0;
}

.task-card-main {
  flex: 1;
  min-width: 0;
}

.task-planning-check {
  flex-shrink: 0;
  margin-top: -4px;
}

.task-planning-check :deep(.el-checkbox__label) {
  display: none;
}

.task-card:hover {
  border-color: var(--accent);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
  z-index: 1;
}

.task-card-top {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 6px;
  min-width: 0;
}

.task-delete {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  margin-top: -1px;
  padding: 0;
  border: none;
  border-radius: 6px;
  color: var(--text-muted);
  background: transparent;
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
}

.task-delete:hover {
  color: #f87171;
  background: rgba(248, 113, 113, 0.12);
}

.task-title {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-title :deep(.auto-translated) {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.task-time {
  font-size: 11px;
  color: var(--text-muted);
}

.stage-empty {
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
  padding: 20px 0;
}

.pipeline-events {
  margin-top: 24px;
}

.event-list {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 12px;
  max-height: 300px;
  overflow-y: auto;
}

.event-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  font-size: 12px;
}

.event-item:hover {
  background: var(--bg-tertiary);
}

.event-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.event-type {
  font-weight: 600;
  color: var(--text-secondary);
  min-width: 60px;
}

.event-detail {
  color: var(--text-muted);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-time {
  color: var(--text-muted);
  font-size: 11px;
  flex-shrink: 0;
}

/* ===== Observability Panel ===== */

.observability-panel {
  margin-top: 32px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  overflow: hidden;
}

.panel-tabs {
  display: flex;
  border-bottom: 1px solid var(--border-color);
  padding: 0 16px;
  gap: 4px;
}

.panel-tab {
  padding: 12px 16px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-muted);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 6px;
}

.panel-tab:hover { color: var(--text-primary); }

.panel-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.tab-badge {
  background: var(--accent);
  color: #fff;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 10px;
  font-weight: 600;
}

.panel-content {
  padding: 16px;
  max-height: 420px;
  overflow-y: auto;
}

.empty-state {
  text-align: center;
  color: var(--text-muted);
  padding: 40px 0;
  font-size: 13px;
}

/* Trace cards */
.trace-list { display: flex; flex-direction: column; gap: 10px; }

.trace-card {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px 14px;
}

.trace-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.trace-task {
  font-weight: 600;
  font-size: 13px;
  color: var(--text-primary);
  font-family: monospace;
}

.trace-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-bottom: 6px;
}

.metric { display: flex; flex-direction: column; gap: 2px; }
.metric-label { font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }
.metric-value { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.model-tag { font-family: monospace; font-size: 11px; }

.trace-models {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
  flex-wrap: wrap;
}

.tier-planning { color: #ef4444; }
.tier-execution { color: #f59e0b; }
.tier-routine { color: #22c55e; }
.tier-default { color: var(--text-muted); }

.trace-verify {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  padding-top: 8px;
  border-top: 1px solid var(--border-color);
}

.verify-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
}

.verify-pass { background: #dcfce7; color: #166534; }
.verify-warn { background: #fef3c7; color: #92400e; }
.verify-fail { background: #fecaca; color: #991b1b; }

.verify-detail {
  font-size: 11px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 4px;
}

.verify-dot-pass::before, .verify-dot-warn::before, .verify-dot-fail::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.verify-dot-pass::before { background: #22c55e; }
.verify-dot-warn::before { background: #f59e0b; }
.verify-dot-fail::before { background: #ef4444; }

/* Approval cards */
.approval-list { display: flex; flex-direction: column; gap: 8px; }

.approval-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--bg-tertiary);
  border: 1px solid #f59e0b40;
  border-radius: 8px;
  padding: 12px;
}

.approval-info { display: flex; align-items: center; gap: 12px; font-size: 13px; }
.approval-action { font-weight: 600; color: var(--text-primary); }
.approval-desc { color: var(--text-secondary); font-size: 12px; }
.approval-role { color: var(--text-muted); }
.approval-time { color: var(--text-muted); font-size: 11px; }
.approval-actions { display: flex; gap: 8px; }

/* Audit log */
.audit-list { display: flex; flex-direction: column; gap: 4px; }

.audit-entry {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  font-size: 12px;
  border-radius: 4px;
}

.audit-entry:hover { background: var(--bg-tertiary); }

.audit-outcome {
  font-weight: 600;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  min-width: 70px;
  text-align: center;
}

.outcome-auto_approved { background: #dcfce7; color: #166534; }
.outcome-approved { background: #dcfce7; color: #166534; }
.outcome-rejected { background: #fecaca; color: #991b1b; }
.outcome-blocked { background: #fecaca; color: #991b1b; }
.outcome-pending_approval { background: #fef3c7; color: #92400e; }
.outcome-auto_approved_with_warning { background: #fef3c7; color: #92400e; }

.audit-action { color: var(--text-primary); font-weight: 500; }
.audit-role { color: var(--text-muted); }
.audit-time { color: var(--text-muted); margin-left: auto; }

/* Model tiers */
.tier-info { display: flex; flex-direction: column; gap: 20px; }

.tier-group { padding: 12px; background: var(--bg-tertiary); border-radius: 8px; }

.tier-name {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
}

.tier-roles { display: flex; flex-wrap: wrap; gap: 6px; }
.tier-role-tag { font-family: monospace; }

/* Template selector */
.template-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
  width: 100%;
}
.template-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--border-color, #e4e7ed);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.template-card:hover {
  border-color: var(--el-color-primary-light-3, #79bbff);
  background: var(--bg-tertiary, #f5f7fa);
}
.template-card.active {
  border-color: var(--el-color-primary, #409eff);
  background: var(--el-color-primary-light-9, #ecf5ff);
}
.template-icon { font-size: 20px; flex-shrink: 0; }
.template-info {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
.template-label { font-size: 13px; font-weight: 600; white-space: nowrap; }
.template-desc {
  font-size: 11px;
  color: var(--text-muted, #909399);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.template-badges {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex-shrink: 0;
}

/* Template preview */
.template-preview {
  margin-top: 12px;
  padding: 12px;
  background: var(--bg-tertiary, #f0f2f5);
  border-radius: 8px;
  border: 1px solid var(--border-color, #e4e7ed);
}
.template-preview-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary, #606266);
  margin-bottom: 8px;
}
.template-stage-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.template-stage-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 4px;
  background: var(--bg-secondary, #fff);
  font-size: 12px;
}
.tps-idx {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--accent, #409eff);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
  flex-shrink: 0;
}
.tps-label {
  font-weight: 600;
  color: var(--text-primary, #303133);
  min-width: 80px;
}
.tps-role {
  color: var(--text-muted, #909399);
  font-family: monospace;
  font-size: 11px;
  flex: 1;
}
.tps-gate {
  font-size: 11px;
  font-weight: 600;
  color: #f59e0b;
  flex-shrink: 0;
}

.form-tip-small {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-muted, #909399);
  line-height: 1.45;
}

.form-tip-small .inline-code {
  font-family: ui-monospace, monospace;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg-tertiary, #2a2a3a);
  color: var(--text-secondary, #a0a0b0);
}

.local-path-field {
  margin-top: 4px;
}

.local-path-inner {
  display: flex;
  align-items: stretch;
  width: 100%;
  border: 1px solid var(--border-color, #2a2a3a);
  border-radius: 4px;
  overflow: hidden;
  background: var(--bg-secondary, #16161c);
}

.path-prepend {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  padding: 0 12px;
  font-size: 13px;
  color: var(--text-muted, #909399);
  background: var(--bg-tertiary, #1e1e28);
  border-right: 1px solid var(--border-color, #2a2a3a);
}

.path-autocomplete {
  flex: 1;
  min-width: 0;
}

.path-autocomplete :deep(.el-input__wrapper) {
  box-shadow: none !important;
  border: none !important;
  border-radius: 0;
  background: transparent;
}

.local-project-parent-input {
  margin-top: 8px;
  width: 100%;
}

.local-path-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}
</style>

<style>
/* el-dialog teleports to body — must be unscoped */
.create-task-dialog.el-dialog {
  width: min(92vw, 760px) !important;
  max-width: 760px;
}
.create-task-dialog .el-dialog__body {
  max-height: min(70vh, 640px);
  overflow-y: auto;
}
</style>
