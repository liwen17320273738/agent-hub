<template>
  <div class="workflow-view">
    <h1>工作流</h1>
    <p class="view-subtitle">任务流水线与工作流编排</p>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="流水线" name="pipeline">
        <div class="workflow-action-bar">
          <el-button type="primary" @click="$router.push('/pipeline')">
            打开流水线面板
          </el-button>
        </div>
        <TaskTable :tasks="recentTasks" empty-text="暂无任务" @click-task="goTask" />
      </el-tab-pane>

      <el-tab-pane label="工作流编排" name="builder">
        <div class="workflow-action-bar">
          <el-button type="primary" @click="$router.push('/workflow-builder')">
            打开 Workflow Builder
          </el-button>
        </div>
        <el-empty description="在 Builder 中设计工作流，保存后可在「运行」tab 中执行" />
      </el-tab-pane>

      <el-tab-pane label="运行" name="run">
        <div class="workflow-action-bar">
          <el-select v-model="selectedWorkflowId" placeholder="选择已保存的工作流" style="width: 300px; margin-right: 12px">
            <el-option
              v-for="wf in savedWorkflows"
              :key="wf.id"
              :label="wf.name"
              :value="wf.id"
            />
          </el-select>
          <el-button type="primary" :loading="running" :disabled="!selectedWorkflowId" @click="runWorkflow">
            执行工作流
          </el-button>
        </div>

        <div v-if="runResult" class="run-result">
          <div class="run-header">
            <el-tag :type="runResult.status === 'done' ? 'success' : runResult.status === 'failed' ? 'danger' : 'primary'" size="default">
              {{ runResult.status === 'done' ? '执行成功' : runResult.status === 'failed' ? '执行失败' : '执行中' }}
            </el-tag>
            <span class="run-time">耗时 {{ (runResult.elapsed_ms / 1000).toFixed(1) }}s</span>
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

        <el-empty v-else-if="!running" description="选择一个工作流并点击执行" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { fetchTasks } from '@/services/pipelineApi'
import { apiUrl } from '@/services/enterpriseApi'
import { getAuthToken } from '@/services/api'
import type { PipelineTask } from '@/agents/types'
import TaskTable from '@/components/inbox/TaskTable.vue'

const router = useRouter()
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
    const resp = await fetch(apiUrl('/workflows'), { credentials: 'same-origin', headers: { ...authHeaders() } })
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
      const err = await resp.json().catch(() => ({ detail: '执行失败' }))
      throw new Error(err.detail || '执行失败')
    }
    const data = await resp.json()
    runResult.value = data.run
    if (data.run?.status === 'done') {
      ElMessage.success('工作流执行成功')
    } else {
      ElMessage.warning('工作流执行完成（部分失败）')
    }
  } catch (e: any) {
    ElMessage.error(e.message || '执行异常')
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
