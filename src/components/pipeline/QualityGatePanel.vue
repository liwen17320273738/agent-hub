<template>
  <!--
    Single source of truth for showing a stage's quality-gate result.

    Why a dedicated component (instead of the previous inline div):
      - The check list, suggestions, block_reason, and override metadata used
        to be 4 separate divs scattered in PipelineTaskDetail.vue. They shared
        no layout, so a failing gate would render as an unfocused wall of
        text. Here they're laid out as: [score arc] · [category bars] ·
        [grouped checks] · [suggestions] — which mirrors how an operator
        actually triages: "how bad?" → "where?" → "exactly what?" → "how do I fix?"
      - The score arc + category bars are pure SVG/CSS, no chart lib.
      - We always render even if `gateDetails` is missing — the empty state
        ("尚未运行门禁") is more useful than rendering nothing, because the
        absence of a panel was previously confused with a passing gate.
  -->
  <div class="qg-panel" :class="['status-' + (gateStatus || 'pending')]">
    <!-- ── header: score arc + verdict tag ── -->
    <div class="qg-header">
      <div class="qg-score-arc">
        <svg viewBox="0 0 80 80" class="arc-svg">
          <circle cx="40" cy="40" r="34" class="arc-bg" />
          <circle
            cx="40"
            cy="40"
            r="34"
            class="arc-fg"
            :stroke-dasharray="arcDashArray"
            :stroke-dashoffset="arcDashOffset"
          />
        </svg>
        <div class="arc-center">
          <div class="arc-pct">{{ scorePct }}<span class="pct-sym">%</span></div>
          <div class="arc-label">{{ t('qualityGate.overallScore') }}</div>
        </div>
      </div>
      <div class="qg-verdict">
        <div class="verdict-pill" :class="'verdict-' + (gateStatus || 'pending')">
          <span class="verdict-icon">{{ verdictIcon }}</span>
          <span class="verdict-text">{{ verdictLabel }}</span>
        </div>
        <div v-if="blockReason" class="block-reason">
          <el-icon class="reason-icon"><Warning /></el-icon>
          <span>{{ blockReason }}</span>
        </div>
        <div v-else-if="overrideInfo" class="override-line">
          🔓 {{ t('qualityGate.manualOverrideBy') }} · {{ overrideInfo.by }}
          <span v-if="overrideInfo.reason"> — {{ overrideInfo.reason }}</span>
        </div>
      </div>
    </div>

    <!-- ── category bars: one row per category, segment per check ── -->
    <div v-if="categories.length" class="qg-categories">
      <div v-for="cat in categories" :key="cat.name" class="cat-row">
        <div class="cat-label">
          <span class="cat-name">{{ catLabel(cat.name) }}</span>
          <span class="cat-score" :class="'score-' + cat.aggStatus">
            {{ Math.round(cat.aggScore * 100) }}%
          </span>
        </div>
        <div class="cat-bar">
          <div
            v-for="(seg, i) in cat.checks"
            :key="i"
            class="cat-seg"
            :class="'seg-' + normStatus(seg.status)"
            :style="{ flexGrow: 1 }"
            :title="`${seg.name}: ${seg.message}`"
          />
        </div>
      </div>
    </div>

    <!-- ── grouped check list ── -->
    <div v-if="checks.length" class="qg-checks">
      <details
        v-for="cat in categories"
        :key="cat.name"
        class="cat-group"
        :open="cat.aggStatus !== 'passed'"
      >
        <summary class="cat-summary">
          <span class="summary-icon">{{ catIcon(cat.aggStatus) }}</span>
          <span class="summary-label">{{ catLabel(cat.name) }}</span>
          <span class="summary-count">{{ t('qualityGate.itemsCount', { n: cat.checks.length }) }}</span>
        </summary>
        <ul class="check-list">
          <li
            v-for="(c, idx) in cat.checks"
            :key="idx"
            class="check-row"
            :class="'row-' + normStatus(c.status)"
          >
            <span class="check-icon">{{ statusIcon(c.status) }}</span>
            <span class="check-name">{{ c.name }}</span>
            <span class="check-score">{{ Math.round(c.score * 100) }}%</span>
            <span class="check-msg">{{ c.message || '—' }}</span>
          </li>
        </ul>
      </details>
    </div>

    <!-- ── suggestions ── -->
    <div v-if="suggestions.length" class="qg-suggestions">
      <div class="sg-header">
        <el-icon><InfoFilled /></el-icon>
        <span>{{ t('qualityGate.suggestions') }}</span>
      </div>
      <ul>
        <li v-for="(s, i) in suggestions" :key="i">{{ s }}</li>
      </ul>
    </div>

    <!-- ── action footer ── -->
    <div v-if="gateStatus === 'failed' && !overrideInfo" class="qg-actions">
      <el-button type="warning" size="small" @click="$emit('override')" :loading="overriding">
        <el-icon><Unlock /></el-icon>
        {{ t('qualityGate.manualOverride') }}
      </el-button>
      <span class="action-hint">{{ t('qualityGate.overrideHint') }}</span>
    </div>

    <!-- ── empty state ── -->
    <div v-if="!checks.length && !blockReason" class="qg-empty">
      <el-icon><Loading /></el-icon>
      <span>{{ t('qualityGate.emptyNotRun') }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Warning, InfoFilled, Unlock, Loading } from '@element-plus/icons-vue'

