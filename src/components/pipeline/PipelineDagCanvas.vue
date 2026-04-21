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
        AI 军团作战图
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
  </div>
</template>

<script setup lang="ts">
import { computed, markRaw, onBeforeUnmount, ref, watch } from 'vue'
import { useVueFlow, VueFlow, type Edge, type Node } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { ElButton, ElIcon, ElTag } from 'element-plus'
import { Connection, FullScreen } from '@element-plus/icons-vue'

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
  [() => props.task, () => props.processingStageId, sseRunStatus],
  () => buildGraph(),
  { immediate: true, deep: true },
)

// ── Vue Flow viewport helpers ──
const { fitView } = useVueFlow()
function autoFit() { fitView({ padding: 0.15, duration: 250 }) }

function onNodeClick(payload: { node: Node }) {
  const stageId = (payload.node.data as { stageId?: string })?.stageId
  if (stageId) emit('node-click', stageId)
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
    case 'pipeline:dag-branch': {
      const target = data.to as string | undefined
      if (target) setStageStatus(target, 'rejected')
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
</style>
