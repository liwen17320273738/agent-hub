<template>
  <!--
    Live DAG canvas for AI-army pipelines.

    Why this exists:
      The legacy vertical stepper in PipelineTaskDetail (numbered circles 1-7)
      reads as a static report card. Even when the backend is doing work, the
      UI looks frozen. This component reuses the Workflow Builder's
      `AgentStageNode` + Vue Flow + the existing SSE feed to give the same
      page a "live battlefield" feel — pulsing borders on the active stage,
      colour-coded statuses, automatic provider-fallback badges.

    Design choices worth flagging:
      * Linear pipelines (the only kind PipelineStageState supports today)
        get edges connecting [n] → [n+1]. When dependsOn arrives, swap to
        explicit deps without touching the parent.
      * Status mapping is *additive*: SSE updates layer on top of the snapshot
        from `task.stages`. That way a freshly-loaded page shows the right
        colours even before any SSE event arrives, and SSE events can show
        finer-grained transitions (running → done) the snapshot can't.
      * `processingStageId` (set by parent during ad-hoc actions like Smart
        Run) wins over snapshot status, because the snapshot lags by ~1 SSE
        round-trip.
  -->
  <div class="pipeline-dag-canvas">
    <div class="canvas-header">
      <h2 class="section-title">
        <el-icon><Connection /></el-icon>
        任务编排图
      </h2>
      <div class="canvas-actions">
        <el-tag
          v-if="lastFallback"
          size="small"
          type="warning"
          effect="dark"
          class="fallback-tag"
          :title="lastFallback.reason"
        >
          🔄 自动降级 → {{ lastFallback.to_provider }}/{{ shortModel(lastFallback.to_model) }}
        </el-tag>
        <el-tag
          :type="sseStatus === 'connected' ? 'success' : 'info'"
          size="small"
          effect="plain"
        >
          SSE: {{ sseStatusLabel }}
        </el-tag>
        <el-button size="small" text @click="autoFit">
          <el-icon><FullScreen /></el-icon>
          适配视窗
        </el-button>
      </div>
    </div>

    <div class="canvas-body" :style="{ height: canvasHeight + 'px' }">
      <VueFlow
        v-model:nodes="nodes"
        v-model:edges="edges"
        :node-types="nodeTypes"
        :default-edge-options="defaultEdgeOptions"
        :default-viewport="defaultViewport"
        :pan-on-drag="true"
        :nodes-draggable="false"
        :nodes-connectable="false"
        :elements-selectable="true"
        @node-click="onNodeClick"
        fit-view-on-init
      >
        <Background pattern-color="#1e293b" :gap="22" />
        <Controls />
      </VueFlow>
    </div>

    <!--
      Self-heal drawer: opens when the user clicks a node that has at least
      one rework attempt recorded. We render the *latest* attempt's diff
      first (most actionable) and let the user step backwards through prior
      attempts. The drawer lives inside this component so the parent view
      doesn't need to know how SSE rework events are accumulated.
    -->
    <el-drawer
      v-model="healDrawerOpen"
      :title="healDrawerTitle"
      direction="rtl"
      size="56%"
    >
      <div v-if="!healDrawerEvents.length" class="heal-empty">
        <p>该阶段暂无自愈记录。</p>
      </div>
      <div v-else class="heal-body">
        <div class="heal-pager">
          <el-button-group>
            <el-button
              size="small"
              :disabled="healCursor === 0"
              @click="healCursor = Math.max(0, healCursor - 1)"
            >
              <el-icon><ArrowLeft /></el-icon>
              上一次
            </el-button>
            <el-button
              size="small"
              :disabled="healCursor >= healDrawerEvents.length - 1"
              @click="healCursor = Math.min(healDrawerEvents.length - 1, healCursor + 1)"
            >
              下一次
              <el-icon><ArrowRight /></el-icon>
            </el-button>
          </el-button-group>
          <span class="heal-pager-meta">
            第 {{ healCursor + 1 }} / {{ healDrawerEvents.length }} 次自愈 ·
            <strong>{{ formatHealTime(currentHealEvent?.at) }}</strong>
          </span>
        </div>

        <div class="heal-card heal-feedback">
          <div class="heal-card-title">
            <span class="heal-card-icon">📝</span>
            审阅反馈
            <span v-if="currentHealEvent?.reviewer" class="heal-reviewer">
              · {{ currentHealEvent.reviewer }}
            </span>
          </div>
          <pre class="heal-feedback-text">{{ currentHealEvent?.feedback || '(无)' }}</pre>
        </div>

        <div class="heal-card heal-before">
          <div class="heal-card-title">
            <span class="heal-card-icon">🚫</span>
            被打回的草稿
            <el-tag v-if="currentHealEvent?.truncated" size="small" type="warning" effect="dark">
              已截断
            </el-tag>
          </div>
          <pre class="heal-draft">{{ currentHealEvent?.rejectedDraft || '(SSE 未携带草稿)' }}</pre>
        </div>

        <div class="heal-card heal-after">
          <div class="heal-card-title">
            <span class="heal-card-icon">✅</span>
            最新产出（来自 task.stages）
            <el-button
              v-if="currentStageOutput"
              size="small"
              text
              type="primary"
              @click="emit('node-click', healDrawerStageId)"
            >
              在主面板打开 →
            </el-button>
          </div>
          <pre class="heal-draft">{{ currentStageOutput?.slice(0, 4000) || '(尚无新产出)' }}</pre>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, markRaw, onBeforeUnmount, ref, watch } from 'vue'
