<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addCase,
  createDataset,
  createRun,
  curateDataset,
  deleteCase,
  deleteDataset,
  getDataset,
  getRun,
  listDatasets,
  listRuns,
  updateCase,
  type CaseCreatePayload,
  type EvalCase,
  type EvalDataset,
  type EvalDatasetDetail,
  type EvalResult,
  type EvalRunDetail,
  type EvalRunSummary,
  type ScorerKind,
} from '@/services/evalApi'

const { t } = useI18n()

const datasets = ref<EvalDataset[]>([])
const runs = ref<EvalRunSummary[]>([])
const selectedDataset = ref<string>('')
const datasetDetail = ref<EvalDatasetDetail | null>(null)
const loading = ref(false)
const tab = ref<'cases' | 'runs' | 'compare'>('cases')

const filteredRuns = computed(() =>
  selectedDataset.value
    ? runs.value.filter((r) => r.dataset_id === selectedDataset.value)
    : runs.value,
)

async function refreshAll() {
  loading.value = true
  try {
    const [d, r] = await Promise.all([listDatasets(true), listRuns(undefined, 100)])
    datasets.value = d
    runs.value = r
    if (!selectedDataset.value && d.length > 0) {
      selectedDataset.value = d[0].id
    }
  } catch (e) {
    ElMessage.error(t('evalLab.el_prefix_load') + (e as Error).message)
  } finally {
    loading.value = false
  }
}

async function loadDatasetDetail(id: string) {
  if (!id) {
    datasetDetail.value = null
    return
  }
  try {
    datasetDetail.value = await getDataset(id)
  } catch (e) {
    ElMessage.error(t('evalLab.el_prefix_ds') + (e as Error).message)
  }
}

watch(selectedDataset, (id) => {
  loadDatasetDetail(id)
})

// ───── New dataset dialog ────────────────────────────────────────

const newDatasetOpen = ref(false)
const newDatasetForm = reactive({
  name: '',
  description: '',
  target_role: '',
  tags: '',
})
async function submitNewDataset() {
  if (!newDatasetForm.name.trim()) {
    ElMessage.warning(t('evalLab.elMessage_1'))
    return
  }
  try {
    const ds = await createDataset({
      name: newDatasetForm.name.trim(),
      description: newDatasetForm.description.trim(),
      target_role: newDatasetForm.target_role.trim(),
      tags: newDatasetForm.tags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
    })
    ElMessage.success(t('evalLab.elMessage_2'))
    newDatasetOpen.value = false
    Object.assign(newDatasetForm, { name: '', description: '', target_role: '', tags: '' })
    await refreshAll()
    selectedDataset.value = ds.id
  } catch (e) {
    ElMessage.error(t('evalLab.el_prefix_create') + (e as Error).message)
  }
}

async function removeDataset(ds: EvalDataset) {
  await ElMessageBox.confirm(
    t('evalLab.confirmDelDs', { name: ds.name }),
    t('evalLab.confirmTitle'),
    { type: 'warning' },
  )
  try {
    await deleteDataset(ds.id)
    if (selectedDataset.value === ds.id) selectedDataset.value = ''
    await refreshAll()
  } catch (e) {
    ElMessage.error(t('evalLab.el_prefix_delete') + (e as Error).message)
  }
}

// ───── New case dialog ───────────────────────────────────────────

const newCaseOpen = ref(false)
const newCaseForm = reactive<CaseCreatePayload & { expected_text: string; context_text: string }>({
  name: '',
  task: '',
  role: '',
  scorer: 'contains',
  expected: {},
  context: {},
  weight: 1.0,
  timeout_seconds: 120,
  expected_text: '',
  context_text: '{}',
})

const scorerHints = computed<Record<ScorerKind, string>>(() => ({
  contains: t('evalLab.hint_contains'),
  regex: t('evalLab.hint_regex'),
  exact: t('evalLab.hint_exact'),
  json_path: t('evalLab.hint_json_path'),
  llm_judge: t('evalLab.hint_llm_judge'),
}))

watch(
  () => newCaseForm.scorer,
  (s) => {
    newCaseForm.expected_text = scorerHints.value[s as ScorerKind] || '{}'
  },
  { immediate: true },
)

