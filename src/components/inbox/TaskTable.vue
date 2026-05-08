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
import type { PipelineTask } from '@/agents/types'
import AutoTranslated from '@/components/AutoTranslated.vue'
import { appLocaleToBcp47 } from '@/i18n'

const { t, locale } = useI18n()

defineProps<{
  tasks: PipelineTask[]
  emptyText?: string
}>()

const emit = defineEmits<{ clickTask: [task: PipelineTask] }>()

function statusType(s: string) {
  if (s === 'done' || s === 'accepted') return 'success'
  if (s === 'failed' || s === 'rejected') return 'danger'
  if (s === 'cancelled') return 'info'
  if (s === 'plan_pending' || s === 'awaiting_final_acceptance') return 'warning'
  return 'primary'
}

function statusLabel(s: string) {
  const key = `status.${s}`
  const out = t(key)
  return out === key ? s : out
}

function sourceLabel(s: string) {
  const key = `taskTable.source.${s}`
  const out = t(key)
  return out === key ? s : out
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

function progressPct(row: any): number {
  const total = row.stages?.length || 0
  if (!total) return 0
  return Math.round((doneCount(row) / total) * 100)
}

// Absolute time on hover, relative on screen — reading "5min ago" is faster
// than reading "12-08 14:23" when triaging an inbox.
function absDate(ts: number | string | null | undefined): string {
  if (!ts) return '-'
  const d = typeof ts === 'number' ? new Date(ts) : new Date(ts)
  if (isNaN(d.getTime())) return '-'
  return d.toLocaleString(appLocaleToBcp47(locale.value), { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function relativeTime(ts: number | string | null | undefined): string {
  if (!ts) return '-'
  const d = typeof ts === 'number' ? new Date(ts) : new Date(ts)
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
  const ts = row.updatedAt || row.createdAt
  if (!ts) return ''
  const ms = Date.now() - new Date(ts).getTime()
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
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--el-fill-color);
  color: var(--el-text-color-secondary);
}

.stage-cell {
  font-size: 12px;
  color: var(--el-text-color-regular);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
  max-width: 100%;
}

.progress-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
.progress-bar {
  flex: 1;
  height: 6px;
  background: var(--el-fill-color);
  border-radius: 3px;
  overflow: hidden;
}
.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #6366f1, #3b82f6);
  border-radius: 3px;
  transition: width 0.3s;
}
.progress-text {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
  min-width: 32px;
  text-align: right;
}

.fresh {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.fresh-hot   { color: #f56c6c; font-weight: 600; }
.fresh-warm  { color: #e6a23c; }
.fresh-cool  { color: var(--el-text-color-regular); }
.fresh-stale { color: var(--el-text-color-secondary); }

.cost-cell {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: var(--el-text-color-regular);
}
.cost-na { color: var(--el-text-color-placeholder); }
.cost-warn { color: #e6a23c; font-weight: 600; }
.cost-over { color: #f56c6c; font-weight: 700; }

:deep(.row-danger)  { background-color: rgba(245, 108, 108, 0.04); }
:deep(.row-pending) { background-color: rgba(230, 162, 60, 0.04); }
:deep(.row-cancelled) { background-color: rgba(144, 147, 153, 0.06); }
</style>