const { t } = useI18n()

interface GateCheck {
  name: string
  category: string
  status: string
  score: number
  message: string
}
interface OverrideInfo {
  by: string
  reason: string
}

const props = defineProps<{
  gateStatus?: 'passed' | 'warning' | 'failed' | 'bypassed' | 'pending' | null
  gateScore?: number | null
  gateDetails?: {
    checks?: GateCheck[]
    suggestions?: string[]
    block_reason?: string | null
    override?: OverrideInfo | null
  } | null
  overriding?: boolean
}>()

defineEmits<{
  (e: 'override'): void
}>()

const checks = computed<GateCheck[]>(() => props.gateDetails?.checks || [])
const suggestions = computed<string[]>(() => props.gateDetails?.suggestions || [])
const blockReason = computed(() => props.gateDetails?.block_reason || '')
const overrideInfo = computed<OverrideInfo | null>(() => props.gateDetails?.override || null)

// Score arc: stroke-dashoffset trick on a 34-radius circle.
// circumference = 2π·34 ≈ 213.628
const ARC_CIRCUMFERENCE = 2 * Math.PI * 34
const score = computed(() => {
  const v = props.gateScore
  if (v == null || Number.isNaN(v)) return 0
  return Math.max(0, Math.min(1, v))
})
const scorePct = computed(() => Math.round(score.value * 100))
const arcDashArray = computed(() => `${ARC_CIRCUMFERENCE.toFixed(2)}`)
const arcDashOffset = computed(() =>
  `${(ARC_CIRCUMFERENCE * (1 - score.value)).toFixed(2)}`,
)

// Verdict mapping
const verdictIcon = computed(() => {
  switch (props.gateStatus) {
    case 'passed':
      return '✅'
    case 'warning':
      return '⚠️'
    case 'failed':
      return '❌'
    case 'bypassed':
      return '🔓'
    default:
      return '⏳'
  }
})
const verdictLabel = computed(() => {
  switch (props.gateStatus) {
    case 'passed':
      return t('qualityGate.verdictPassed')
    case 'warning':
      return t('qualityGate.verdictWarning')
    case 'failed':
      return t('qualityGate.verdictFailed')
    case 'bypassed':
      return t('qualityGate.verdictBypassed')
    default:
      return t('qualityGate.verdictPending')
  }
})

// Group checks by category, computing each category's aggregate status/score.
// Aggregate rule: if any FAILED → failed; else if any WARNING → warning;
// else passed. Score = mean of underlying check scores.
function normStatus(s: string): 'passed' | 'warning' | 'failed' | 'pending' {
  const v = (s || '').toLowerCase()
  if (v === 'pass' || v === 'passed') return 'passed'
  if (v === 'warn' || v === 'warning') return 'warning'
  if (v === 'fail' || v === 'failed') return 'failed'
  return 'pending'
}
const categories = computed(() => {
  const groups: Record<string, GateCheck[]> = {}
  for (const c of checks.value) {
    const cat = c.category || 'misc'
    if (!groups[cat]) groups[cat] = []
    groups[cat].push(c)
  }
  return Object.entries(groups).map(([name, items]) => {
    const norms = items.map((c) => normStatus(c.status))
    const aggStatus = norms.includes('failed')
      ? 'failed'
      : norms.includes('warning')
        ? 'warning'
        : 'passed'
    const aggScore = items.length
      ? items.reduce((a, c) => a + (c.score || 0), 0) / items.length
      : 0
    return { name, checks: items, aggStatus, aggScore }
  })
})

function statusIcon(s: string): string {
  switch (normStatus(s)) {
    case 'passed':
      return '✓'
    case 'warning':
      return '!'
    case 'failed':
      return '✗'
    default:
      return '·'
  }
}
function catIcon(s: string): string {
  switch (s) {
    case 'passed':
      return '✅'
    case 'warning':
      return '⚠️'
    case 'failed':
      return '❌'
    default:
      return '·'
  }
}
function catLabel(name: string): string {
  switch (name) {
    case 'deliverable':
      return t('qualityGate.catDeliverable')
    case 'threshold':
      return t('qualityGate.catThreshold')
    case 'length':
      return t('qualityGate.catLength')
    case 'llm':
      return t('qualityGate.catLlm')
    case 'heuristic':
      return t('qualityGate.catHeuristic')
    default:
      return name
  }
}
</script>

