<template>
  <div class="task-detail" v-if="task">
    <header class="detail-header">
      <div class="header-breadcrumb">
        <router-link to="/pipeline" class="back-link">
          <el-icon><ArrowLeft /></el-icon>
          流水线
        </router-link>
        <span class="separator">/</span>
        <span class="task-id">{{ task.id.slice(0, 8) }}</span>
      </div>
      <div class="header-main">
        <h1>{{ task.title }}</h1>
        <div class="header-tags">
          <el-tag :type="statusTagType" size="default">{{ statusLabel }}</el-tag>
          <el-tag :type="sourceTagType(task.source)" size="small">{{ task.source }}</el-tag>
        </div>
      </div>
      <p v-if="task.description" class="task-description">{{ task.description }}</p>
    </header>

    <section class="stage-progress">
      <h2 class="section-title">阶段进度</h2>
      <div class="stage-timeline">
        <div
          v-for="(stage, idx) in task.stages"
          :key="stage.id"
          class="timeline-item"
          :class="[
            `status-${stage.status}`,
            { current: stage.id === task.currentStageId },
            { processing: processingStage === stage.id },
          ]"
        >
          <div class="timeline-dot">
            <el-icon v-if="processingStage === stage.id" :size="14" class="spin-icon"><Loading /></el-icon>
            <el-icon v-else-if="stage.status === 'done'" :size="14"><Check /></el-icon>
            <el-icon v-else-if="stage.status === 'active'" :size="14"><Loading /></el-icon>
            <span v-else class="dot-number">{{ idx + 1 }}</span>
          </div>
          <div class="timeline-connector" v-if="idx < task.stages.length - 1"></div>
          <div class="timeline-content">
            <div class="stage-label-row">
              <span class="stage-label">{{ stage.label }}</span>
              <el-tag v-if="processingStage === stage.id" size="small" type="warning" class="processing-tag">
                AI 处理中...
              </el-tag>
            </div>
            <div class="stage-role">{{ stage.ownerRole }}</div>
            <div v-if="stage.startedAt" class="stage-time">
              开始: {{ formatDate(stage.startedAt) }}
            </div>
            <div v-if="stage.completedAt" class="stage-time">
              完成: {{ formatDate(stage.completedAt) }}
              <span class="duration" v-if="stage.startedAt">
                ({{ formatDuration(stage.completedAt - stage.startedAt) }})
              </span>
            </div>
            <div v-if="stage.output" class="stage-output-preview">
              <div class="output-header" @click="toggleOutput(stage.id)">
                <el-icon><Document /></el-icon>
                <span>查看产出</span>
                <el-icon class="toggle-icon" :class="{ expanded: expandedOutputs.has(stage.id) }">
                  <ArrowDown />
                </el-icon>
              </div>
              <div v-if="expandedOutputs.has(stage.id)" class="output-body">
                <div class="output-content-md" v-html="renderMarkdown(stage.output)"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 子任务追踪面板 (deer-flow 风格) -->
    <section class="subtask-tracking" v-if="subtasks.length">
      <h2 class="section-title">
        <span class="icon-brain">🧠</span>
        Lead Agent 子任务
        <el-tag size="small" type="info" style="margin-left: 8px">
          {{ completedSubtasks }}/{{ subtasks.length }}
        </el-tag>
      </h2>
      <div class="subtask-list">
        <SubtaskCard
          v-for="st in subtasks"
          :key="st.id"
          :subtask="st"
        />
      </div>
    </section>

    <section class="task-actions" v-if="task.status === 'active'">
      <h2 class="section-title">操作</h2>
      <div class="action-buttons">
        <el-button
          type="success"
          size="large"
          @click="handleSmartRun"
          :loading="smartRunning"
          :disabled="task.currentStageId === 'done'"
        >
          <span style="margin-right:4px">🧠</span>
          Lead Agent 智能执行
        </el-button>
        <el-button
          @click="handleAutoRun"
          :loading="autoRunning"
          :disabled="task.currentStageId === 'done'"
        >
          <el-icon><VideoPlay /></el-icon>
          经典全自动执行
        </el-button>
        <el-button
          type="primary"
          @click="handleRunCurrentStage"
          :loading="stageRunning"
          :disabled="task.currentStageId === 'done'"
        >
          <el-icon><CaretRight /></el-icon>
          AI 执行当前阶段
        </el-button>
        <el-button
          @click="handleAdvance"
          :disabled="task.currentStageId === 'done'"
        >
          <el-icon><Right /></el-icon>
          手动跳过
        </el-button>
        <el-button
          type="warning"
          @click="showRejectDialog = true"
          :disabled="task.currentStageId === 'planning'"
        >
          <el-icon><Back /></el-icon>
          打回
        </el-button>
        <el-button
          v-if="task.currentStageId === 'development'"
          @click="handleResume"
          :loading="resuming"
        >
          <el-icon><RefreshRight /></el-icon>
          确认构建完成 & 继续
        </el-button>
        <el-button
          @click="goToAgent"
        >
          <el-icon><ChatDotSquare /></el-icon>
          进入 Agent 对话
        </el-button>
      </div>
    </section>

    <section class="live-log" v-if="stageLogs.length">
      <h2 class="section-title">
        实时日志
        <el-tag size="small" type="info" style="margin-left: 8px">{{ stageLogs.length }}</el-tag>
      </h2>
      <div class="log-container" ref="logContainer">
        <div
          v-for="(log, i) in stageLogs"
          :key="i"
          class="log-entry"
          :class="log.event"
        >
          <span class="log-time">{{ formatLogTime(log.timestamp) }}</span>
          <span class="log-event">{{ formatEventName(log.event) }}</span>
          <span class="log-detail" v-if="log.detail">{{ log.detail }}</span>
        </div>
      </div>
    </section>

    <section class="task-artifacts" v-if="task.artifacts?.length">
      <h2 class="section-title">
        交付产物
        <el-tag size="small" type="info" style="margin-left: 8px">{{ task.artifacts.length }}</el-tag>
      </h2>
      <div class="artifact-list">
        <div
          v-for="artifact in task.artifacts"
          :key="artifact.id"
          class="artifact-card"
        >
          <div class="artifact-header">
            <div class="artifact-name">
              <el-tag size="small" :type="artifactTagType(artifact.type)">{{ artifact.type }}</el-tag>
              {{ artifact.name }}
            </div>
            <el-tag size="small" type="info">{{ artifact.stageId }}</el-tag>
          </div>
          <div class="artifact-body">
            <div
              v-if="expandedArtifacts.has(artifact.id)"
              class="artifact-content-full"
              v-html="renderMarkdown(artifact.content)"
            ></div>
            <pre v-else class="artifact-content-preview">{{ artifact.content.slice(0, 300) }}{{ artifact.content.length > 300 ? '...' : '' }}</pre>
          </div>
          <el-button
            text
            size="small"
            @click="toggleArtifact(artifact.id)"
            class="artifact-toggle"
          >
            {{ expandedArtifacts.has(artifact.id) ? '收起' : '展开全部' }}
          </el-button>
        </div>
      </div>
    </section>

    <el-dialog v-model="showRejectDialog" title="打回任务" width="400px">
      <el-form label-position="top">
        <el-form-item label="打回到哪个阶段">
          <el-select v-model="rejectTarget" style="width: 100%">
            <el-option
              v-for="stage in previousStages"
              :key="stage.id"
              :label="stage.label"
              :value="stage.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="打回原因">
          <el-input v-model="rejectReason" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRejectDialog = false">取消</el-button>
        <el-button type="warning" @click="handleReject">确认打回</el-button>
      </template>
    </el-dialog>
  </div>

  <div v-else-if="loadError" class="task-loading">
    <p class="error-text">{{ loadError }}</p>
    <el-button type="primary" @click="loadTask" style="margin-top: 12px">重试</el-button>
    <el-button @click="router.push('/pipeline')" style="margin-top: 12px">返回列表</el-button>
  </div>

  <div v-else class="task-loading">
    <el-icon class="loading-icon" :size="32"><Loading /></el-icon>
    <p>加载中...</p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowDown, ArrowLeft, Back, CaretRight, Check, ChatDotSquare,
  Document, Loading, RefreshRight, Right, VideoPlay,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { usePipelineStore } from '@/stores/pipeline'
