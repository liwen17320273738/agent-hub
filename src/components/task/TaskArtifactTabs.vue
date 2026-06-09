<template>
  <div class="task-artifact-tabs">
    <el-alert
      v-if="taskStatus === 'active'"
      type="info"
      :closable="false"
      show-icon
      class="artifacts-running-hint"
      :title="t('artifactTabs.runningHintTitle')"
      :description="t('artifactTabs.runningHintBody')"
    />
    <ArtifactContractPanel
      class="contract-above-bar"
      :task-id="taskId"
      :task-status="taskStatus"
    />
    <DesignTokenPanel
      :task-id="taskId"
    />
    <!-- Completion bar: delivery artifact types (registry-aligned) -->
    <div class="completion-bar">
      <div
        v-for="tab in TAB_DEFS"
        :key="tab.type"
        class="completion-item"
        :class="statusClass(tab.type)"
        :title="statusTooltip(tab.type)"
        @click="activeTab = tab.type"
      >
        <span class="completion-icon">{{ tab.icon }}</span>
        <span class="completion-label">{{ tab.short }}</span>
      </div>
    </div>

    <el-tabs
      v-model="activeTab"
      type="card"
      class="artifact-tabs"
    >
      <el-tab-pane
        v-for="tab in TAB_DEFS"
        :key="tab.type"
        :name="tab.type"
        :lazy="true"
      >
        <template #label>
          <span class="tab-label">
            <span class="tab-icon">{{ tab.icon }}</span>
            {{ tab.label }}
            <el-badge
              v-if="artifactStatus(tab.type) === 'superseded'"
              :value="t('artifactTabs.supersededBadge')"
              type="warning"
              class="tab-badge"
            />
          </span>
        </template>

        <TaskCodeTab
          v-if="tab.type === 'code_link'"
          :task-id="taskId"
        />
        <UiMockupCard
          v-else-if="tab.type === 'ui_mockup' || tab.type === 'ui_mockup_html'"
          :task-id="taskId"
          :focus="tab.type === 'ui_mockup_html' ? 'ui_mockup_html' : 'ui_mockup'"
          :refresh-nonce="refreshNonce"
        />
        <TaskArchDiagram
          v-else-if="tab.type === 'architecture_diagram'"
          :task-id="taskId"
          :refresh-nonce="refreshNonce"
        />
        <TaskQATab
          v-else-if="tab.type === 'test_report'"
          :task-id="taskId"
          :refresh-nonce="refreshNonce"
        />
        <DeployPreviewCard
          v-else-if="tab.type === 'preview_url'"
          :task-id="taskId"
          :refresh-nonce="refreshNonce"
        />
        <TaskDocTab
          v-else
          :task-id="taskId"
          :artifact-type="tab.type"
          :display-name="tab.label"
          :icon="tab.icon"
          :draft-content="draftByType[tab.type]"
        />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import TaskDocTab from './TaskDocTab.vue'
import TaskCodeTab from './TaskCodeTab.vue'
import TaskQATab from './TaskQATab.vue'
import DeployPreviewCard from './DeployPreviewCard.vue'
import UiMockupCard from '../design/UiMockupCard.vue'
import TaskArchDiagram from './TaskArchDiagram.vue'
import ArtifactContractPanel from './ArtifactContractPanel.vue'
import DesignTokenPanel from './DesignTokenPanel.vue'
import { getAuthToken } from '@/services/api'

const { t } = useI18n()

const TAB_BASE = [
  { type: 'brief', icon: '📋' },
  { type: 'prd', icon: '📝' },
  { type: 'ui_spec', icon: '🎨' },
  { type: 'ui_mockup', icon: '🖼️' },
  { type: 'ui_mockup_html', icon: '🖌️' },
  { type: 'architecture', icon: '🏗️' },
  { type: 'architecture_diagram', icon: '📐' },
  { type: 'implementation', icon: '💻' },
  { type: 'code_link', icon: '📦' },
  { type: 'test_report', icon: '🧪' },
  { type: 'acceptance', icon: '✅' },
  { type: 'ops_runbook', icon: '🔧' },
  { type: 'preview_url', icon: '🔗' },
] as const

const props = defineProps<{
  taskId: string
  readonly?: boolean
  /** Lifecycle status of the task — forwarded to ArtifactContractPanel so it
   *  can soften language / collapse details once the task is closed. */
  taskStatus?: string
  /** Live LLM draft keyed by artifact type (from stage output chunks). */
  draftByType?: Record<string, string>
  /** Bump to force visual artifact tabs to refetch. */
  refreshNonce?: number
}>()