import { useVueFlow, VueFlow, type Edge, type Node } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { ElButton, ElButtonGroup, ElDrawer, ElIcon, ElTag } from 'element-plus'
import { ArrowLeft, ArrowRight, Connection, FullScreen } from '@element-plus/icons-vue'

import AgentStageNode from '@/components/builder/AgentStageNode.vue'
import { subscribePipelineEvents, type SSEStatus } from '@/services/pipelineApi'
import type { PipelineTask, PipelineStageState, PipelineEvent } from '@/agents/types'

import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'

type RunStatus = 'idle' | 'running' | 'done' | 'failed' | 'rejected' | 'awaiting' | 'skipped'

interface FallbackEvent {
  from_provider?: string
  from_model?: string
  to_provider?: string
  to_model?: string
  reason?: string
}

const props = defineProps<{
  task: PipelineTask
  /** Stage currently being processed (set by parent during Smart Run / Auto Run). */
  processingStageId?: string | null
  /** Optional explicit height; defaults to a sensible 360px. */
  height?: number
}>()

const emit = defineEmits<{
  (e: 'node-click', stageId: string): void
}>()

const canvasHeight = computed(() => props.height ?? 360)
const nodeTypes = { agentStage: markRaw(AgentStageNode) }
const defaultViewport = { x: 0, y: 0, zoom: 0.85 }
const defaultEdgeOptions = {
  type: 'smoothstep',
  animated: false,
  style: { stroke: '#475569', strokeWidth: 1.6 },
  markerEnd: { type: 'arrowclosed' as const, color: '#475569' },
}

// Per-node runtime status from SSE; keyed by stage id. Layered on top of the
// snapshot so a fresh page paint already shows the right colours.
const sseRunStatus = ref<Map<string, { status: RunStatus; lastError?: string }>>(
  new Map(),
)

const sseStatus = ref<SSEStatus>('disconnected')
const sseStatusLabel = computed(() => {
  switch (sseStatus.value) {
    case 'connected': return '已连接'
    case 'connecting': return '连接中'
    case 'reconnecting': return '重连中'
    default: return '未连接'
  }
})

const lastFallback = ref<FallbackEvent | null>(null)