async function submitNewCase() {
  if (!selectedDataset.value) return
  if (!newCaseForm.task.trim()) {
    ElMessage.warning(t('evalLab.elMessage_3'))
    return
  }
  let expected: Record<string, unknown>
  let context: Record<string, unknown>
  try {
    expected = JSON.parse(newCaseForm.expected_text || '{}')
    context = JSON.parse(newCaseForm.context_text || '{}')
  } catch (e) {
    ElMessage.error(t('evalLab.el_prefix_json') + (e as Error).message)
    return
  }
  try {
    await addCase(selectedDataset.value, {
      name: newCaseForm.name?.trim() || '',
      task: newCaseForm.task.trim(),
      role: newCaseForm.role?.trim() || '',
      scorer: newCaseForm.scorer,
      expected,
      context,
      weight: newCaseForm.weight,
      timeout_seconds: newCaseForm.timeout_seconds,
    })
    ElMessage.success(t('evalLab.elMessage_4'))
    newCaseOpen.value = false
    Object.assign(newCaseForm, {
      name: '',
      task: '',
      role: '',
      weight: 1.0,
      timeout_seconds: 120,
      expected_text: scorerHints.value[newCaseForm.scorer as ScorerKind] || '{}',
      context_text: '{}',
    })
    await loadDatasetDetail(selectedDataset.value)
  } catch (e) {
    ElMessage.error(t('evalLab.el_prefix_save') + (e as Error).message)
  }
}

const curateOpen = ref(false)
const curateBusy = ref(false)
const curateForm = reactive({
  source: 'pipeline_tasks' as 'pipeline_tasks' | 'feedback',
  role: '',
  since_days: 14,
  limit: 20,
  min_quality_score: 0.7,
  scorer: 'llm_judge' as ScorerKind,
})

async function runCuration() {
  if (!selectedDataset.value) {
    ElMessage.warning(t('evalLab.elMessage_5'))
    return
  }
  curateBusy.value = true
  try {
    const r = await curateDataset(selectedDataset.value, {
      source: curateForm.source,
      role: curateForm.role.trim() || undefined,
      since_days: curateForm.since_days,
      limit: curateForm.limit,
      min_quality_score: curateForm.min_quality_score,
      scorer: curateForm.scorer,
    })
    ElMessage.success(
      t('evalLab.elMessage_curateOk', {
        n: r.appended,
        s: r.scanned ?? 0,
        k: r.skipped ?? 0,
      }),
    )
    curateOpen.value = false
    await loadDatasetDetail(selectedDataset.value)
  } catch (e) {
    ElMessage.error(t('evalLab.el_prefix_curate') + (e as Error).message)
  } finally {
    curateBusy.value = false
  }
}

async function toggleCaseEnabled(c: EvalCase) {
  try {
    await updateCase(c.id, { enabled: !c.enabled })
    await loadDatasetDetail(selectedDataset.value)
  } catch (e) {
    ElMessage.error(t('evalLab.el_prefix_update') + (e as Error).message)
  }
}

async function removeCase(c: EvalCase) {
  const name = c.name || c.task.slice(0, 30)
  await ElMessageBox.confirm(
    t('evalLab.confirmDelCase', { name }),
    t('evalLab.confirmTitle'),
    { type: 'warning' },
  )
  try {
    await deleteCase(c.id)
    await loadDatasetDetail(selectedDataset.value)
  } catch (e) {
    ElMessage.error(t('evalLab.el_prefix_delete') + (e as Error).message)
  }
}

// ───── Run scheduling + polling ──────────────────────────────────

const newRunOpen = ref(false)
const newRunForm = reactive({
  label: '',
  role_override: '',
  model_override: '',
})
const scheduling = ref(false)

async function submitNewRun() {
  if (!selectedDataset.value) return
  scheduling.value = true
  try {
    await createRun({
      dataset_id: selectedDataset.value,
      label: newRunForm.label.trim(),
      agent_role_override: newRunForm.role_override.trim(),
      model_override: newRunForm.model_override.trim(),
    })
    ElMessage.success(t('evalLab.elMessage_6'))
    newRunOpen.value = false
    Object.assign(newRunForm, { label: '', role_override: '', model_override: '' })
    await refreshAll()
  } catch (e) {
    ElMessage.error(t('evalLab.el_prefix_run') + (e as Error).message)
  } finally {
    scheduling.value = false
  }
}

let pollHandle: ReturnType<typeof setInterval> | null = null
function startPolling() {
  stopPolling()
  pollHandle = setInterval(async () => {
    const hasPending = filteredRuns.value.some(
      (r) => r.status === 'pending' || r.status === 'running',
    )
    if (!hasPending) return
    try {
      runs.value = await listRuns(undefined, 100)
    } catch {
      /* ignore */
    }
  }, 4000)
}
function stopPolling() {
  if (pollHandle) {
    clearInterval(pollHandle)
    pollHandle = null
  }
}

