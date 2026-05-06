<template>
  <div class="execution-log-tab">
    <!-- Job selector -->
    <div v-if="jobs.length > 1" class="job-selector">
      <el-select v-model="activeJobId" size="small" @change="loadLogs" class="job-select">
        <el-option
          v-for="j in jobs"
          :key="j.id"
          :value="j.id"
          :label="`${j.status} · ${formatJobTime(j.startedAt)} · ${formatDuration(j)}`"
        />
      </el-select>
    </div>

    <!-- Job summary -->
    <div v-if="activeJob" class="job-summary">
      <div class="job-summary-item">
        <span class="summary-label">状态</span>
        <el-tag :type="jobStatusTag" size="small" effect="dark">
          <span class="status-dot" :class="activeJob.status" />
          {{ jobStatusLabel }}
        </el-tag>
      </div>
      <div class="job-summary-item">
        <span class="summary-label">耗时</span>
        <span class="summary-value">{{ formatDuration(activeJob) }}</span>
      </div>
      <div class="job-summary-item">
        <span class="summary-label">退出码</span>
        <span class="summary-value">{{ activeJob.exitCode ?? '—' }}</span>
      </div>
      <div class="job-summary-item">
        <span class="summary-label">日志条数</span>
        <span class="summary-value">{{ logs.length }}</span>
      </div>
      <el-button v-if="activeJob.status === 'running'" size="small" type="danger" plain @click="handleKill">
        <el-icon><CloseBold /></el-icon> 终止
      </el-button>
    </div>

    <!-- Filter toolbar -->
    <div class="log-toolbar" v-if="logs.length">
      <el-checkbox-group v-model="visibleTypes" size="small">
        <el-checkbox-button value="stdout">stdout</el-checkbox-button>
        <el-checkbox-button value="stderr">stderr</el-checkbox-button>
        <el-checkbox-button value="error">error</el-checkbox-button>
      </el-checkbox-group>
      <el-input
        v-model="searchQuery"
        size="small"
        placeholder="搜索日志..."
        clearable
        class="log-search"
        :prefix-icon="Search"
      />
      <el-button size="small" text @click="autoScroll = !autoScroll">
        <el-icon><Bottom /></el-icon>
        {{ autoScroll ? '自动滚动' : '手动' }}
      </el-button>
    </div>

    <!-- Empty state -->
    <div v-if="!hasJobs" class="log-empty">
      <el-icon :size="48"><Monitor /></el-icon>
      <p>暂无 Claude Code 执行记录</p>
      <p class="log-empty-hint">当 pipeline 进入「开发实现」阶段时，Claude Code 的执行日志会显示在这里</p>
    </div>

    <!-- No logs yet for running job -->
    <div v-else-if="!logs.length && activeJob?.status === 'running'" class="log-waiting">
      <el-icon class="spin-icon" :size="32"><Loading /></el-icon>
      <p>等待 Claude Code 输出...</p>
    </div>

    <!-- Log output -->
    <div v-else class="log-output" ref="logContainer">
      <div
        v-for="(log, i) in filteredLogs"
        :key="i"
        class="log-line"
        :class="`log-type-${log.type}`"
      >
        <span class="log-line-time">{{ formatLogTime(log.timestamp) }}</span>
        <span class="log-line-type">{{ log.type === 'stdout' ? 'OUT' : log.type === 'stderr' ? 'ERR' : 'ERR' }}</span>
        <span class="log-line-text">{{ log.text }}</span>
      </div>
      <div v-if="!filteredLogs.length && searchQuery" class="log-no-match">
        无匹配 "{{ searchQuery }}" 的日志行
      </div>
    </div>

    <!-- Load more -->
    <div v-if="!allLoaded" class="log-load-more">
      <el-button text @click="loadOlder">加载更早的日志</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Monitor, Loading, CloseBold, Bottom } from '@element-plus/icons-vue'
import { fetchJobLogs, fetchJobsByTask, type ExecutorJobLog } from '@/services/pipelineApi'
import { subscribePipelineEvents } from '@/services/pipelineApi'
import type { PipelineEvent } from '@/agents/types'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps<{
  taskId: string
}>()

// ── State ──
const jobs = ref<any[]>([])
const activeJobId = ref<string>('')
const logs = ref<ExecutorJobLog[]>([])
const visibleTypes = ref<(string | number | boolean)[]>(['stdout', 'stderr', 'error'])
const searchQuery = ref('')
const autoScroll = ref(true)
const logContainer = ref<HTMLElement | null>(null)
const allLoaded = ref(true)

const hasJobs = computed(() => jobs.value.length > 0)
const activeJob = computed(() => jobs.value.find(j => j.id === activeJobId.value) || null)

const filteredLogs = computed(() => {
  let result = logs.value
  if (visibleTypes.value.length) {
    result = result.filter(l => visibleTypes.value.includes(l.type))
  }
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    result = result.filter(l => l.text.toLowerCase().includes(q))
  }
  return result
})

// ── Status helpers ──
const jobStatusTag = computed(() => {
  const s = activeJob.value?.status
  if (s === 'done') return 'success'
  if (s === 'running') return 'warning'
  if (s === 'error' || s === 'failed' || s === 'timeout') return 'danger'
  if (s === 'killed') return 'info'
  return 'info'
})

const jobStatusLabel = computed(() => {
  const s = activeJob.value?.status
  const map: Record<string, string> = {
    running: '运行中',
    done: '完成',
    failed: '失败',
    error: '错误',
    timeout: '超时',
    killed: '已终止',
  }
  return map[s] || s || '—'
})