// ── Self-heal history, accumulated from SSE ──
//
// Each `stage:rework` (linear pipeline) and `pipeline:dag-branch` (DAG
// orchestrator) event captures one rejected draft + its review feedback.
// We keep them per-stage so the operator can scrub through prior attempts
// when the AI is still wrestling with the same stage.
//
// Cap at 8 attempts/stage — that's twice the engine's MAX_REVIEW_RETRIES,
// enough headroom for the DAG branch case and far below anything that
// would matter for memory.
interface SelfHealEvent {
  attempt: number
  feedback: string
  rejectedDraft: string
  truncated: boolean
  reviewer: string
  at: number
}
const SELF_HEAL_CAP = 8
const selfHealHistory = ref<Map<string, SelfHealEvent[]>>(new Map())

function pushSelfHeal(stageId: string, evt: SelfHealEvent) {
  const next = new Map(selfHealHistory.value)
  const cur = next.get(stageId) || []
  next.set(stageId, [...cur, evt].slice(-SELF_HEAL_CAP))
  selfHealHistory.value = next
}

// Drawer state
const healDrawerOpen = ref(false)
const healDrawerStageId = ref<string>('')
const healCursor = ref(0)
const healDrawerEvents = computed<SelfHealEvent[]>(
  () => selfHealHistory.value.get(healDrawerStageId.value) || [],
)
const currentHealEvent = computed<SelfHealEvent | undefined>(
  () => healDrawerEvents.value[healCursor.value],
)
const healDrawerTitle = computed(() => {
  const stage = props.task.stages.find((s) => s.id === healDrawerStageId.value)
  const label = stage?.label || healDrawerStageId.value
  return `🔁 自愈历史 · ${label}`
})
const currentStageOutput = computed(() => {
  const stage = props.task.stages.find((s) => s.id === healDrawerStageId.value)
  return stage?.output || ''
})
function formatHealTime(ms?: number): string {
  if (!ms) return ''
  const d = new Date(ms)
  return d.toLocaleString()
}

// ── Status mapping: PipelineStageState.status → AgentStageNode runStatus ──
function mapStageStatus(s: PipelineStageState, taskFailed: boolean): RunStatus {
  switch (s.status) {
    case 'done':       return 'done'
    case 'active':     return 'running'
    case 'reviewing':  return 'running'
    case 'rejected':   return 'rejected'
    case 'awaiting_approval': return 'awaiting'
    case 'blocked':    return 'failed'
    case 'pending':
      // If the whole task is failed and this is the current stage, light it
      // up red — the failed stage is technically still 'pending' in the DB
      // when the worker died mid-execution.
      if (taskFailed && s.id === props.task.currentStageId) return 'failed'
      return 'idle'
    default:           return 'idle'
  }
}

// ── Build nodes + edges from task.stages ──
const HORIZONTAL_GAP = 260
const NODE_Y = 40

const nodes = ref<Node[]>([])
const edges = ref<Edge[]>([])

function buildGraph() {
  // The PipelineTask shape uses a 'failed' status that the type union doesn't
  // include yet — cast through string to keep TS quiet.
  const taskFailed = String((props.task as unknown as { status: string }).status) === 'failed'
  const sseMap = sseRunStatus.value

  nodes.value = props.task.stages.map((stage, idx) => {
    const fromSse = sseMap.get(stage.id)
    const fromProcessing =
      props.processingStageId === stage.id ? { status: 'running' as RunStatus } : null
    const fromSnapshot = mapStageStatus(stage, taskFailed)
    // Precedence: processing > SSE > snapshot. Once a stage finishes the
    // snapshot becomes authoritative again; processingStage gets nulled out
    // by the parent on `stage:completed`.
    const runStatus: RunStatus =
      fromProcessing?.status || fromSse?.status || fromSnapshot

    const healCount = selfHealHistory.value.get(stage.id)?.length || 0

    return {
      id: stage.id,
      type: 'agentStage',
      position: { x: idx * HORIZONTAL_GAP, y: NODE_Y },
      data: {
        stageId: stage.id,
        label: stage.label,
        role: stage.ownerRole,
        runStatus,
        lastError: fromSse?.lastError,
        qualityGateMin: stage.gateScore && stage.gateScore < 1 ? stage.gateScore : undefined,
        selfHealAttempts: healCount,
      },
      // The AgentStageNode handles both selection & rendering; we don't want
      // the user to drag stages around on a live execution view.
      draggable: false,
      selectable: true,
    }
  })

  edges.value = []
  for (let i = 1; i < props.task.stages.length; i++) {
    const prev = props.task.stages[i - 1]
    const cur = props.task.stages[i]
    edges.value.push({
      id: `${prev.id}->${cur.id}`,
      source: prev.id,
      target: cur.id,
      type: 'smoothstep',
      animated: cur.status === 'active' || cur.id === props.processingStageId,
      style: {
        stroke: cur.status === 'active' || cur.id === props.processingStageId ? '#38bdf8' : '#475569',
        strokeWidth: 1.6,
      },
    })
  }
}

