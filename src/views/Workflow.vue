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
                <el-tag :type="nodeRes.status === 'done' ? 'success' : nodeRes.status === 'running' ? 'warning' : 'danger'" size="small">
                  {{ nodeRes.status === 'done' ? t('workflow.statusDone') : nodeRes.status === 'running' ? t('workflow.statusRunning') : t('workflow.statusFailed') }}
                </el-tag>
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
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { fetchTasks } from '@/services/pipelineApi'
import { subscribePipelineEvents } from '@/services/pipelineApi'
import { apiUrl } from '@/services/enterpriseApi'
import { getAuthToken } from '@/services/api'
import type { PipelineTask, PipelineEvent } from '@/agents/types'
import TaskTable from '@/components/inbox/TaskTable.vue'

const router = useRouter()
const { t } = useI18n()
const activeTab = ref('pipeline')
const recentTasks = ref<PipelineTask[]>([])

interface SavedWorkflow { id: string; name: string }
interface WorkflowNodeResult {
  status: string
  output?: string
  error?: string
}
interface WorkflowRunState {
  run_id: string
  workflow_name: string
  status: string
  error?: string
  elapsed_ms: number
  node_results: Record<string, WorkflowNodeResult>
}

const savedWorkflows = ref<SavedWorkflow[]>([])
const selectedWorkflowId = ref('')
const running = ref(false)
const runResult = ref<WorkflowRunState | null>(null)
let sseUnsubscribe: (() => void) | null = null

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

onUnmounted(() => {
  sseUnsubscribe?.()
})

function goTask(task: PipelineTask) {
  router.push(`/pipeline/task/${task.id}`)
}

async function runWorkflow() {
  if (!selectedWorkflowId.value) return
  running.value = true
  runResult.value = null
  sseUnsubscribe?.()

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
    const runId: string = data.run?.run_id || ''

    // 初始化本地状态
    runResult.value = {
      run_id: runId,
      workflow_name: data.run?.workflow_name || '',
      status: 'running',
      elapsed_ms: 0,
      node_results: {},
    }

    // 订阅 SSE 实时更新工作流执行进度
    sseUnsubscribe = subscribePipelineEvents((event: PipelineEvent) => {
      const evt = event.event
      const d = event.data as any
      // 只处理当前 run 的事件
      if (!d || d.run_id !== runId) return

      if (evt === 'workflow:node-start') {
        if (runResult.value) {
          runResult.value.node_results[d.node_id] = { status: 'running' }
          // 触发响应式更新
          runResult.value = { ...runResult.value }
        }
      } else if (evt === 'workflow:node-done') {
        if (runResult.value) {
          runResult.value.node_results[d.node_id] = { status: 'done' }
          runResult.value = { ...runResult.value }
        }
      } else if (evt === 'workflow:node-error') {
        if (runResult.value) {
          runResult.value.node_results[d.node_id] = {
            status: 'failed',
            error: d.error || 'Unknown error',
          }
          runResult.value = { ...runResult.value }
        }
      } else if (evt === 'workflow:done') {
        if (runResult.value) {
          runResult.value.status = d.status || 'done'
          runResult.value.elapsed_ms = d.elapsed_ms || 0
          runResult.value = { ...runResult.value }
        }
        running.value = false
        sseUnsubscribe?.()
        sseUnsubscribe = null
        if (d.status === 'done') {
          ElMessage.success(t('workflow.runOk'))
        } else {
          ElMessage.warning(t('workflow.runPartial'))
        }
      }
    })

    // SSE 超时兜底：60 秒后自动断开
    setTimeout(() => {
      if (running.value) {
        running.value = false
        sseUnsubscribe?.()
        sseUnsubscribe = null
        if (runResult.value && runResult.value.status === 'running') {
          runResult.value.status = 'timeout'
          runResult.value.error = 'Workflow execution timed out (60s)'
          runResult.value = { ...runResult.value }
        }
      }
    }, 60_000)
  } catch (e: any) {
    ElMessage.error(e.message || t('workflow.runException'))
    running.value = false
  }
}
</script>

<style scoped>
.workflow-view {
  padding: 28px 36px;
  max-width: 1200px;
  width: 100%;
}

.workflow-view h1 {
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -0.4px;
  margin-bottom: 4px;
  background: linear-gradient(135deg, var(--text-primary), var(--text-secondary));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.view-subtitle {
  color: var(--text-muted);
  font-size: 14px;
  margin-bottom: 24px;
}

.workflow-action-bar {
  margin-bottom: 18px;
  display: flex;
  align-items: center;
}

.run-result {
  margin-top: 18px;
}

.run-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 14px;
}

.run-time {
  font-size: 13px;
  color: var(--text-muted);
  font-weight: 500;
}

.run-error {
  margin-bottom: 14px;
}

.run-nodes {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.run-node-card {
  padding: 14px 18px;
  border: 1px solid var(--card-border);
  border-radius: var(--card-radius);
  background: var(--card-bg);
  box-shadow: var(--card-shadow);
}

.node-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.node-id {
  font-weight: 700;
  font-size: 13px;
  color: var(--text-primary);
}

.node-output {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
}

.node-error {
  font-size: 12px;
  color: var(--red);
  font-weight: 500;
}
</style>