function formatLogTime(ts: number) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleTimeString('zh-CN', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function formatJobTime(ts?: number) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleString('zh-CN')
}

function formatDuration(j: any) {
  if (!j?.startedAt) return '—'
  const end = j.completedAt || Date.now() / 1000
  const ms = (end - j.startedAt) * 1000
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`
}

// ── Data loading ──
async function loadJobs() {
  try {
    const res = await fetchJobsByTask(props.taskId)
    jobs.value = res.jobs || []
    if (jobs.value.length) {
      activeJobId.value = activeJobId.value || jobs.value[0].id
    }
  } catch {
    // task may have no executor jobs yet
  }
}

async function loadLogs() {
  if (!activeJobId.value) return
  try {
    const res = await fetchJobLogs(activeJobId.value)
    if (res.ok) {
      logs.value = res.logs || []
    }
  } catch {
    logs.value = []
  }
}

function loadOlder() {
  // Placeholder for pagination if needed
  allLoaded.value = true
}

async function handleKill() {
  try {
    const res = await fetch(`/api/executor/jobs/${activeJobId.value}/kill`, { method: 'POST' })
    if (res.ok) {
      ElMessage.success('已发送终止信号')
      await loadJobs()
    }
  } catch {
    ElMessage.error('终止失败')
  }
}

// ── SSE bridge for live log streaming ──
let unsubSSE: (() => void) | null = null

function onSSE(evt: PipelineEvent) {
  const data = (evt.data || {}) as Record<string, unknown>
  const eventTaskId = (data.taskId as string) || ''
  if (eventTaskId && eventTaskId !== props.taskId) return

  const jobId = (data.jobId as string) || ''

  // If this event is for a currently tracked job, append live log
  if (evt.event === 'executor:log' && jobId === activeJobId.value) {
    const logEntry: ExecutorJobLog = {
      type: (data.type as 'stdout' | 'stderr' | 'error') || 'stdout',
      text: (data.text as string) || '',
      timestamp: (data.timestamp as number) || Date.now() / 1000,
    }
    logs.value = [...logs.value, logEntry]

    if (autoScroll.value) {
      requestAnimationFrame(() => {
        if (logContainer.value) {
          logContainer.value.scrollTop = logContainer.value.scrollHeight
        }
      })
    }
  }

  // Job completed — refresh job list
  if (['executor:completed', 'executor:error', 'executor:timeout', 'executor:killed'].includes(evt.event) && jobId) {
    loadJobs()
  }

  // New job started — auto-select it
  if (evt.event === 'executor:started' && jobId && !activeJobId.value) {
    activeJobId.value = jobId
  }
}

watch(activeJobId, () => {
  loadLogs()
})

onMounted(() => {
  loadJobs()
  unsubSSE = subscribePipelineEvents((evt) => onSSE(evt))
})

onBeforeUnmount(() => {
  if (unsubSSE) { unsubSSE(); unsubSSE = null }
})
</script>

<style scoped>
.execution-log-tab {
  padding: 8px 0;
}

.job-selector {
  margin-bottom: 12px;
}
.job-select {
  width: 100%;
  max-width: 500px;
}

.job-summary {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 14px;
  background: var(--el-bg-color-page);
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.job-summary-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.summary-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.summary-value {
  font-size: 13px;
  font-weight: 500;
}

.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 4px;
}
.status-dot.running { background: #e6a23c; }
.status-dot.done { background: #67c23a; }
.status-dot.failed,
.status-dot.error,
.status-dot.timeout { background: #f56c6c; }
.status-dot.killed { background: #909399; }

.log-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.log-search {
  width: 200px;
}

.log-empty,
.log-waiting {
  text-align: center;
  padding: 60px 20px;
  color: var(--el-text-color-secondary);
}

.log-empty-hint {
  font-size: 12px;
  margin-top: 8px;
  opacity: 0.6;
}

.log-waiting .spin-icon {
  animation: spin 1.5s linear infinite;
}

@keyframes spin {
  100% { transform: rotate(360deg); }
}

.log-output {
  background: #0d1117;
  border-radius: 8px;
  padding: 8px 0;
  max-height: 520px;
  overflow-y: auto;
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.5;
}

.log-line {
  display: flex;
  gap: 8px;
  padding: 1px 12px;
  border-bottom: 1px solid rgba(255,255,255,0.03);
}

.log-line:hover {
  background: rgba(255,255,255,0.03);
}

.log-line-time {
  color: #6b7280;
  flex-shrink: 0;
  width: 60px;
}

.log-line-type {
  flex-shrink: 0;
  width: 28px;
  font-weight: 600;
  font-size: 10px;
}

.log-type-stdout .log-line-type { color: #a5b4fc; }
.log-type-stderr .log-line-type { color: #f87171; }
.log-type-error .log-line-type { color: #ef4444; font-weight: 700; }

.log-line-text {
  color: #e2e8f0;
  word-break: break-all;
  white-space: pre-wrap;
}

.log-type-stderr .log-line-text { color: #fca5a5; }
.log-type-error .log-line-text { color: #fca5a5; font-style: italic; }

.log-no-match {
  padding: 24px;
  text-align: center;
  color: #6b7280;
  font-size: 13px;
}

.log-load-more {
  text-align: center;
  padding: 10px;
}
</style>