watch(
  [() => props.task, () => props.processingStageId, sseRunStatus, selfHealHistory],
  () => buildGraph(),
  { immediate: true, deep: true },
)

// ── Vue Flow viewport helpers ──
const { fitView } = useVueFlow()
function autoFit() { fitView({ padding: 0.15, duration: 250 }) }

function onNodeClick(payload: { node: Node }) {
  const stageId = (payload.node.data as { stageId?: string })?.stageId
  if (!stageId) return
  // If this stage has self-heal history, prefer opening the diff drawer —
  // that's what the 🔁 pill is hinting at. Holding shift bypasses (lets
  // power-users go straight to the in-page section).
  const hasHistory = (selfHealHistory.value.get(stageId) || []).length > 0
  if (hasHistory) {
    healDrawerStageId.value = stageId
    healCursor.value = (selfHealHistory.value.get(stageId)?.length ?? 1) - 1
    healDrawerOpen.value = true
    return
  }
  emit('node-click', stageId)
}

function shortModel(m?: string): string {
  if (!m) return ''
  const slash = m.lastIndexOf('/')
  return slash >= 0 ? m.slice(slash + 1) : m
}

// ── SSE bridge ──
let unsubSSE: (() => void) | null = null

function setStageStatus(stageId: string, status: RunStatus, lastError?: string) {
  const next = new Map(sseRunStatus.value)
  next.set(stageId, { status, lastError })
  sseRunStatus.value = next
}

function onSSE(evt: PipelineEvent) {
  const data = (evt.data || {}) as Record<string, unknown>
  const eventTaskId = (data.taskId as string) || undefined
  if (eventTaskId && eventTaskId !== props.task.id) return

  const stageId = (data.stageId as string) || ''

  switch (evt.event) {
    case 'pipeline:dag-start':
      sseRunStatus.value = new Map()
      break
    case 'stage:processing':
      if (stageId) setStageStatus(stageId, 'running')
      break
    case 'stage:completed':
      if (stageId) setStageStatus(stageId, 'done')
      break
    case 'stage:retry':
      if (stageId) setStageStatus(stageId, 'running', String(data.lastError || ''))
      break
    case 'stage:error':
      if (stageId) setStageStatus(stageId, 'failed', String(data.error || '执行失败'))
      break
    case 'stage:awaiting-approval':
      if (stageId) setStageStatus(stageId, 'awaiting')
      break
    case 'stage:skipped':
      if (stageId) setStageStatus(stageId, 'skipped')
      break
    case 'stage:provider-fallback':
      // New event from llm_router. Surface the rotation as a top banner —
      // stage status itself stays "running" because the next provider is
      // about to be tried.
      lastFallback.value = data as FallbackEvent
      break
    case 'stage:rework': {
      // Linear pipeline self-heal — peer-review rejected, regenerating.
      // The stage stays "running" (we're regenerating now); the badge
      // count goes up.
      if (!stageId) break
      pushSelfHeal(stageId, {
        attempt: Number(data.attempt) || 1,
        feedback: String(data.feedback || ''),
        rejectedDraft: String(data.rejectedDraft || ''),
        truncated: Boolean(data.rejectedDraftTruncated),
        reviewer: String(data.reviewer || ''),
        at: evt.timestamp || Date.now(),
      })
      setStageStatus(stageId, 'running')
      break
    }
    case 'pipeline:dag-branch': {
      // DAG path equivalent of stage:rework — reviewing stage REJECTED a
      // downstream stage and we're branching back to it. The "to" stage
      // is what's about to be regenerated.
      const target = data.to as string | undefined
      if (target) {
        setStageStatus(target, 'rejected')
        pushSelfHeal(target, {
          attempt: Number(data.rejectCount) || 1,
          feedback: String(data.feedbackPreview || ''),
          rejectedDraft: String(data.rejectedDraft || ''),
          truncated: Boolean(data.rejectedDraftTruncated),
          reviewer: 'reviewing',
          at: evt.timestamp || Date.now(),
        })
      }
      break
    }
    case 'pipeline:rollback':
      if (stageId) setStageStatus(stageId, 'failed', String(data.reason || '回滚'))
      break
  }
}