import {
  fetchTask, runStage as apiRunStage, autoRunPipeline, resumeAfterBuild,
  smartRunPipeline, subscribePipelineEvents,
} from '@/services/pipelineApi'
import type { PipelineTask, PipelineEvent, SubtaskInfo } from '@/agents/types'
import { renderMarkdown } from '@/services/markdown'
import SubtaskCard from '@/components/SubtaskCard.vue'

const route = useRoute()
const router = useRouter()
const pipelineStore = usePipelineStore()

const task = ref<PipelineTask | null>(null)
const loadError = ref('')
const autoRunning = ref(false)
const smartRunning = ref(false)
const stageRunning = ref(false)
const resuming = ref(false)
const subtasks = ref<SubtaskInfo[]>([])
const processingStage = ref<string | null>(null)
const showRejectDialog = ref(false)
const rejectTarget = ref('')
const rejectReason = ref('')
const expandedOutputs = reactive(new Set<string>())
const expandedArtifacts = reactive(new Set<string>())
const logContainer = ref<HTMLElement | null>(null)

interface LogEntry {
  event: string
  timestamp: number
  detail?: string
}
const stageLogs = ref<LogEntry[]>([])

const STAGE_IDS = ['planning', 'architecture', 'development', 'testing', 'reviewing', 'deployment', 'done']