const activeTab = ref('brief')

interface ArtifactSummaryItem {
  type_key: string
  has_content: boolean
  version: number
  status: string
}

const artifactSummary = ref<ArtifactSummaryItem[]>([])
const TAB_DEFS = computed(() =>
  TAB_BASE.map((tab) => ({
    ...tab,
    label: t(`artifactTabs.${tab.type}.label` as any),
    short: t(`artifactTabs.${tab.type}.short` as any),
  })),
)

const draftByType = computed(() => props.draftByType || {})

function artifactStatus(type: string): string {
  if (draftByType.value[type]?.trim()) return 'generating'
  const item = artifactSummary.value.find(a => a.type_key === type)
  return item?.status || 'empty'
}

function statusClass(type: string): string {
  if (draftByType.value[type]?.trim()) return 'status-generating'
  const item = artifactSummary.value.find(a => a.type_key === type)
  if (!item || item.status === 'empty') return 'status-empty'
  if (item.status === 'superseded') return 'status-superseded'
  if (item.has_content) return 'status-done'
  return 'status-empty'
}

function statusTooltip(type: string): string {
  const tab = TAB_DEFS.value.find(t => t.type === type)
  const label = tab?.label || type
  const item = artifactSummary.value.find(a => a.type_key === type)
  if (draftByType.value[type]?.trim()) return t('artifactTabs.tooltipGenerating', { label })
  if (!item || item.status === 'empty') return t('artifactTabs.tooltipEmpty', { label })
  if (item.status === 'superseded') return t('artifactTabs.tooltipSuperseded', { label, version: item.version })
  if (item.has_content) return t('artifactTabs.tooltipDone', { label, version: item.version })
  return t('artifactTabs.tooltipBlank', { label })
}

async function loadSummary() {
  try {
    const baseUrl = import.meta.env.VITE_API_BASE || '/api'
    const token = getAuthToken()
    const res = await fetch(
      `${baseUrl}/tasks/${props.taskId}/artifacts`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    )
    if (!res.ok) return
    const data = await res.json()
    artifactSummary.value = data.artifacts || []
  } catch { /* silent */ }
}

let summaryPollTimer: ReturnType<typeof setInterval> | null = null

function startSummaryPoll() {
  stopSummaryPoll()
  if (props.taskStatus !== 'active' && props.taskStatus !== 'running') return
  summaryPollTimer = setInterval(() => { loadSummary() }, 12_000)
}

function stopSummaryPoll() {
  if (summaryPollTimer !== null) {
    clearInterval(summaryPollTimer)
    summaryPollTimer = null
  }
}

defineExpose({ refresh: loadSummary })

onMounted(() => {
  loadSummary()
  startSummaryPoll()
})
onUnmounted(() => stopSummaryPoll())
watch(() => props.taskId, () => loadSummary())
watch(() => props.taskStatus, () => startSummaryPoll())
watch(() => props.refreshNonce, () => loadSummary())
</script>

<style scoped>
.task-artifact-tabs { margin-bottom: 24px; }

.contract-above-bar :deep(.el-card) {
  border: 1px solid var(--el-border-color-lighter);
}

.completion-bar {
  display: flex;
  gap: 3px;
  padding: 12px 4px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.completion-item {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  user-select: none;
  border: 1px solid transparent;
}
.completion-item:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}

.completion-icon { font-size: 15px; }
.completion-label { font-weight: 500; }

.status-empty {
  background: #f5f7fa;
  color: #a8abb2;
  border-color: #ebeef5;
}
.status-generating {
  background: rgba(124, 92, 255, 0.12);
  color: #7c5cff;
  border-color: rgba(124, 92, 255, 0.35);
  animation: generating-pulse 1.6s ease-in-out infinite;
}
@keyframes generating-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.72; }
}

.status-done {
  background: linear-gradient(135deg, #f0f9eb, #e1f3d8);
  color: #529b2e;
  border-color: #c2e7b0;
}
.status-superseded {
  background: #fef0f0;
  color: #f56c6c;
  border-color: #fbc4c4;
}

.artifact-tabs :deep(.el-tabs__content) {
  padding: 8px 4px;
}

.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.tab-icon { font-size: 14px; }
.tab-badge { margin-left: 4px; }
</style>
