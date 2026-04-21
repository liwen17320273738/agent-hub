<template>
  <!--
    Custom Vue Flow node for an agent stage.

    UX choices worth flagging:
    * Two `Handle`s on each side (top/bottom is the wrong axis for a
      left-to-right SDLC pipeline; horizontal Handles read more
      naturally and match the auto-layout from `templateToBuilder`).
    * The role emoji + role label render from `roleEmoji/roleLabel`
      lookups so the builder vocabulary matches the backend exactly
      — no chance of "Designer" rendered here meaning a different
      role to the orchestrator.
    * `selected` and `data.warning` flip border color so cycle /
      validation feedback is visible at a glance without opening
      the config drawer.
  -->
  <div
    class="agent-stage-node"
    :class="{
      selected: props.selected,
      warn: !!props.data?.warning,
      'has-gate': !!props.data?.qualityGateMin,
      'has-human-gate': !!props.data?.humanGate,
      [`run-${props.data?.runStatus || 'idle'}`]: true,
    }"
  >
    <Handle type="target" :position="Position.Left" />
    <div v-if="runStatusBadge" class="run-status-pill" :title="runStatusBadge.title">
      <span class="run-dot" />
      {{ runStatusBadge.text }}
    </div>
    <div class="row title-row">
      <span class="emoji">{{ roleEmoji(props.data?.role) }}</span>
      <span class="label" :title="props.data?.label">{{ props.data?.label || '未命名' }}</span>
    </div>
    <div class="row meta-row">
      <span class="role-pill">{{ roleLabel(props.data?.role) }}</span>
      <span v-if="props.data?.model" class="model-pill" :title="props.data.model">
        {{ shortModel(props.data.model) }}
      </span>
    </div>
    <div class="row stage-id-row">
      <code class="stage-id">{{ props.data?.stageId }}</code>
    </div>
    <div v-if="badges.length" class="row badges-row">
      <span v-for="b in badges" :key="b.text" class="badge" :title="b.title">
        {{ b.text }}
      </span>
    </div>
    <Handle type="source" :position="Position.Right" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { roleEmoji, roleLabel } from '@/services/workflowBuilder'

type RunStatus =
  | 'idle' | 'running' | 'done' | 'failed' | 'rejected' | 'awaiting' | 'skipped'

interface NodeData {
  stageId: string
  label: string
  role: string
  model?: string | null
  qualityGateMin?: number
  rejectAction?: string
  onFailure?: string
  humanGate?: boolean
  /** Set by the parent when this node is part of a cycle / lint error. */
  warning?: string
  /** Set by the parent during live execution from SSE events. */
  runStatus?: RunStatus
  /** Last error string (used as tooltip on failed badge). */
  lastError?: string
}

const props = defineProps<{
  id: string
  data: NodeData
  selected?: boolean
}>()

function shortModel(m: string): string {
  // Trim noisy provider prefixes for the inline pill; the full string
  // is in the title attribute. e.g. "anthropic/claude-sonnet-4" → "claude-sonnet-4"
  const slash = m.lastIndexOf('/')
  return slash >= 0 ? m.slice(slash + 1) : m
}

const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  idle: '',
  running: '运行中',
  done: '已完成',
  failed: '失败',
  rejected: '被打回',
  awaiting: '待审批',
  skipped: '跳过',
}

const runStatusBadge = computed(() => {
  const s = (props.data?.runStatus || 'idle') as RunStatus
  if (s === 'idle') return null
  return {
    text: RUN_STATUS_LABELS[s],
    title:
      s === 'failed' && props.data?.lastError
        ? `失败：${props.data.lastError}`
        : RUN_STATUS_LABELS[s],
  }
})

const badges = computed(() => {
  const out: Array<{ text: string; title: string }> = []
  if (props.data?.qualityGateMin) {
    out.push({
      text: `≥ ${(props.data.qualityGateMin * 100).toFixed(0)}%`,
      title: `质量阈值 ${(props.data.qualityGateMin * 100).toFixed(0)}% — 低于则触发 reject self-heal`,
    })
  }
  if (props.data?.rejectAction && props.data.rejectAction !== 'self-heal') {
    out.push({
      text: props.data.rejectAction,
      title: `Reject 时执行: ${props.data.rejectAction}`,
    })
  }
  if (props.data?.onFailure && props.data.onFailure !== 'halt') {
    out.push({
      text: `fail: ${props.data.onFailure}`,
      title: `失败策略: ${props.data.onFailure}`,
    })
  }
  if (props.data?.humanGate) {
    out.push({ text: '👤', title: '该阶段需要人工审批' })
  }
  return out
})
</script>