const stageToAgent: Record<string, string> = {
  planning: 'ceo-agent',
  architecture: 'architect-agent',
  development: 'developer-agent',
  testing: 'qa-agent',
  reviewing: 'ceo-agent',
  deployment: 'devops-agent',
}

const completedSubtasks = computed(() =>
  subtasks.value.filter(s => s.status === 'completed').length
)

const statusLabel = computed(() => {
  const labels: Record<string, string> = {
    active: '进行中',
    paused: '已暂停',
    done: '已完成',
    cancelled: '已取消',
  }
  return labels[task.value?.status || ''] || task.value?.status
})

const statusTagType = computed(() => {
  const map: Record<string, string> = {
    active: 'primary',
    paused: 'warning',
    done: 'success',
    cancelled: 'danger',
  }
  return (map[task.value?.status || ''] || 'info') as '' | 'success' | 'warning' | 'info' | 'danger'
})

function sourceTagType(source: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' {
  const map: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
    feishu: 'warning', qq: 'success', web: 'info', api: 'primary', 'api-e2e': 'danger',
  }
  return map[source] ?? 'info'
}

function artifactTagType(type: string) {
  const map: Record<string, string> = { document: 'primary', code: 'success', test: 'warning' }
  return (map[type] || 'info') as '' | 'success' | 'warning' | 'info' | 'danger'
}

const previousStages = computed(() => {
  if (!task.value) return []
  const currentIdx = STAGE_IDS.indexOf(task.value.currentStageId)
  if (currentIdx <= 0) return []
  return task.value.stages
    .filter(s => {
      const sIdx = STAGE_IDS.indexOf(s.id)
      return sIdx >= 0 && sIdx < currentIdx
    })
})