<style scoped>
.qg-panel {
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  position: relative;
}
.qg-panel.status-passed {
  border-color: #14532d;
}
.qg-panel.status-warning {
  border-color: #854d0e;
  background: linear-gradient(180deg, #1c1917 0%, #0f172a 60%);
}
.qg-panel.status-failed {
  border-color: #7f1d1d;
  background: linear-gradient(180deg, #1c1117 0%, #0f172a 60%);
}
.qg-panel.status-bypassed {
  border-color: #155e75;
}

/* ── header / arc ── */
.qg-header {
  display: flex;
  gap: 18px;
  align-items: center;
}
.qg-score-arc {
  position: relative;
  width: 80px;
  height: 80px;
  flex-shrink: 0;
}
.arc-svg {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}
.arc-bg {
  fill: none;
  stroke: #1e293b;
  stroke-width: 8;
}
.arc-fg {
  fill: none;
  stroke-width: 8;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.6s ease, stroke 0.4s;
}
.status-passed .arc-fg {
  stroke: #22c55e;
}
.status-warning .arc-fg {
  stroke: #f59e0b;
}
.status-failed .arc-fg {
  stroke: #ef4444;
}
.status-bypassed .arc-fg {
  stroke: #06b6d4;
}
.status-pending .arc-fg {
  stroke: #64748b;
}
.arc-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.arc-pct {
  font-size: 18px;
  font-weight: 700;
  font-family: ui-monospace, monospace;
  color: #f1f5f9;
}
.pct-sym {
  font-size: 11px;
  color: #94a3b8;
  margin-left: 1px;
}
.arc-label {
  font-size: 10px;
  color: #94a3b8;
  margin-top: -2px;
}

.qg-verdict {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.verdict-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  width: fit-content;
}
.verdict-passed {
  background: #052e16;
  color: #4ade80;
}
.verdict-warning {
  background: #422006;
  color: #fbbf24;
}
.verdict-failed {
  background: #450a0a;
  color: #f87171;
}
.verdict-bypassed {
  background: #083344;
  color: #67e8f9;
}
.verdict-pending {
  background: #1e293b;
  color: #94a3b8;
}
.block-reason {
  font-size: 12px;
  color: #fca5a5;
  display: flex;
  align-items: flex-start;
  gap: 6px;
  line-height: 1.4;
}
.reason-icon {
  margin-top: 2px;
  flex-shrink: 0;
}
.override-line {
  font-size: 12px;
  color: #67e8f9;
}

/* ── category bars ── */
.qg-categories {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-top: 1px solid #1e293b;
  padding-top: 10px;
}
.cat-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cat-label {
  width: 96px;
  flex-shrink: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  color: #cbd5e1;
}
.cat-score {
  font-family: ui-monospace, monospace;
  font-weight: 600;
}
.score-passed { color: #4ade80; }
.score-warning { color: #fbbf24; }
.score-failed { color: #f87171; }
.score-pending { color: #94a3b8; }

.cat-bar {
  flex: 1;
  height: 8px;
  display: flex;
  gap: 2px;
  border-radius: 4px;
  overflow: hidden;
  background: #1e293b;
}
.cat-seg {
  height: 100%;
}
.seg-passed { background: #22c55e; }
.seg-warning { background: #f59e0b; }
.seg-failed { background: #ef4444; }
.seg-pending { background: #475569; }

/* ── grouped checks ── */
.qg-checks {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-top: 1px solid #1e293b;
  padding-top: 10px;
}
.cat-group {
  border-radius: 6px;
  background: #0b1220;
}
.cat-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  color: #e2e8f0;
}
.cat-summary::marker { content: ""; }
.summary-count {
  margin-left: auto;
  font-size: 11px;
  color: #64748b;
  font-family: ui-monospace, monospace;
}
.check-list {
  list-style: none;
  margin: 0;
  padding: 4px 12px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.check-row {
  display: grid;
  grid-template-columns: 18px 1fr auto 2fr;
  align-items: baseline;
  gap: 8px;
  font-size: 11.5px;
  padding: 4px 6px;
  border-radius: 4px;
  background: #0f172a;
}
.row-failed { border-left: 2px solid #ef4444; }
.row-warning { border-left: 2px solid #f59e0b; }
.row-passed { border-left: 2px solid #22c55e; }
.check-icon {
  text-align: center;
  font-weight: 700;
}
.row-passed .check-icon { color: #4ade80; }
.row-warning .check-icon { color: #fbbf24; }
.row-failed .check-icon { color: #f87171; }
.check-name {
  color: #cbd5e1;
  font-family: ui-monospace, monospace;
}
.check-score {
  color: #94a3b8;
  font-family: ui-monospace, monospace;
  font-size: 10.5px;
}
.check-msg {
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── suggestions ── */
.qg-suggestions {
  border-top: 1px solid #1e293b;
  padding-top: 10px;
}
.sg-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #67e8f9;
  margin-bottom: 4px;
}
.qg-suggestions ul {
  margin: 0;
  padding-left: 22px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.qg-suggestions li {
  font-size: 12px;
  color: #cbd5e1;
  line-height: 1.5;
}

/* ── actions ── */
.qg-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  border-top: 1px solid #1e293b;
  padding-top: 10px;
}
.action-hint {
  font-size: 11px;
  color: #64748b;
}

.qg-empty {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #64748b;
  font-style: italic;
}
</style>