// ───── Run detail drawer ─────────────────────────────────────────

const detailOpen = ref(false)
const runDetail = ref<EvalRunDetail | null>(null)
const expandedResultId = ref<string>('')

async function openRunDetail(run: EvalRunSummary) {
  detailOpen.value = true
  runDetail.value = null
  try {
    runDetail.value = await getRun(run.id)
  } catch (e) {
    ElMessage.error(t('evalLab.el_prefix_detail') + (e as Error).message)
  }
}

function statusType(s: string) {
  switch (s) {
    case 'completed':
      return 'success'
    case 'failed':
    case 'aborted':
      return 'danger'
    case 'running':
      return 'warning'
    default:
      return 'info'
  }
}

function fmtPct(n: number) {
  return `${(n * 100).toFixed(1)}%`
}

// ───── A/B compare ───────────────────────────────────────────────

const compareLeft = ref<string>('')
const compareRight = ref<string>('')
const leftDetail = ref<EvalRunDetail | null>(null)
const rightDetail = ref<EvalRunDetail | null>(null)

async function loadCompare() {
  if (compareLeft.value) {
    try {
      leftDetail.value = await getRun(compareLeft.value)
    } catch (e) {
      ElMessage.error(t('evalLab.el_prefix_left') + (e as Error).message)
    }
  }
  if (compareRight.value) {
    try {
      rightDetail.value = await getRun(compareRight.value)
    } catch (e) {
      ElMessage.error(t('evalLab.el_prefix_right') + (e as Error).message)
    }
  }
}

interface CompareRow {
  case_name: string
  left?: EvalResult
  right?: EvalResult
  delta: number
}

const compareRows = computed<CompareRow[]>(() => {
  if (!leftDetail.value || !rightDetail.value) return []
  const map = new Map<string, CompareRow>()
  for (const r of leftDetail.value.results) {
    const key = r.case_name || r.case_id || r.id
    map.set(key, { case_name: key, left: r, delta: 0 })
  }
  for (const r of rightDetail.value.results) {
    const key = r.case_name || r.case_id || r.id
    const existing = map.get(key)
    if (existing) {
      existing.right = r
      existing.delta = r.score - (existing.left?.score ?? 0)
    } else {
      map.set(key, { case_name: key, right: r, delta: r.score })
    }
  }
  return Array.from(map.values()).sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
})

const compareSummary = computed(() => {
  if (!leftDetail.value || !rightDetail.value) return null
  const lAvg = leftDetail.value.avg_score
  const rAvg = rightDetail.value.avg_score
  return {
    leftAvg: lAvg,
    rightAvg: rAvg,
    delta: rAvg - lAvg,
    winner: rAvg > lAvg ? 'right' : rAvg < lAvg ? 'left' : 'tie',
  }
})

// ───── Trend (simple inline SVG sparkline) ────────────────────────

const trendData = computed(() => {
  const rs = filteredRuns.value.filter((r) => r.status === 'completed').slice(0, 30).reverse()
  return rs.map((r) => ({ id: r.id, label: r.label, score: r.avg_score }))
})