function formatDate(ts: number) {
  return new Date(ts).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function formatDuration(ms: number) {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}min`
}

function formatLogTime(ts: number) {
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function formatEventName(event: string) {
  const map: Record<string, string> = {
    'stage:queued': '⏳ 排队',
    'stage:processing': '🔄 处理中',
    'stage:completed': '✅ 完成',
    'stage:error': '❌ 错误',
    'task:stage-advanced': '➡️ 推进',
    'task:created': '📝 创建',
    'task:updated': '📝 更新',
    'pipeline:auto-start': '🚀 自动启动',
    'pipeline:auto-completed': '🎉 全流程完成',
    'pipeline:auto-paused': '⏸️ 暂停',
    'pipeline:auto-error': '💥 流程错误',
    'pipeline:smart-start': '🧠 Lead Agent 启动',
    'pipeline:smart-completed': '🧠 智能流水线完成',
    'pipeline:smart-error': '🧠 智能流水线错误',
    'lead-agent:analyzing': '🔍 Lead Agent 分析中',
    'lead-agent:plan-ready': '📋 任务分解完成',
    'lead-agent:error': '❌ Lead Agent 错误',
    'subtask:start': '▶️ 子任务启动',
    'subtask:completed': '✅ 子任务完成',
    'subtask:failed': '❌ 子任务失败',
    'subtasks:batch-start': '⚡ 并行批次启动',
    'middleware:blocked': '🛡️ 中间件拦截',
    'middleware:token-usage': '📊 Token 用量',
    'executor:started': '⚡ Claude Code 启动',
    'executor:launched': '🚀 Claude Code 运行中',
    'executor:log': '📋 Claude Code 日志',
    'executor:completed': '✅ Claude Code 完成',
    'executor:error': '❌ Claude Code 错误',
    'executor:timeout': '⏰ Claude Code 超时',
    'executor:killed': '🛑 Claude Code 已终止',
  }
  return map[event] || event
}

function toggleOutput(stageId: string) {
  if (expandedOutputs.has(stageId)) expandedOutputs.delete(stageId)
  else expandedOutputs.add(stageId)
}

function toggleArtifact(id: string) {
  if (expandedArtifacts.has(id)) expandedArtifacts.delete(id)
  else expandedArtifacts.add(id)
}

function addLog(event: string, data?: Record<string, unknown>) {
  const detail = data?.error
    ? String(data.error)
    : data?.stageId
      ? `阶段: ${data.stageId}${data.label ? ` (${data.label})` : ''}`
      : data?.from && data?.to
        ? `${data.from} → ${data.to}`
        : undefined

  stageLogs.value.push({
    event,
    timestamp: Date.now(),
    detail: detail as string | undefined,
  })

  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
}

let unsubSSE: (() => void) | null = null

function setupSSE() {
  unsubSSE = subscribePipelineEvents((evt: PipelineEvent) => {
    const taskId = route.params.id as string
    const data = evt.data as Record<string, unknown> | undefined

    const eventTaskId = data?.taskId || (data?.task as Record<string, unknown>)?.id
    if (eventTaskId && eventTaskId !== taskId) return

    addLog(evt.event, data)

    if (evt.event === 'stage:processing') {
      processingStage.value = (data?.stageId as string) || null
    }

    if (evt.event === 'stage:completed') {
      processingStage.value = null
      stageRunning.value = false
      loadTask()
    }
    if (evt.event === 'stage:error') {
      processingStage.value = null
      stageRunning.value = false
    }

    // Lead Agent 子任务追踪 (deer-flow 风格)
    if (evt.event === 'subtask:start') {
      subtasks.value.push({
        id: (data?.subtaskId as string) || '',
        title: (data?.title as string) || '',
        role: (data?.role as string) || '',
        status: 'running',
        startTime: Date.now(),
      })
    }
    if (evt.event === 'subtask:completed') {
      const st = subtasks.value.find(s => s.id === data?.subtaskId)
      if (st) {
        st.status = 'completed'
        st.endTime = Date.now()
      }
    }
    if (evt.event === 'subtask:failed') {
      const st = subtasks.value.find(s => s.id === data?.subtaskId)
      if (st) {
        st.status = 'failed'
        st.error = (data?.error as string) || '执行失败'
        st.endTime = Date.now()
      }
    }
    if (evt.event === 'lead-agent:plan-ready') {
      const plan = data?.plan as Record<string, unknown>
      if (plan?.subtaskCount) {
        addLog('lead-agent:plan-ready', {
          analysis: `分解为 ${plan.subtaskCount} 个子任务，策略: ${plan.strategy}，复杂度: ${plan.complexity}`,
        })
      }
    }

    if (
      evt.event === 'task:stage-advanced' ||
      evt.event === 'task:updated' ||
      evt.event === 'stage:completed' ||
      evt.event === 'pipeline:auto-completed' ||
      evt.event === 'pipeline:smart-completed'
    ) {
      const updatedTask = (data?.task as PipelineTask) || null
      if (updatedTask) {
        task.value = updatedTask
      } else {
        loadTask()
      }
    }

    if (evt.event === 'pipeline:auto-completed') {
      autoRunning.value = false
      stageRunning.value = false
      ElMessage.success('全自动流水线已完成！')
    }

    if (evt.event === 'pipeline:smart-completed') {
      smartRunning.value = false
      autoRunning.value = false
      stageRunning.value = false
      const completed = (data?.completedSubtasks as number) || 0
      const total = (data?.subtaskCount as number) || 0
      ElMessage.success(`Lead Agent 智能执行完成！${completed}/${total} 子任务成功`)
    }

    if (evt.event === 'pipeline:auto-paused') {
      autoRunning.value = false
      ElMessage.info('流水线在 building 阶段暂停，请确认 Claude Code 执行完成后继续。')
    }

    if (evt.event === 'pipeline:auto-error' || evt.event === 'stage:error' || evt.event === 'pipeline:smart-error') {
      autoRunning.value = false
      smartRunning.value = false
      stageRunning.value = false
      ElMessage.error(`执行失败: ${data?.error || '未知错误'}`)
    }
  })
}

async function handleSmartRun() {
  if (!task.value) return
  smartRunning.value = true
  stageLogs.value = []
  subtasks.value = []
  try {
    await smartRunPipeline(task.value.id)
    addLog('pipeline:smart-start', { taskId: task.value.id })
    ElMessage.success('Lead Agent 已启动后台执行，可自由切换页面')
  } catch (e: unknown) {
    smartRunning.value = false
    ElMessage.error(`智能执行启动失败: ${e instanceof Error ? e.message : String(e)}`)
  }
}

async function handleAutoRun() {
  if (!task.value) return
  autoRunning.value = true
  stageLogs.value = []
  try {
    await autoRunPipeline(task.value.id)
    addLog('pipeline:auto-start', { taskId: task.value.id })
    ElMessage.success('全自动流水线已启动后台执行，可自由切换页面')
  } catch (e: unknown) {
    autoRunning.value = false
    ElMessage.error(`启动失败: ${e instanceof Error ? e.message : String(e)}`)
  }
}

async function handleRunCurrentStage() {
  if (!task.value) return
  stageRunning.value = true
  try {
    await apiRunStage(task.value.id)
    addLog('stage:queued', { stageId: task.value.currentStageId })
    ElMessage.success('AI 已开始执行当前阶段，可自由切换页面')
  } catch (e: unknown) {
    stageRunning.value = false
    ElMessage.error(`执行失败: ${e instanceof Error ? e.message : String(e)}`)
  }
}

async function handleAdvance() {
  if (!task.value) return
  try {
    task.value = await pipelineStore.advanceTask(task.value.id)
    addLog('task:stage-advanced', { from: '(手动)', to: task.value.currentStageId })
  } catch (e: unknown) {
    ElMessage.error(`推进失败: ${e instanceof Error ? e.message : String(e)}`)
  }
}

async function handleReject() {
  if (!task.value || !rejectTarget.value) return
  try {
    task.value = await pipelineStore.rejectTask(
      task.value.id,
      rejectTarget.value,
      rejectReason.value,
    )
    showRejectDialog.value = false
    rejectTarget.value = ''
    rejectReason.value = ''
    ElMessage.success('任务已打回')
  } catch (e: unknown) {
    ElMessage.error(`打回失败: ${e instanceof Error ? e.message : String(e)}`)
  }
}

async function handleResume() {
  if (!task.value) return
  resuming.value = true
  try {
    await resumeAfterBuild(task.value.id)
    addLog('pipeline:auto-start', { taskId: task.value.id })
  } catch (e: unknown) {
    ElMessage.error(`恢复失败: ${e instanceof Error ? e.message : String(e)}`)
  } finally {
    resuming.value = false
  }
}

function goToAgent() {
  if (!task.value) return
  const agentId = stageToAgent[task.value.currentStageId] || 'wayne-orchestrator'
  router.push({
    path: `/agent/${agentId}`,
    query: { pipelineTask: task.value.id },
  })
}

async function loadTask() {
  const id = route.params.id as string
  if (!id) return
  loadError.value = ''
  try {
    task.value = await fetchTask(id)
    // Detect if a background run is in progress (stage is active but has no output yet)
    if (task.value && task.value.status === 'active') {
      const activeStage = task.value.stages.find(s => s.status === 'active')
      if (activeStage && !activeStage.output) {
        processingStage.value = activeStage.id
      }
    }
    if (task.value?.status === 'done' || task.value?.currentStageId === 'done') {
      autoRunning.value = false
      smartRunning.value = false
      stageRunning.value = false
    }
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '加载任务失败'
    console.error('加载任务失败:', e)
  }
}

onMounted(() => {
  loadTask()
  setupSSE()
})

onUnmounted(() => {
  unsubSSE?.()
})

watch(() => route.params.id, () => {
  loadTask()
  stageLogs.value = []
  processingStage.value = null
})
</script>

<style scoped>
.task-detail {
  padding: 32px;
  max-width: 960px;
  margin: 0 auto;
}

.detail-header { margin-bottom: 32px; }

.header-breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 12px;
}

.back-link {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--accent);
  text-decoration: none;
}
.back-link:hover { text-decoration: underline; }

.separator { color: var(--border-color); }
.task-id { font-family: monospace; }

.header-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.header-main h1 {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
}

.header-tags { display: flex; gap: 8px; }

.task-description {
  color: var(--text-secondary);
  margin-top: 8px;
  line-height: 1.6;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 16px;
  display: flex;
  align-items: center;
}

.stage-progress { margin-bottom: 32px; }

.stage-timeline {
  display: flex;
  flex-direction: column;
  position: relative;
}

.timeline-item {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 12px 0;
  position: relative;
}

.timeline-dot {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  background: var(--bg-tertiary);
  border: 2px solid var(--border-color);
  color: var(--text-muted);
  z-index: 1;
}

.timeline-item.status-done .timeline-dot {
  background: #22c55e;
  border-color: #22c55e;
  color: #fff;
}

.timeline-item.status-active .timeline-dot {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
  animation: pulse 2s infinite;
}

.timeline-item.processing .timeline-dot {
  background: #f59e0b;
  border-color: #f59e0b;
  color: #fff;
  animation: none;
  box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.3);
}

.timeline-item.current .timeline-dot {
  box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.2);
}

.timeline-connector {
  position: absolute;
  left: 13px;
  top: 40px;
  bottom: -12px;
  width: 2px;
  background: var(--border-color);
}

.timeline-item.status-done .timeline-connector {
  background: #22c55e;
}

.timeline-content { flex: 1; }

.stage-label-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.stage-label {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 14px;
}

.processing-tag {
  animation: blink 1.5s infinite;
}

.stage-role {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

.stage-time {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

.duration {
  color: var(--accent);
  font-weight: 500;
}

.stage-output-preview {
  margin-top: 8px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
}

.output-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12px;
  color: var(--accent);
  background: var(--bg-secondary);
  transition: background 0.2s;
}
.output-header:hover {
  background: var(--bg-tertiary);
}

.toggle-icon {
  margin-left: auto;
  transition: transform 0.2s;
}
.toggle-icon.expanded {
  transform: rotate(180deg);
}

.output-body {
  padding: 12px 16px;
  background: var(--bg-tertiary);
  max-height: 400px;
  overflow-y: auto;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.output-content-md :deep(h2) { font-size: 16px; font-weight: 700; margin: 12px 0 8px; color: var(--text-primary); }
.output-content-md :deep(h3) { font-size: 14px; font-weight: 600; margin: 10px 0 6px; color: var(--text-primary); }
.output-content-md :deep(h4) { font-size: 13px; font-weight: 600; margin: 8px 0 4px; color: var(--text-primary); }
.output-content-md :deep(strong) { color: var(--text-primary); }
.output-content-md :deep(code) {
  background: rgba(99, 102, 241, 0.15);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12px;
}
.output-content-md :deep(li) {
  margin-left: 16px;
  margin-bottom: 2px;
  list-style: disc;
}

.task-actions { margin-bottom: 32px; }

.action-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.live-log { margin-bottom: 32px; }

.log-container {
  background: #0d1117;
  border-radius: 10px;
  padding: 12px;
  max-height: 300px;
  overflow-y: auto;
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
}

.log-entry {
  display: flex;
  gap: 10px;
  padding: 3px 0;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}

.log-time {
  color: #6b7280;
  flex-shrink: 0;
  width: 70px;
}

.log-event {
  color: #a5b4fc;
  flex-shrink: 0;
  min-width: 100px;
}

.log-detail {
  color: #9ca3af;
  word-break: break-all;
}

.log-entry.stage\:error .log-event,
.log-entry.pipeline\:auto-error .log-event {
  color: #ef4444;
}

.log-entry.stage\:completed .log-event,
.log-entry.pipeline\:auto-completed .log-event {
  color: #22c55e;
}

.subtask-tracking {
  margin-bottom: 24px;
  padding: 16px;
  background: linear-gradient(135deg, #f8f9ff 0%, #f0f7ff 100%);
  border-radius: 12px;
  border: 1px solid #d9ecff;
}
.subtask-tracking .section-title {
  display: flex;
  align-items: center;
  gap: 4px;
}
.subtask-tracking .icon-brain { font-size: 20px; }
.subtask-list { margin-top: 12px; }

.task-artifacts { margin-bottom: 32px; }

.artifact-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.artifact-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  overflow: hidden;
}

.artifact-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-color);
}

.artifact-name {
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.artifact-body {
  padding: 12px 14px;
}

.artifact-content-preview {
  background: var(--bg-tertiary);
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  color: var(--text-secondary);
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 120px;
  overflow-y: auto;
}

.artifact-content-full {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.7;
  max-height: 500px;
  overflow-y: auto;
}

.artifact-content-full :deep(h2) { font-size: 16px; font-weight: 700; margin: 12px 0 8px; color: var(--text-primary); }
.artifact-content-full :deep(h3) { font-size: 14px; font-weight: 600; margin: 10px 0 6px; color: var(--text-primary); }
.artifact-content-full :deep(h4) { font-size: 13px; font-weight: 600; margin: 8px 0 4px; color: var(--text-primary); }
.artifact-content-full :deep(strong) { color: var(--text-primary); }
.artifact-content-full :deep(code) {
  background: rgba(99, 102, 241, 0.15);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12px;
}
.artifact-content-full :deep(li) {
  margin-left: 16px;
  margin-bottom: 2px;
  list-style: disc;
}

.artifact-toggle {
  width: 100%;
  border-top: 1px solid var(--border-color);
  border-radius: 0;
}

.task-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 60vh;
  color: var(--text-muted);
}

.loading-icon { animation: spin 1s linear infinite; }
.spin-icon { animation: spin 1s linear infinite; }

@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.7; } }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
</style>
