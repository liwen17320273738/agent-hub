<template>
  <div class="pipeline-dashboard">
    <header class="pipeline-header">
      <div class="header-top">
        <h1>AI 军团流水线</h1>
        <div class="header-actions">
          <el-tag :type="healthStatus.pipeline === 'online' ? 'success' : 'danger'" size="small">
            {{ healthStatus.pipeline === 'online' ? '在线' : '离线' }}
          </el-tag>
          <el-tag v-if="healthStatus.feishu" type="info" size="small">飞书</el-tag>
          <el-tag v-if="healthStatus.qq" type="info" size="small">QQ</el-tag>
          <el-button type="primary" @click="showCreateDialog = true">
            <el-icon><Plus /></el-icon>
            创建任务
          </el-button>
        </div>
      </div>
      <p class="subtitle">
        飞书/QQ → OpenClaw 网关 → 自动编排 → Claude Code 执行 → 评审验收
      </p>
    </header>

    <section class="pipeline-stats">
      <div class="stat-card">
        <div class="stat-number">{{ pipelineStore.activeTasks.length }}</div>
        <div class="stat-label">进行中</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{{ pipelineStore.doneTasks.length }}</div>
        <div class="stat-label">已完成</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{{ pipelineStore.tasks.length }}</div>
        <div class="stat-label">全部任务</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{{ pipelineStore.eventLog.length }}</div>
        <div class="stat-label">事件流</div>
      </div>
    </section>

    <section class="pipeline-board">
      <h2 class="section-title">阶段看板</h2>
      <div class="stage-columns">
        <div
          v-for="stage in stages"
          :key="stage.id"
          class="stage-column"
          :class="{ 'has-tasks': (pipelineStore.tasksByStage[stage.id] || []).length > 0 }"
        >
          <div class="stage-header">
            <span class="stage-dot" :style="{ background: stageColor(stage.id) }"></span>
            <span class="stage-name">{{ stage.label }}</span>
            <el-badge
              :value="(pipelineStore.tasksByStage[stage.id] || []).length"
              :hidden="!(pipelineStore.tasksByStage[stage.id] || []).length"
              type="primary"
              class="stage-badge"
            />
          </div>
          <div class="stage-tasks">
            <div
              v-for="task in (pipelineStore.tasksByStage[stage.id] || [])"
              :key="task.id"
              class="task-card"
              @click="$router.push(`/pipeline/task/${task.id}`)"
            >
              <div class="task-title">{{ task.title }}</div>
              <div class="task-meta">
                <el-tag :type="sourceTagType(task.source)" size="small">{{ task.source }}</el-tag>
                <span class="task-time">{{ timeAgo(task.updatedAt) }}</span>
              </div>
            </div>
            <div v-if="!(pipelineStore.tasksByStage[stage.id] || []).length" class="stage-empty">
              暂无任务
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
        <div v-if="!traces.length" class="empty-state">暂无 trace 数据</div>
        <div v-else class="trace-list">
          <div v-for="trace in traces" :key="trace.taskId" class="trace-card">
            <div class="trace-header">
              <span class="trace-task">{{ trace.taskId?.slice(0, 8) }}...</span>
              <el-tag :type="trace.lastSpan?.status === 'completed' ? 'success' : 'warning'" size="small">
                {{ trace.lastSpan?.status || 'unknown' }}
              </el-tag>
            </div>
            <div class="trace-metrics">
              <span class="metric">
                <span class="metric-label">Spans</span>
                <span class="metric-value">{{ trace.spans }}</span>
              </span>
              <span class="metric" v-if="trace.lastSpan?.durationMs">
                <span class="metric-label">耗时</span>
                <span class="metric-value">{{ (trace.lastSpan.durationMs / 1000).toFixed(1) }}s</span>
              </span>
              <span class="metric" v-if="trace.lastSpan?.totalTokens">
                <span class="metric-label">Tokens</span>
                <span class="metric-value">{{ trace.lastSpan.totalTokens.toLocaleString() }}</span>
              </span>
              <span class="metric" v-if="trace.lastSpan?.model">
                <span class="metric-label">模型</span>
                <span class="metric-value model-tag">{{ trace.lastSpan.model }}</span>
              </span>
              <span class="metric" v-if="trace.lastSpan?.tier">
                <span class="metric-label">Tier</span>
                <span class="metric-value" :class="'tier-' + trace.lastSpan.tier">{{ trace.lastSpan.tier }}</span>
              </span>
            </div>
            <div class="trace-verify" v-if="trace.lastSpan?.verification">
              <span
                class="verify-badge"
                :class="'verify-' + trace.lastSpan.verification.overall"
              >
                {{ trace.lastSpan.verification.overall === 'pass' ? 'PASS' : trace.lastSpan.verification.overall === 'warn' ? 'WARN' : 'FAIL' }}
              </span>
              <span class="verify-detail" v-for="c in (trace.lastSpan.verification.checks || [])" :key="c.check">
                <span :class="'verify-dot-' + c.status"></span>
                {{ c.check }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Approvals Tab -->
      <div v-if="activeObsTab === 'approvals'" class="panel-content">
        <div v-if="!approvals.length" class="empty-state">无待审批操作</div>
        <div v-else class="approval-list">
          <div v-for="a in approvals" :key="a.id" class="approval-card">
            <div class="approval-info">
              <span class="approval-action">{{ a.action }}</span>
              <span class="approval-role">{{ a.role }}</span>
              <span class="approval-time">{{ timeAgo(a.createdAt) }}</span>
            </div>
            <div class="approval-actions">
              <el-button type="success" size="small" @click="handleApproval(a.id, true)">批准</el-button>
              <el-button type="danger" size="small" @click="handleApproval(a.id, false)">拒绝</el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- Audit Log Tab -->
      <div v-if="activeObsTab === 'audit'" class="panel-content">
        <div v-if="!auditEntries.length" class="empty-state">审计日志为空</div>
        <div v-else class="audit-list">
          <div v-for="(entry, idx) in auditEntries" :key="idx" class="audit-entry">
            <span class="audit-outcome" :class="'outcome-' + entry.outcome">{{ entry.outcome }}</span>
            <span class="audit-action">{{ entry.action }}</span>
            <span class="audit-role">{{ entry.role }}</span>
            <span class="audit-time">{{ formatTime(entry.time) }}</span>
          </div>
        </div>
      </div>

      <!-- Model Tiers Tab -->
      <div v-if="activeObsTab === 'tiers'" class="panel-content">
        <div class="tier-info">
          <div class="tier-group" v-for="(info, tierName) in modelTiers" :key="tierName">
            <h4 class="tier-name" :class="'tier-' + tierName">{{ info.label }}</h4>
            <div class="tier-roles">
              <el-tag v-for="role in info.roles" :key="role" size="small" class="tier-role-tag">{{ role }}</el-tag>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="pipeline-events" v-if="pipelineStore.eventLog.length">
      <h2 class="section-title">实时事件流</h2>
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

    <el-dialog v-model="showCreateDialog" title="创建新任务" width="520px">
      <el-form label-position="top">
        <el-form-item label="任务标题">
          <el-input v-model="newTask.title" placeholder="简洁描述需求..." />
        </el-form-item>
        <el-form-item label="需求描述">
          <el-input
            v-model="newTask.description"
            type="textarea"
            :rows="4"
            placeholder="详细需求描述..."
          />
        </el-form-item>
        <el-form-item label="来源">
          <el-select v-model="newTask.source" style="width: 100%">
            <el-option label="Web 手动" value="web" />
            <el-option label="API 接口" value="api" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="newTask.autoRun">创建后立即全自动执行 (AI 自动跑完所有阶段)</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleCreateTask" :loading="creating">
          {{ newTask.autoRun ? '创建并自动执行' : '创建任务' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { Plus } from '@element-plus/icons-vue'
import { usePipelineStore } from '@/stores/pipeline'
import { ElMessage } from 'element-plus'
import {
  fetchPipelineHealth, autoRunPipeline, smartRunPipeline,
  fetchTraces, fetchApprovals, resolveApproval as apiResolveApproval, fetchAuditLog,
} from '@/services/pipelineApi'
import type { PipelineEvent } from '@/agents/types'

const router = useRouter()

const pipelineStore = usePipelineStore()

const showCreateDialog = ref(false)
const creating = ref(false)
const healthStatus = ref<Record<string, unknown>>({})

const activeObsTab = ref('traces')
const traces = ref<any[]>([])
const approvals = ref<any[]>([])
const auditEntries = ref<any[]>([])

const obsTabs = computed(() => [
  { id: 'traces', label: 'Traces', badge: traces.value.length || null },
  { id: 'approvals', label: '审批', badge: approvals.value.length || null },
  { id: 'audit', label: '审计日志', badge: null },
  { id: 'tiers', label: '模型分级', badge: null },
])

const modelTiers = {
  planning: {
    label: 'Tier 1 — Planning (强模型)',
    roles: ['orchestrator', 'lead-agent', 'wayne-ceo', 'wayne-cto', 'wayne-acceptance'],
  },
  execution: {
    label: 'Tier 2 — Execution (平衡)',
    roles: ['product-manager', 'developer', 'qa-lead', 'wayne-product', 'wayne-developer'],
  },
  routine: {
    label: 'Tier 3 — Routine (低成本)',
    roles: ['wayne-marketing', 'wayne-finance', 'wayne-devops', 'openclaw'],
  },
}

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
    ElMessage.success(approved ? '已批准' : '已拒绝')
    await loadObsData()
  } catch (e: any) {
    ElMessage.error(`操作失败: ${e.message}`)
  }
}

const newTask = ref({
  title: '',
  description: '',
  source: 'web',
  autoRun: true,
})

const stages = [
  { id: 'intake', label: '需求接入' },
  { id: 'planning', label: 'PRD 定义' },
  { id: 'architecture', label: '技术方案' },
  { id: 'building', label: '开发实现' },
  { id: 'testing', label: '质量验证' },
  { id: 'reviewing', label: '验收评审' },
  { id: 'done', label: '已完成' },
]

const stageColors: Record<string, string> = {
  intake: '#6366f1',
  planning: '#3b82f6',
  architecture: '#14b8a6',
  building: '#f59e0b',
  testing: '#ef4444',
  reviewing: '#8b5cf6',
  done: '#22c55e',
}

function stageColor(id: string) {
  return stageColors[id] || '#666'
}

function sourceTagType(source: string) {
  const map: Record<string, string> = {
    feishu: 'warning',
    qq: 'success',
    web: 'info',
    api: '',
  }
  return (map[source] || '') as '' | 'success' | 'warning' | 'info' | 'danger'
}

function timeAgo(ts: number) {
  const diff = Date.now() - ts
  if (diff < 60_000) return '刚刚'
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)}分钟前`
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)}小时前`
  return `${Math.floor(diff / 86400_000)}天前`
}

