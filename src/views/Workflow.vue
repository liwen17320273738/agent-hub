<template>
  <div class="workflow-view">
    <h1>{{ t('workflow.title') }}</h1>
    <p class="view-subtitle">{{ t('workflow.subtitle') }}</p>

    <el-tabs v-model="activeTab">
      <el-tab-pane :label="t('workflow.tabPipeline')" name="pipeline">
        <div class="workflow-action-bar">
          <el-button type="primary" @click="$router.push('/pipeline')">
            {{ t('workflow.openPipelinePanel') }}
          </el-button>
        </div>
        <TaskTable :tasks="recentTasks" :empty-text="t('workflow.noTasks')" @click-task="goTask" />
      </el-tab-pane>

      <el-tab-pane :label="t('workflow.tabBuilder')" name="builder">
        <div class="workflow-action-bar">
          <el-button type="primary" @click="$router.push('/workflow-builder')">
            {{ t('workflow.openBuilder') }}
          </el-button>
        </div>
        <el-empty :description="t('workflow.builderHint')" />
      </el-tab-pane>

      <el-tab-pane :label="t('workflow.tabRun')" name="run">
        <div class="workflow-action-bar">
          <el-select v-model="selectedWorkflowId" :placeholder="t('workflow.selectPlaceholder')" style="width: 300px; margin-right: 12px">
            <el-option
              v-for="wf in savedWorkflows"
              :key="wf.id"
              :label="wf.name"
              :value="wf.id"
            />
          </el-select>
          <el-button type="primary" :loading="running" :disabled="!selectedWorkflowId" @click="runWorkflow">
            {{ t('workflow.runWorkflow') }}
          </el-button>
        </div>

        <div v-if="runResult" class="run-result">
          <div class="run-header">
            <el-tag :type="runResult.status === 'done' ? 'success' : runResult.status === 'failed' ? 'danger' : 'primary'" size="default">
              {{ runResult.status === 'done' ? t('workflow.statusDone') : runResult.status === 'failed' ? t('workflow.statusFailed') : t('workflow.statusRunning') }}
            </el-tag>
            <span class="run-time">{{ t('workflow.elapsed', { s: (runResult.elapsed_ms / 1000).toFixed(1) }) }}</span>
          </div>
          <div v-if="runResult.error" class="run-error">
            <el-alert type="error" :closable="false" show-icon>{{ runResult.error }}</el-alert>
          </div>
          <div class="run-nodes">
            <div v-for="(nodeRes, nodeId) in runResult.node_results" :key="nodeId" class="run-node-card">
              <div class="node-header">
                <span class="node-id">{{ nodeId }}</span>
                <el-tag :type="nodeRes.status === 'done' ? 'success' : 'danger'" size="small">{{ nodeRes.status }}</el-tag>
              </div>
              <div v-if="nodeRes.output" class="node-output">{{ nodeRes.output.slice(0, 500) }}{{ nodeRes.output.length > 500 ? '…' : '' }}</div>
              <div v-if="nodeRes.error" class="node-error">{{ nodeRes.error }}</div>
            </div>
          </div>
        </div>

        <el-empty v-else-if="!running" :description="t('workflow.runEmpty')" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { fetchTasks } from '@/services/pipelineApi'
import { apiUrl } from '@/services/enterpriseApi'
import { getAuthToken } from '@/services/api'
import type { PipelineTask } from '@/agents/types'
import TaskTable from '@/components/inbox/TaskTable.vue'

const router = useRouter()
const { t } = useI18n()
const activeTab = ref('pipeline')
const recentTasks = ref<PipelineTask[]>([])

interface SavedWorkflow { id: string; name: string }
const savedWorkflows = ref<SavedWorkflow[]>([])
const selectedWorkflowId = ref('')
const running = ref(false)
const runResult = ref<any>(null)

function authHeaders(): HeadersInit {
  const token = getAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

onMounted(async () => {
  try {
    const all = await fetchTasks()
    recentTasks.value = all.slice(0, 20)
  } catch { /* empty */ }
  try {
    const resp = await fetch(apiUrl('/workflows/'), { credentials: 'same-origin', headers: { ...authHeaders() } })
    if (resp.ok) {
      const data = await resp.json()
      savedWorkflows.value = (data.workflows || []).map((w: any) => ({ id: w.id, name: w.name }))
    }
  } catch { /* empty */ }
})

function goTask(task: PipelineTask) {
  router.push(`/pipeline/task/${task.id}`)
}

async function runWorkflow() {
  if (!selectedWorkflowId.value) return
  running.value = true
  runResult.value = null
  try {
    const resp = await fetch(apiUrl(`/workflows/${selectedWorkflowId.value}/run`), {
      method: 'POST',
      credentials: 'same-origin',
      headers: { ...authHeaders() },
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: t('workflow.statusFailed') }))
      throw new Error(err.detail || t('workflow.statusFailed'))
    }
    const data = await resp.json()
    runResult.value = data.run
    if (data.run?.status === 'done') {
      ElMessage.success(t('workflow.runOk'))
    } else {
      ElMessage.warning(t('workflow.runPartial'))
    }
  } catch (e: any) {
    ElMessage.error(e.message || t('workflow.runException'))
  } finally {
    running.value = false
  }
}
</script>

<style scoped>
.workflow-view {
  padding: 24px 32px;
  max-width: 1200px;
}

.workflow-view h1 {
  font-size: 22px;
  margin-bottom: 4px;
}

.view-subtitle {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-bottom: 24px;
}

.workflow-action-bar {
  margin-bottom: 16px;
  display: flex;
  align-items: center;
}

.run-result {
  margin-top: 16px;
}

.run-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.run-time {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.run-error {
  margin-bottom: 12px;
}

.run-nodes {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.run-node-card {
  padding: 12px 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color);
}

.node-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.node-id {
  font-weight: 600;
  font-size: 13px;
}

.node-output {
  font-size: 12px;
  color: var(--el-text-color-regular);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
}

.node-error {
  font-size: 12px;
  color: var(--el-color-danger);
}
</style>
