<template>
  <div class="task-table">
    <el-table
      :data="tasks"
      stripe
      size="small"
      style="width: 100%"
      :row-class-name="rowClass"
      @row-click="(row: any) => emit('clickTask', row)"
    >
      <el-table-column prop="title" :label="t('taskTable.task')" min-width="260" show-overflow-tooltip>
        <template #default="{ row }">
          <div class="cell-title">
            <span class="title-text"><AutoTranslated :text="row.title" /></span>
            <span v-if="row.source" class="source-pill">{{ sourceLabel(row.source) }}</span>
          </div>
        </template>
      </el-table-column>

      <el-table-column :label="t('taskTable.status')" width="100">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small" effect="light">
            {{ statusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column :label="t('taskTable.stage')" width="140">
        <template #default="{ row }">
          <span class="stage-cell" :title="row.currentStageId">
            {{ stageLabel(row) }}
          </span>
        </template>
      </el-table-column>

      <el-table-column :label="t('taskTable.progress')" width="120">
        <template #default="{ row }">
          <div class="progress-cell" :title="`${doneCount(row)}/${row.stages?.length || 0}`">
            <div class="progress-bar">
              <div class="progress-bar-fill" :style="{ width: progressPct(row) + '%' }"></div>
            </div>
            <span class="progress-text">{{ progressPct(row) }}%</span>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="Cost" width="80">
        <template #default="{ row }">
          <span v-if="row.budgetInfo?.spent_usd != null" class="cost-cell" :class="costClass(row)">
            ${{ row.budgetInfo.spent_usd.toFixed(4) }}
          </span>
          <span v-else class="cost-cell cost-na">-</span>
        </template>
      </el-table-column>

      <el-table-column :label="t('taskTable.updated')" width="130">
        <template #default="{ row }">
          <span :class="['fresh', freshnessClass(row)]" :title="absDate(row.updatedAt || row.createdAt)">
            {{ relativeTime(row.updatedAt || row.createdAt) }}
          </span>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!tasks.length" :description="emptyText" />
  </div>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { onMounted, onUnmounted, ref as vueRef } from 'vue'
import type { PipelineTask } from '@/agents/types'
import AutoTranslated from '@/components/AutoTranslated.vue'
import { appLocaleToBcp47 } from '@/i18n'

const { t, te, locale } = useI18n()

defineProps<{
  tasks: PipelineTask[]
  emptyText?: string
}>()

// Force relative time labels to refresh every 30s so "刚刚" doesn't stay forever
const timeTick = vueRef(0)
let timeTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => { timeTimer = setInterval(() => { timeTick.value++ }, 30_000) })
onUnmounted(() => { if (timeTimer) clearInterval(timeTimer) })

const emit = defineEmits<{ clickTask: [task: PipelineTask] }>()

function statusType(s: string) {
  if (s === 'done' || s === 'accepted') return 'success'
  if (s === 'failed' || s === 'rejected') return 'danger'
  if (s === 'cancelled') return 'info'
  if (s === 'plan_pending' || s === 'awaiting_final_acceptance' || s === 'awaiting_evidence') return 'warning'
  return 'primary'
}

// Use te() before t() so unknown dynamic values (e.g. arbitrary `source`
// strings coming from gateway/test scripts) don't spam the console with
// intlify "Not found …" warnings, but still render as the raw value.
function statusLabel(s: string) {
  const key = `status.${s}`
  return te(key) ? t(key) : s
}

function sourceLabel(s: string) {
  const key = `taskTable.source.${s}`
  return te(key) ? t(key) : s
}

function stageLabel(row: any): string {
  const stages = row.stages || []
  const cur = stages.find((st: any) => st.id === row.currentStageId)
  return cur?.label || row.currentStageId || '-'
}

function doneCount(row: any): number {
  const stages = row.stages || []
  return stages.filter((s: any) => s.status === 'done').length
}

// Progress must agree with task.status. A task whose lifecycle finished
// (done/accepted) is 100% even if no `pipeline_stages` rows were written
// (seed scripts, gateway tasks that wrote artifacts directly, etc.).
// Conversely, a `failed`/`cancelled` task should reflect how far it got,
// not be forced to 100%.
function progressPct(row: any): number {
  const s = row.status
  if (s === 'done' || s === 'accepted') return 100
  const total = row.stages?.length || 0
  if (!total) return 0
  return Math.round((doneCount(row) / total) * 100)
}

// 后端返回的 UTC 时间可能不带时区标识（naive datetime），
// JS 会将其当作本地时间解析，导致显示偏移 8 小时。
// 此函数确保无时区字符串被当作 UTC 解析。
function toUtcDate(ts: number | string): Date {
  if (typeof ts === 'number') return new Date(ts)
  const s = String(ts).trim()
  // 已有时区信息（Z 结尾或含 +HH:MM / -HH:MM）→ 直接解析
  if (/[+-]\d{2}:\d{2}$/.test(s) || s.endsWith('Z')) return new Date(s)
  // 无时区 → 假定 UTC
  return new Date(s + 'Z')
}

// Absolute time on hover, relative on screen — reading "5min ago" is faster
// than reading "12-08 14:23" when triaging an inbox.
function absDate(ts: number | string | null | undefined): string {
  if (!ts) return '-'
  const d = toUtcDate(ts)
  if (isNaN(d.getTime())) return '-'
  return d.toLocaleString(appLocaleToBcp47(locale.value), { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function relativeTime(ts: number | string | null | undefined): string {
  void timeTick.value // re-evaluate every 30s
  if (!ts) return '-'
  const d = toUtcDate(ts)
  const ms = Date.now() - d.getTime()
  if (isNaN(ms)) return '-'
  if (ms < 60_000) return t('taskTable.justNow')
  if (ms < 3_600_000) return t('taskTable.minutesAgo', { n: Math.floor(ms / 60_000) })
  if (ms < 86_400_000) return t('taskTable.hoursAgo', { n: Math.floor(ms / 3_600_000) })
  if (ms < 7 * 86_400_000) return t('taskTable.daysAgo', { n: Math.floor(ms / 86_400_000) })
  return d.toLocaleDateString(appLocaleToBcp47(locale.value), { month: '2-digit', day: '2-digit' })
}

// Visual freshness so stale "执行中" tasks (probably stuck) jump out.
function freshnessClass(row: any): string {
  void timeTick.value // re-evaluate every 30s
  const ts = row.updatedAt || row.createdAt
  if (!ts) return ''
  const ms = Date.now() - toUtcDate(ts).getTime()
  if (ms < 5 * 60_000) return 'fresh-hot'
  if (ms < 60 * 60_000) return 'fresh-warm'
  if (ms < 24 * 60 * 60_000) return 'fresh-cool'
  return 'fresh-stale'
}

function costClass(row: any): string {
  const info = row.budgetInfo
  if (!info) return ''
  const ratio = info.spent_usd / (info.budget_usd || 1)
  if (ratio >= 1) return 'cost-over'
  if (ratio >= 0.6) return 'cost-warn'
  return ''
}

function rowClass({ row }: { row: any }) {
  if (row.status === 'failed' || row.status === 'rejected') return 'row-danger'
  if (row.status === 'cancelled') return 'row-cancelled'
  if (row.status === 'plan_pending' || row.status === 'awaiting_final_acceptance') return 'row-pending'
  return ''
}
</script>

<style scoped>
.task-table {
  min-height: 200px;
}

.el-table {
  cursor: pointer;
  --el-table-border-color: var(--border-color);
  --el-table-header-bg-color: var(--bg-tertiary);
  --el-table-row-hover-bg-color: var(--bg-hover);
  --el-table-tr-bg-color: var(--bg-secondary);
}

:deep(.el-table th.el-table__cell) {
  background: var(--bg-tertiary);
  font-weight: 700;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border-color);
}

:deep(.el-table .el-table__row) {
  transition: background 0.15s;
}

:deep(.el-table__body tr:hover > td) {
  background: var(--accent-soft) !important;
}

.cell-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.title-text {
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.source-pill {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--accent-soft);
  color: var(--accent);
}

.stage-cell {
  font-size: 12px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
  max-width: 100%;
}

.progress-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.progress-bar {
  flex: 1;
  height: 6px;
  background: var(--border-color);
  border-radius: 3px;
  overflow: hidden;
}
.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
  border-radius: 3px;
  transition: width 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}
.progress-text {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  min-width: 32px;
  text-align: right;
}

.fresh {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.fresh-hot   { color: var(--red); font-weight: 700; }
.fresh-warm  { color: var(--amber); font-weight: 600; }
.fresh-cool  { color: var(--text-secondary); }
.fresh-stale { color: var(--text-muted); }

.cost-cell {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
}
.cost-na { color: var(--text-muted); }
.cost-warn { color: var(--amber); font-weight: 600; }
.cost-over { color: var(--red); font-weight: 700; }

:deep(.row-danger)  { background-color: rgba(248, 113, 113, 0.04); }
:deep(.row-pending) { background-color: rgba(251, 191, 36, 0.04); }
:deep(.row-cancelled) { background-color: rgba(96, 96, 120, 0.06); }
</style>