function formatTime(ts: number) {
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
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
  const labels: Record<string, string> = {
    'task:created': '任务创建',
    'task:updated': '任务更新',
    'task:stage-advanced': '阶段推进',
    'task:rejected': '阶段打回',
    'task:deleted': '任务删除',
    'openclaw:intake': '需求接入',
    'stage:queued': '阶段排队',
    'stage:processing': 'AI 处理中',
    'stage:completed': '阶段完成',
    'stage:error': '阶段错误',
    'pipeline:auto-start': '🚀 自动启动',
    'pipeline:auto-completed': '🎉 全流程完成',
    'pipeline:auto-paused': '⏸️ 暂停等待',
    'pipeline:auto-error': '💥 流程错误',
    'executor:started': '执行开始',
    'executor:completed': '执行完成',
    'executor:error': '执行错误',
    connected: '连接建立',
  }
  return labels[event] || event
}

function eventDetail(event: PipelineEvent) {
  const data = event.data as Record<string, unknown>
  if (data?.title) return String(data.title)
  if (data?.taskId) return `任务 ${String(data.taskId).slice(0, 8)}...`
  return ''
}

async function handleCreateTask() {
  if (!newTask.value.title.trim()) {
    ElMessage.warning('请输入任务标题')
    return
  }
  creating.value = true
  try {
    const task = await pipelineStore.createTask({
      title: newTask.value.title,
      description: newTask.value.description,
      source: newTask.value.source,
    })
    showCreateDialog.value = false

    if (newTask.value.autoRun) {
      await smartRunPipeline(task.id)
      router.push(`/pipeline/task/${task.id}`)
    }

    newTask.value = { title: '', description: '', source: 'web', autoRun: true }
  } catch (e: unknown) {
    ElMessage.error(`创建任务失败: ${e instanceof Error ? e.message : String(e)}`)
  } finally {
    creating.value = false
  }
}

onMounted(async () => {
  pipelineStore.loadTasks()
  pipelineStore.startEventStream()
  try {
    healthStatus.value = await fetchPipelineHealth()
  } catch {
    healthStatus.value = { pipeline: 'offline' }
  }
  loadObsData()
})

onUnmounted(() => {
  pipelineStore.stopEventStream()
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

.stat-number {
  font-size: 32px;
  font-weight: 700;
  color: var(--accent);
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

.stage-columns {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px;
}

.stage-column {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 14px;
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
}

.stage-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.stage-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.stage-tasks {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-card {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.task-card:hover {
  border-color: var(--accent);
  transform: translateY(-1px);
}

.task-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 6px;
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
</style>