<style scoped>
.agent-stage-node {
  position: relative;
  width: 220px;
  background: #1f2937;
  border: 1.5px solid #334155;
  border-radius: 10px;
  color: #e2e8f0;
  font-size: 12px;
  padding: 10px 12px;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
  cursor: pointer;
  transition: border-color 0.12s, box-shadow 0.12s, transform 0.12s;
}
.agent-stage-node:hover {
  border-color: #60a5fa;
}
.agent-stage-node.selected {
  border-color: #38bdf8;
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.25);
}
.agent-stage-node.warn {
  border-color: #f87171;
  box-shadow: 0 0 0 3px rgba(248, 113, 113, 0.25);
}

/* Run-status colour overrides — applied via .run-{status} on the root.
 * Border glow makes the active stage obvious from across the canvas
 * (we want the demo GIF to be readable at thumbnail size). */
.agent-stage-node.run-running {
  border-color: #38bdf8;
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.35);
  animation: stage-pulse 1.4s ease-in-out infinite;
}
.agent-stage-node.run-done {
  border-color: #34d399;
  box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.25);
}
.agent-stage-node.run-failed {
  border-color: #f87171;
  box-shadow: 0 0 0 3px rgba(248, 113, 113, 0.30);
}
.agent-stage-node.run-rejected {
  border-color: #fb923c;
  box-shadow: 0 0 0 3px rgba(251, 146, 60, 0.30);
}
.agent-stage-node.run-awaiting {
  border-color: #facc15;
  box-shadow: 0 0 0 3px rgba(250, 204, 21, 0.30);
}
.agent-stage-node.run-skipped {
  opacity: 0.55;
}
@keyframes stage-pulse {
  0%, 100% { box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.35); }
  50%      { box-shadow: 0 0 0 6px rgba(56, 189, 248, 0.18); }
}

.run-status-pill {
  position: absolute;
  top: -10px;
  right: 8px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 1px 8px;
  font-size: 10px;
  border-radius: 999px;
  background: #0f172a;
  color: #f8fafc;
  border: 1px solid #334155;
  white-space: nowrap;
}
.run-running .run-status-pill { color: #38bdf8; border-color: #1e40af; background: #082f49; }
.run-done    .run-status-pill { color: #34d399; border-color: #065f46; background: #022c22; }
.run-failed  .run-status-pill { color: #f87171; border-color: #7f1d1d; background: #2c0b0b; }
.run-rejected .run-status-pill { color: #fb923c; border-color: #7c2d12; background: #2a160c; }
.run-awaiting .run-status-pill { color: #facc15; border-color: #713f12; background: #261c0a; }
.run-skipped .run-status-pill { color: #94a3b8; }
.run-status-pill .run-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}
.row:first-child {
  margin-top: 0;
}
.title-row {
  font-weight: 600;
  font-size: 13px;
  color: #f8fafc;
}
.title-row .emoji {
  font-size: 16px;
  line-height: 1;
}
.title-row .label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta-row {
  flex-wrap: wrap;
}
.role-pill,
.model-pill {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  background: #0f172a;
  color: #94a3b8;
  border: 1px solid #1e293b;
}
.model-pill {
  background: #1e3a5f;
  color: #93c5fd;
  border-color: #1e40af;
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stage-id-row .stage-id {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10.5px;
  color: #64748b;
  background: transparent;
  padding: 0;
}

.badges-row {
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}
.badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #0f172a;
  color: #cbd5e1;
  border: 1px solid #334155;
}

/* Vue Flow handles — small, on the visible edges, blue when hovered. */
:deep(.vue-flow__handle) {
  width: 9px;
  height: 9px;
  background: #475569;
  border: 2px solid #1f2937;
}
:deep(.vue-flow__handle:hover) {
  background: #38bdf8;
}
</style>
