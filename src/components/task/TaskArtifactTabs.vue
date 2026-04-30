<template>
  <div class="task-artifact-tabs">
    <!-- Completion bar: 8 icons showing artifact status -->
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

    <el-tabs v-model="activeTab" type="border-card" class="artifact-tabs">
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
              value="已打回"
              type="warning"
              class="tab-badge"
            />
          </span>
        </template>

        <TaskCodeTab
          v-if="tab.type === 'code_link'"
          :task-id="taskId"
        />
        <TaskDocTab
          v-else
          :task-id="taskId"
          :artifact-type="tab.type"
          :display-name="tab.label"
          :icon="tab.icon"
        />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import TaskDocTab from './TaskDocTab.vue'
import TaskCodeTab from './TaskCodeTab.vue'
import { getAuthToken } from '@/services/api'

const TAB_DEFS = [
  { type: 'brief',          icon: '📋', label: '需求',     short: '需求' },
  { type: 'prd',            icon: '📝', label: 'PRD',      short: 'PRD' },
  { type: 'ui_spec',        icon: '🎨', label: 'UI 规格',  short: 'UI' },
  { type: 'architecture',   icon: '🏗️', label: '技术方案', short: '架构' },
  { type: 'code_link',      icon: '📦', label: '代码',     short: '代码' },
  { type: 'test_report',    icon: '🧪', label: '测试',     short: '测试' },
  { type: 'acceptance',     icon: '✅', label: '验收',     short: '验收' },
  { type: 'ops_runbook',    icon: '🔧', label: '运维',     short: '运维' },
]

const props = defineProps<{
  taskId: string
  readonly?: boolean
}>()

const activeTab = ref('brief')

interface ArtifactSummaryItem {
  type_key: string
  has_content: boolean
  version: number
  status: string
}

const artifactSummary = ref<ArtifactSummaryItem[]>([])

function artifactStatus(type: string): string {
  const item = artifactSummary.value.find(a => a.type_key === type)
  return item?.status || 'empty'
}

function statusClass(type: string): string {
  const item = artifactSummary.value.find(a => a.type_key === type)
  if (!item || item.status === 'empty') return 'status-empty'
  if (item.status === 'superseded') return 'status-superseded'
  if (item.has_content) return 'status-done'
  return 'status-empty'
}

function statusTooltip(type: string): string {
  const tab = TAB_DEFS.find(t => t.type === type)
  const label = tab?.label || type
  const item = artifactSummary.value.find(a => a.type_key === type)
  if (!item || item.status === 'empty') return `${label}：未生成`
  if (item.status === 'superseded') return `${label}：已打回 (v${item.version})`
  if (item.has_content) return `${label}：已完成 (v${item.version})`
  return `${label}：空`
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

onMounted(() => loadSummary())
watch(() => props.taskId, () => loadSummary())
</script>

<style scoped>
.task-artifact-tabs { margin-bottom: 24px; }

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