function trendPath(): string {
  const pts = trendData.value
  if (!pts.length) return ''
  const w = 320
  const h = 60
  const max = 1
  const stepX = pts.length > 1 ? w / (pts.length - 1) : 0
  return pts
    .map((p, i) => {
      const x = i * stepX
      const y = h - p.score * h
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
}

onMounted(async () => {
  await refreshAll()
  startPolling()
})
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="eval-page">
    <div class="page-header">
      <div>
        <h1>{{ t('evalLab.text_1') }}</h1>
        <p class="page-subtitle">{{ t('evalLab.text_subtitle') }}</p>
      </div>
      <div class="actions">
        <el-button :loading="loading" plain @click="refreshAll">{{ t('evalLab.text_2') }}</el-button>
        <el-button type="primary" @click="newDatasetOpen = true">{{ t('evalLab.text_3') }}</el-button>
      </div>
    </div>

    <div class="layout">
      <aside class="sidebar">
        <div class="section-title">{{ t('evalLab.sectionDatasets') }}</div>
        <div v-for="ds in datasets" :key="ds.id" class="ds-row" :class="{ active: ds.id === selectedDataset }">
          <div class="ds-main" @click="selectedDataset = ds.id">
            <div class="ds-name">{{ ds.name }}</div>
            <div class="ds-meta">
              <el-tag size="small" effect="plain">{{ ds.case_count }}{{ t('evalLab.suffix_cases') }}</el-tag>
              <el-tag v-if="ds.target_role" size="small" type="info" effect="plain">
                {{ ds.target_role }}
              </el-tag>
            </div>
          </div>
          <el-button text size="small" type="danger" @click.stop="removeDataset(ds)">{{ t('evalLab.text_4') }}</el-button>
        </div>
        <div v-if="!datasets.length" class="empty-side">{{ t('evalLab.text_5') }}</div>
      </aside>

      <section class="main">
        <div v-if="selectedDataset && datasetDetail" class="dataset-header card">
          <div>
            <div class="dataset-name">{{ datasetDetail.name }}</div>
            <div v-if="datasetDetail.description" class="dataset-desc">
              {{ datasetDetail.description }}
            </div>
            <div class="dataset-meta">
              <el-tag v-if="datasetDetail.target_role" size="small" type="info">
                {{ t('evalLab.targetRole') }}：{{ datasetDetail.target_role }}
              </el-tag>
              <el-tag
                v-for="tag in datasetDetail.tags"
                :key="tag"
                size="small"
                type="success"
                effect="plain"
              >
                #{{ tag }}
              </el-tag>
            </div>
          </div>
          <div class="header-actions">
            <el-button @click="newCaseOpen = true">{{ t('evalLab.text_6') }}</el-button>
            <el-button @click="curateOpen = true">{{ t('evalLab.text_7') }}</el-button>
            <el-button type="primary" @click="newRunOpen = true">{{ t('evalLab.text_8') }}</el-button>
          </div>
        </div>

        <div v-if="selectedDataset" class="tab-row">
          <el-radio-group v-model="tab" size="small">
            <el-radio-button label="cases" value="cases">{{ t('evalLab.tab_cases') }}</el-radio-button>
            <el-radio-button label="runs" value="runs">{{ t('evalLab.tab_runs') }}</el-radio-button>
            <el-radio-button label="compare" value="compare">{{ t('evalLab.text_9') }}</el-radio-button>
          </el-radio-group>
        </div>

        <!-- Cases tab -->
        <div v-if="tab === 'cases' && datasetDetail" class="card">
          <el-table :data="datasetDetail.cases" stripe>
            <el-table-column prop="name" :label="t('evalLab.label_1')" width="160" />
            <el-table-column :label="t('evalLab.label_2')">
              <template #default="{ row }">
                <div class="case-task">{{ row.task }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="role" :label="t('evalLab.col_role')" width="110" />
            <el-table-column prop="scorer" :label="t('evalLab.col_scorer')" width="110">
              <template #default="{ row }">
                <el-tag size="small" type="info">{{ row.scorer }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="weight" :label="t('evalLab.col_weight')" width="70" />
            <el-table-column :label="t('evalLab.col_enabled')" width="80">
              <template #default="{ row }">
                <el-switch :model-value="row.enabled" @change="toggleCaseEnabled(row)" />
              </template>
            </el-table-column>
            <el-table-column :label="t('evalLab.col_actions')" width="80">
              <template #default="{ row }">
                <el-button text size="small" type="danger" @click="removeCase(row)">
                  {{ t('evalLab.delete') }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="!datasetDetail.cases.length" class="empty-cases">{{ t('evalLab.noCases') }}</div>
        </div>

        <!-- Runs tab -->
        <div v-if="tab === 'runs'" class="card">
          <div class="trend-row">
            <div class="trend-title">{{ t('evalLab.trendTitle') }}</div>
            <svg width="320" height="60" class="trend-svg">
              <path :d="trendPath()" stroke="var(--el-color-primary, #409eff)" fill="none" stroke-width="2" />
              <line x1="0" :y1="60" x2="320" :y2="60" stroke="#ddd" />
            </svg>
          </div>
          <el-table :data="filteredRuns" stripe @row-click="openRunDetail">
            <el-table-column prop="label" :label="t('evalLab.col_label')" min-width="180">
              <template #default="{ row }">
                <div class="run-label">{{ row.label }}</div>
                <div class="run-meta-line">
                  <span v-if="row.model_override">{{ t('evalLab.modelPrefix') }}: {{ row.model_override }}</span>
                  <span v-if="row.agent_role_override">{{ t('evalLab.rolePrefix') }}: {{ row.agent_role_override }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column :label="t('evalLab.col_status')" width="100">
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('evalLab.col_result')" width="170">
              <template #default="{ row }">
                <span class="run-pass">{{ row.passed_cases }}</span>
                /
                <span class="run-fail">{{ row.failed_cases }}</span>
                /
                <span class="run-skip">{{ row.skipped_cases }}</span>
                <span class="run-total">/ {{ row.total_cases }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('evalLab.col_avg')" width="110">
              <template #default="{ row }">
                <strong>{{ fmtPct(row.avg_score) }}</strong>
              </template>
            </el-table-column>
            <el-table-column :label="t('evalLab.col_lat')" width="90">
              <template #default="{ row }">{{ Math.round(row.avg_latency_ms) }}ms</template>
            </el-table-column>
            <el-table-column :label="t('evalLab.col_start')" width="160">
              <template #default="{ row }">{{ row.started_at?.slice(0, 19).replace('T', ' ') }}</template>
            </el-table-column>
          </el-table>
          <div v-if="!filteredRuns.length" class="empty-cases">{{ t('evalLab.noRuns') }}</div>
        </div>

        <!-- Compare tab -->
        <div v-if="tab === 'compare'" class="card">
          <div class="compare-pickers">
            <div class="compare-pick">
              <span class="pick-label">A</span>
              <el-select v-model="compareLeft" :placeholder="t('evalLab.ph_runA')" style="width: 360px">
                <el-option
                  v-for="r in filteredRuns.filter((x) => x.status === 'completed')"
                  :key="r.id"
                  :label="`${r.label}  (${fmtPct(r.avg_score)})`"
                  :value="r.id"
                />
              </el-select>
            </div>
            <div class="compare-pick">
              <span class="pick-label">B</span>
              <el-select v-model="compareRight" :placeholder="t('evalLab.ph_runB')" style="width: 360px">
                <el-option
                  v-for="r in filteredRuns.filter((x) => x.status === 'completed')"
                  :key="r.id"
                  :label="`${r.label}  (${fmtPct(r.avg_score)})`"
                  :value="r.id"
                />
              </el-select>
            </div>
            <el-button type="primary" :disabled="!compareLeft || !compareRight" @click="loadCompare">
              {{ t('evalLab.btn_compare') }}
            </el-button>
          </div>

          <div v-if="compareSummary" class="compare-summary">
            <div class="summary-item">
              <div class="summary-label">{{ t('evalLab.label_avgA') }}</div>
              <div class="summary-value">{{ fmtPct(compareSummary.leftAvg) }}</div>
            </div>
            <div class="summary-item">
              <div class="summary-label">{{ t('evalLab.label_avgB') }}</div>
              <div class="summary-value">{{ fmtPct(compareSummary.rightAvg) }}</div>
            </div>
            <div class="summary-item delta">
              <div class="summary-label">{{ t('evalLab.label_delta') }}</div>
              <div
                class="summary-value"
                :class="{
                  positive: compareSummary.delta > 0,
                  negative: compareSummary.delta < 0,
                }"
              >
                {{ compareSummary.delta > 0 ? '+' : '' }}{{ fmtPct(compareSummary.delta) }}
              </div>
            </div>
            <div class="summary-item">
              <div class="summary-label">{{ t('evalLab.label_winner') }}</div>
              <div class="summary-value">
                <el-tag
                  :type="
                    compareSummary.winner === 'tie'
                      ? 'info'
                      : compareSummary.winner === 'right'
                        ? 'success'
                        : 'warning'
                  "
                >
                  {{
                    compareSummary.winner === 'tie'
                      ? t('evalLab.tie')
                      : compareSummary.winner === 'right'
                        ? 'B'
                        : 'A'
                  }}
                </el-tag>
              </div>
            </div>
          </div>

          <el-table v-if="compareRows.length" :data="compareRows" stripe>
            <el-table-column prop="case_name" :label="t('evalLab.col_case')" min-width="200" />
            <el-table-column :label="t('evalLab.col_scoreA')" width="110">
              <template #default="{ row }">
                <span v-if="row.left">{{ fmtPct(row.left.score) }}</span>
                <span v-else class="missing">{{ t('evalLab.missing') }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('evalLab.col_scoreB')" width="110">
              <template #default="{ row }">
                <span v-if="row.right">{{ fmtPct(row.right.score) }}</span>
                <span v-else class="missing">{{ t('evalLab.missing') }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('evalLab.col_delta')" width="120">
              <template #default="{ row }">
                <span :class="{ positive: row.delta > 0, negative: row.delta < 0 }">
                  {{ row.delta > 0 ? '+' : '' }}{{ fmtPct(row.delta) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column :label="t('evalLab.col_latA')" width="100">
              <template #default="{ row }">{{ row.left?.latency_ms ?? '-' }}ms</template>
            </el-table-column>
            <el-table-column :label="t('evalLab.col_latB')" width="100">
              <template #default="{ row }">{{ row.right?.latency_ms ?? '-' }}ms</template>
            </el-table-column>
          </el-table>
        </div>

        <div v-if="!selectedDataset" class="empty-main">
          <p>{{ t('evalLab.emptySidebar') }}</p>
        </div>
      </section>
    </div>

    <!-- New dataset dialog -->
    <el-dialog v-model="newDatasetOpen" :title="t('evalLab.dialog_newDs')" width="540px">
      <el-form label-width="100px">
        <el-form-item :label="t('evalLab.label_1')"><el-input v-model="newDatasetForm.name" /></el-form-item>
        <el-form-item :label="t('evalLab.label_desc')">
          <el-input v-model="newDatasetForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item :label="t('evalLab.label_targetRole')">
          <el-input v-model="newDatasetForm.target_role" :placeholder="t('evalLab.ph_role_dev')" />
        </el-form-item>
        <el-form-item :label="t('evalLab.label_tags')">
          <el-input v-model="newDatasetForm.tags" :placeholder="t('evalLab.ph_comma')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newDatasetOpen = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="submitNewDataset">{{ t('evalLab.btn_create') }}</el-button>
      </template>
    </el-dialog>

    <!-- Curate from traces dialog -->
    <el-dialog v-model="curateOpen" :title="t('evalLab.dialog_curate')" width="560px">
      <p class="curate-hint">{{ t('evalLab.curateHint') }}</p>
      <el-form label-width="120px" size="small">
        <el-form-item :label="t('evalLab.label_dataSource')">
          <el-radio-group v-model="curateForm.source">
            <el-radio-button label="pipeline_tasks">{{ t('evalLab.src_pipeline') }}</el-radio-button>
            <el-radio-button label="feedback">{{ t('evalLab.src_feedback') }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="t('evalLab.label_roleFilter')">
          <el-input v-model="curateForm.role" :placeholder="t('evalLab.ph_all_roles')" />
        </el-form-item>
        <el-form-item :label="t('evalLab.label_lastN')">
          <el-input-number v-model="curateForm.since_days" :min="1" :max="180" />
        </el-form-item>
        <el-form-item :label="t('evalLab.label_maxRows')">
          <el-input-number v-model="curateForm.limit" :min="1" :max="100" />
        </el-form-item>
        <el-form-item :label="t('evalLab.label_minQ')">
          <el-input-number v-model="curateForm.min_quality_score" :min="0" :max="1" :step="0.1" :precision="2" />
        </el-form-item>
        <el-form-item :label="t('evalLab.label_scorer')">
          <el-select v-model="curateForm.scorer" style="width: 200px">
            <el-option :label="t('evalLab.opt_llm_rec')" value="llm_judge" />
            <el-option :label="t('evalLab.opt_contains')" value="contains" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="curateOpen = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="runCuration" :loading="curateBusy">
          {{ t('evalLab.btn_startCurate') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- New case dialog -->
    <el-dialog v-model="newCaseOpen" :title="t('evalLab.dialog_newCase')" width="640px">
      <el-form label-width="100px">
        <el-form-item :label="t('evalLab.label_1')"><el-input v-model="newCaseForm.name" /></el-form-item>
        <el-form-item :label="t('evalLab.label_task')">
          <el-input v-model="newCaseForm.task" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item :label="t('evalLab.label_roleOv')">
          <el-input v-model="newCaseForm.role" :placeholder="t('evalLab.ph_target_role')" />
        </el-form-item>
        <el-form-item :label="t('evalLab.label_scorer')">
          <el-select v-model="newCaseForm.scorer" style="width: 200px">
            <el-option label="contains" value="contains" />
            <el-option label="regex" value="regex" />
            <el-option label="exact" value="exact" />
            <el-option label="json_path" value="json_path" />
            <el-option label="llm_judge" value="llm_judge" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('evalLab.label_expectedJson')">
          <el-input v-model="newCaseForm.expected_text" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item :label="t('evalLab.label_contextJson')">
          <el-input v-model="newCaseForm.context_text" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item :label="t('evalLab.label_weight')">
          <el-input-number v-model="newCaseForm.weight" :min="0.1" :step="0.1" :precision="1" />
        </el-form-item>
        <el-form-item :label="t('evalLab.label_timeout')">
          <el-input-number v-model="newCaseForm.timeout_seconds" :min="10" :step="10" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newCaseOpen = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="submitNewCase">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- New run dialog -->
    <el-dialog v-model="newRunOpen" :title="t('evalLab.dialog_newRun')" width="540px">
      <el-form label-width="100px">
        <el-form-item :label="t('evalLab.label_runLabel')">
          <el-input v-model="newRunForm.label" :placeholder="t('evalLab.ph_run_ex')" />
        </el-form-item>
        <el-form-item :label="t('evalLab.label_roleOv')">
          <el-input v-model="newRunForm.role_override" :placeholder="t('evalLab.ph_role_case')" />
        </el-form-item>
        <el-form-item :label="t('evalLab.label_modelOv')">
          <el-input v-model="newRunForm.model_override" :placeholder="t('evalLab.ph_model')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newRunOpen = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="scheduling" @click="submitNewRun">
          {{ t('evalLab.btn_schedule') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- Run detail drawer -->
    <el-drawer v-model="detailOpen" :title="t('evalLab.dialog_runDetail')" size="780px">
      <div v-if="!runDetail" class="loading-pane">{{ t('evalLab.loading') }}</div>
      <div v-else class="detail-body">
        <div class="detail-meta">
          <div><strong>{{ runDetail.label }}</strong></div>
          <el-tag :type="statusType(runDetail.status)" size="small">{{ runDetail.status }}</el-tag>
          <span class="meta-item">
            {{ t('evalLab.passSlash', { p: runDetail.passed_cases, tot: runDetail.total_cases }) }}
          </span>
          <span class="meta-item">avg {{ fmtPct(runDetail.avg_score) }}</span>
          <span class="meta-item">{{ Math.round(runDetail.avg_latency_ms) }}ms</span>
        </div>
        <div v-for="r in runDetail.results" :key="r.id" class="result-row">
          <div class="result-head" @click="expandedResultId = expandedResultId === r.id ? '' : r.id">
            <el-tag :type="r.passed ? 'success' : 'danger'" size="small" class="passed-tag">
              {{ r.passed ? 'PASS' : 'FAIL' }}
            </el-tag>
            <span class="result-name">{{ r.case_name || t('evalLab.unnamed') }}</span>
            <span class="result-score">{{ fmtPct(r.score) }}</span>
            <span class="result-latency">{{ r.latency_ms }}ms</span>
            <span class="result-scorer">{{ r.scorer }}</span>
          </div>
          <div v-if="expandedResultId === r.id" class="result-detail">
            <div v-if="r.error" class="result-error">⚠ {{ r.error }}</div>
            <div class="rd-section">
              <div class="rd-label">{{ t('evalLab.result_output') }}</div>
              <pre class="rd-pre">{{ r.output || t('evalLab.emptyOut') }}</pre>
            </div>
            <div class="rd-section">
              <div class="rd-label">{{ t('evalLab.result_scorer') }}</div>
              <pre class="rd-pre">{{ JSON.stringify(r.scorer_detail, null, 2) }}</pre>
            </div>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.eval-page {
  max-width: 1400px;
  margin: 0 auto;
  padding: 24px;
}
.curate-hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--text-muted, #999);
  line-height: 1.5;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 18px;
  gap: 20px;
}
.page-header h1 {
  margin: 0;
  font-size: 22px;
}
.page-subtitle {
  margin-top: 6px;
  color: var(--text-secondary, #606266);
  font-size: 13px;
  max-width: 700px;
}
.layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 18px;
}
.sidebar {
  background: var(--bg-secondary, #fafafa);
  border: 1px solid var(--border-color, #ebeef5);
  border-radius: 8px;
  padding: 14px;
  height: fit-content;
  position: sticky;
  top: 20px;
}
.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary, #909399);
  margin-bottom: 8px;
  text-transform: uppercase;
}
.ds-row {
  display: flex;
  align-items: center;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
  margin-bottom: 4px;
}
.ds-row:hover {
  background: var(--bg-tertiary, #f0f2f5);
}
.ds-row.active {
  background: var(--primary-bg, #ecf5ff);
  border-color: var(--el-color-primary, #409eff);
}
.ds-main {
  flex: 1;
}
.ds-name {
  font-size: 13px;
  font-weight: 500;
}
.ds-meta {
  display: flex;
  gap: 4px;
  margin-top: 4px;
  flex-wrap: wrap;
}
.empty-side {
  text-align: center;
  color: var(--text-secondary, #909399);
  padding: 30px 0;
  font-size: 12px;
}
.main {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}
.card {
  background: #fff;
  border: 1px solid var(--border-color, #ebeef5);
  border-radius: 10px;
  padding: 16px;
}
.dataset-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.dataset-name {
  font-size: 16px;
  font-weight: 600;
}
.dataset-desc {
  font-size: 13px;
  color: var(--text-secondary, #606266);
  margin-top: 4px;
}
.dataset-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.header-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.tab-row {
  display: flex;
  justify-content: flex-start;
}
.case-task {
  font-size: 12px;
  color: var(--text-primary, #303133);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 600px;
}
.empty-cases {
  text-align: center;
  padding: 30px;
  color: var(--text-secondary, #909399);
  font-size: 13px;
}
.empty-main {
  text-align: center;
  padding: 80px 0;
  color: var(--text-secondary, #909399);
}
.trend-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
  padding: 10px 12px;
  background: var(--bg-secondary, #fafafa);
  border-radius: 6px;
}
.trend-title {
  font-size: 12px;
  color: var(--text-secondary, #909399);
}
.run-label {
  font-weight: 500;
  font-size: 13px;
}
.run-meta-line {
  font-size: 11px;
  color: var(--text-secondary, #909399);
  margin-top: 2px;
  display: flex;
  gap: 10px;
}
.run-pass {
  color: var(--el-color-success, #67c23a);
  font-weight: 600;
}
.run-fail {
  color: var(--el-color-danger, #f56c6c);
  font-weight: 600;
}
.run-skip {
  color: var(--el-color-warning, #e6a23c);
}
.run-total {
  color: var(--text-secondary, #909399);
}
.compare-pickers {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.compare-pick {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pick-label {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--el-color-primary, #409eff);
  color: white;
  text-align: center;
  font-size: 11px;
  line-height: 18px;
  font-weight: 600;
}
.compare-pick:nth-child(2) .pick-label {
  background: var(--el-color-success, #67c23a);
}
.compare-summary {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
  padding: 14px;
  background: var(--bg-secondary, #fafafa);
  border-radius: 8px;
}
.summary-item {
  text-align: center;
}
.summary-label {
  font-size: 11px;
  color: var(--text-secondary, #909399);
}
.summary-value {
  font-size: 18px;
  font-weight: 600;
  margin-top: 4px;
}
.summary-value.positive {
  color: var(--el-color-success, #67c23a);
}
.summary-value.negative {
  color: var(--el-color-danger, #f56c6c);
}
.positive {
  color: var(--el-color-success, #67c23a);
  font-weight: 600;
}
.negative {
  color: var(--el-color-danger, #f56c6c);
  font-weight: 600;
}
.missing {
  color: var(--text-secondary, #909399);
  font-size: 11px;
}
.detail-body {
  padding: 0 16px;
}
.detail-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.meta-item {
  font-size: 12px;
  color: var(--text-secondary, #606266);
}
.result-row {
  border: 1px solid var(--border-color, #ebeef5);
  border-radius: 6px;
  margin-bottom: 6px;
}
.result-head {
  display: grid;
  grid-template-columns: auto 1fr auto auto auto;
  gap: 10px;
  align-items: center;
  padding: 10px 12px;
  cursor: pointer;
}
.result-head:hover {
  background: var(--bg-secondary, #fafafa);
}
.passed-tag {
  font-family: ui-monospace, SFMono-Regular, monospace;
}
.result-name {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.result-score {
  font-weight: 600;
  font-size: 13px;
  width: 50px;
  text-align: right;
}
.result-latency {
  font-size: 11px;
  color: var(--text-secondary, #909399);
  width: 60px;
  text-align: right;
}
.result-scorer {
  font-size: 11px;
  color: var(--text-secondary, #909399);
  width: 80px;
  text-align: right;
  font-family: ui-monospace, SFMono-Regular, monospace;
}
.result-detail {
  padding: 10px 14px;
  border-top: 1px dashed var(--border-color, #ebeef5);
  background: var(--bg-secondary, #fafafa);
}
.result-error {
  color: var(--el-color-danger, #f56c6c);
  margin-bottom: 8px;
  font-size: 12px;
}
.rd-section + .rd-section {
  margin-top: 10px;
}
.rd-label {
  font-size: 11px;
  color: var(--text-secondary, #909399);
  margin-bottom: 4px;
  text-transform: uppercase;
}
.rd-pre {
  margin: 0;
  padding: 10px;
  background: white;
  border: 1px solid var(--border-color, #ebeef5);
  border-radius: 4px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow: auto;
}
.actions {
  display: flex;
  gap: 8px;
}
.loading-pane {
  text-align: center;
  padding: 60px;
  color: var(--text-secondary, #909399);
}
.trend-svg {
  display: block;
}
</style>