unsubSSE = subscribePipelineEvents(
  (evt) => onSSE(evt),
  (s) => { sseStatus.value = s },
)

onBeforeUnmount(() => {
  if (unsubSSE) { unsubSSE(); unsubSSE = null }
})
</script>

<style scoped>
.pipeline-dag-canvas {
  background: #0b1220;
  border: 1px solid #1e293b;
  border-radius: 12px;
  margin-bottom: 24px;
  overflow: hidden;
}

.canvas-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #1e293b;
  background: linear-gradient(180deg, #0f172a 0%, #0b1220 100%);
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #f8fafc;
  margin: 0;
}

.canvas-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.fallback-tag {
  animation: pop 320ms ease-out;
}

.canvas-body {
  width: 100%;
  background:
    radial-gradient(ellipse at center, rgba(56, 189, 248, 0.05) 0%, transparent 70%),
    #0b1220;
}

@keyframes pop {
  0%   { transform: scale(0.85); opacity: 0; }
  50%  { transform: scale(1.05); opacity: 1; }
  100% { transform: scale(1); }
}

/* Vue Flow theme overrides — match the dark dashboard. */
:deep(.vue-flow__edge-path) {
  stroke-linecap: round;
}
:deep(.vue-flow__controls) {
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 6px;
}
:deep(.vue-flow__controls-button) {
  background: transparent;
  color: #cbd5e1;
  border-bottom: 1px solid #1e293b;
}
:deep(.vue-flow__controls-button:hover) {
  background: #1e293b;
  color: #38bdf8;
}
:deep(.vue-flow__controls-button svg) {
  fill: currentColor;
}

/* ── Self-heal drawer ── */
.heal-empty {
  padding: 24px;
  color: #94a3b8;
  font-style: italic;
}
.heal-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px 20px;
}
.heal-pager {
  display: flex;
  align-items: center;
  gap: 12px;
}
.heal-pager-meta {
  font-size: 12px;
  color: #94a3b8;
}
.heal-pager-meta strong {
  color: #cbd5e1;
}
.heal-card {
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 8px;
  padding: 12px;
}
.heal-card.heal-feedback { border-color: #1e40af; }
.heal-card.heal-before   { border-color: #7f1d1d; }
.heal-card.heal-after    { border-color: #14532d; }
.heal-card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
  margin-bottom: 8px;
}
.heal-card-icon {
  font-size: 14px;
}
.heal-reviewer {
  font-weight: 400;
  color: #94a3b8;
  font-size: 11px;
}
.heal-feedback-text,
.heal-draft {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 11.5px;
  color: #cbd5e1;
  background: #0b1220;
  border: 1px solid #111827;
  border-radius: 6px;
  padding: 10px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 360px;
  overflow: auto;
}
</style>
