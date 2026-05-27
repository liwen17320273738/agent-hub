<template>
  <!--
    Per-stage quality-gate threshold editor.

    Three things this UI does that the URL-encoded form would not:

      1. *Diff awareness* — every slider has an "已修改" badge when its value
         differs from the effective default; this is the only way the user
         knows whether they're looking at the global default or a tweak.
      2. *Atomic save* — the dialog gathers everything into a single
         `overrides` object and PUTs it once, so a mid-edit close doesn't
         half-apply a change.
      3. *Required-sections / keywords* — these are arrays in the engine,
         but the drawer treats them as comma-separated strings to keep the
         UI flat (parsed back on save). Fewer clicks for the common case
         of "add 'API 设计' to the list".
  -->
  <el-drawer
    v-model="visible"
    :title="t('qualityGateConfigDrawer.title_1')"
    direction="rtl"
    size="42%"
    :before-close="handleClose"
  >
    <template #header>
      <div class="drawer-header">
        <h3>
          <el-icon><Setting /></el-icon>
          {{ $t('QualityGateConfigDrawer.title') }}
        </h3>
        <span v-if="hasUnsavedChanges" class="unsaved-tag">{{ t('qualityGateConfigDrawer.text_1') }}</span>
      </div>
    </template>

    <div v-if="loading" class="drawer-loading">
      <el-skeleton :rows="6" animated />
    </div>

    <div v-else-if="error" class="drawer-error">
      <el-alert :title="error" type="error" :closable="false" show-icon />
    </div>

    <div v-else class="drawer-body">
      <p class="drawer-hint" v-html="$t('QualityGateConfigDrawer.priorityHint')" />

      <el-collapse v-model="activeStages">
        <el-collapse-item
          v-for="stage in stages"
          :key="stage.stageId"
          :name="stage.stageId"
        >
          <template #title>
            <div class="stage-header-row">
              <span class="stage-id-pill">{{ stage.stageId }}</span>
              <span v-if="stageHasDirty(stage.stageId)" class="dirty-badge">{{ $t('QualityGateConfigDrawer.modified') }}</span>
              <span v-else-if="stage.hasOverrides" class="override-badge">{{ $t('QualityGateConfigDrawer.overridden') }}</span>
            </div>
          </template>

          <div class="threshold-block">
            <div class="threshold-row">
              <label>
                <span class="label-main">{{ $t('QualityGateConfigDrawer.passThreshold') }}</span>
                <span class="label-sub">{{ $t('QualityGateConfigDrawer.passThresholdSub') }}</span>
              </label>
              <div class="control-col">
                <el-slider
                  v-model="formState[stage.stageId].pass_threshold"
                  :min="0"
                  :max="1"
                  :step="0.05"
                  :format-tooltip="fmtPercent"
                />
                <span class="value-pill">{{ fmtPercent(formState[stage.stageId].pass_threshold) }}</span>
              </div>
            </div>

            <div class="threshold-row">
              <label>
                <span class="label-main">{{ $t('QualityGateConfigDrawer.failThreshold') }}</span>
                <span class="label-sub" v-html="$t('QualityGateConfigDrawer.failThresholdSub')" />
              </label>
              <div class="control-col">
                <el-slider
                  v-model="formState[stage.stageId].fail_threshold"
                  :min="0"
                  :max="1"
                  :step="0.05"
                  :format-tooltip="fmtPercent"
                />
                <span class="value-pill">{{ fmtPercent(formState[stage.stageId].fail_threshold) }}</span>
              </div>
            </div>

            <div class="threshold-row">
              <label>
                <span class="label-main">{{ $t('QualityGateConfigDrawer.minLength') }}</span>
                <span class="label-sub">{{ $t('QualityGateConfigDrawer.minLengthSub') }}</span>
              </label>
              <div class="control-col">
                <el-input-number
                  v-model="formState[stage.stageId].min_length"
                  :min="0"
                  :step="100"
                  size="small"
                />
              </div>
            </div>

            <div class="threshold-row vertical">
              <label>
                <span class="label-main">{{ $t('QualityGateConfigDrawer.requiredSections') }}</span>
                <span class="label-sub">{{ $t('QualityGateConfigDrawer.requiredSectionsSub') }}</span>
              </label>
              <el-input
                v-model="formState[stage.stageId].required_sections_text"
                :placeholder="$t('QualityGateConfigDrawer.requiredSectionsPlaceholder')"
                size="small"
              />
            </div>

            <div class="threshold-row vertical">
              <label>
                <span class="label-main">{{ $t('QualityGateConfigDrawer.requiredKeywords') }}</span>
                <span class="label-sub">{{ $t('QualityGateConfigDrawer.keywordModeLabel') }}: {{ formState[stage.stageId].keyword_mode === 'all' ? $t('QualityGateConfigDrawer.keywordModeAll') : $t('QualityGateConfigDrawer.keywordModeAny') }}</span>
              </label>
              <div class="kw-row">
                <el-input
                  v-model="formState[stage.stageId].required_keywords_text"
                  :placeholder="$t('QualityGateConfigDrawer.requiredKeywordsPlaceholder')"
                  size="small"
                  class="kw-input"
                />
                <el-radio-group
                  v-model="formState[stage.stageId].keyword_mode"
                  size="small"
                >
                  <el-radio-button value="all">{{ $t('QualityGateConfigDrawer.keywordAll') }}</el-radio-button>
                  <el-radio-button value="any">{{ $t('QualityGateConfigDrawer.keywordAny') }}</el-radio-button>
                </el-radio-group>
              </div>
            </div>

            <div class="threshold-row inline">
              <el-button
                size="small"
                text
                type="warning"
                :disabled="!stage.hasOverrides && !stageHasDirty(stage.stageId)"
                @click="resetStage(stage.stageId)"
               aria-label="action">
                <el-icon><RefreshLeft /></el-icon>
                {{ $t('QualityGateConfigDrawer.restoreDefault') }}
              </el-button>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>

    <template #footer>
      <div class="drawer-footer">
        <el-button @click="handleClose">{{ $t('QualityGateConfigDrawer.cancel') }}</el-button>
        <el-button
          type="primary"
          :loading="saving"
          :disabled="!hasUnsavedChanges"
          @click="handleSave"
        >
          {{ $t('QualityGateConfigDrawer.save') }}
        </el-button>
      </div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Setting, RefreshLeft } from '@element-plus/icons-vue'
import {
  fetchQualityGateConfig,
  updateQualityGateConfig,
  type StageGateConfig,
} from '@/services/pipelineApi'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps<{
  taskId: string
  modelValue: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', open: boolean): void
  (e: 'saved'): void
}>()

interface FormStage {
  pass_threshold: number
  fail_threshold: number
  min_length: number
  required_sections_text: string
  required_keywords_text: string
  keyword_mode: 'all' | 'any'
}

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const stages = ref<StageGateConfig[]>([])
const activeStages = ref<string[]>([])
// formState is a *flat working copy* keyed by stageId. We diff against
// `stages.value[i].effective` to compute "已修改" and the PUT payload.
const formState = reactive<Record<string, FormStage>>({})

function fmtPercent(n: number): string {
  return `${Math.round(n * 100)}%`
}

function csvOf(list: string[] | undefined): string {
  if (!list || !Array.isArray(list)) return ''
  return list.join(', ')
}
function parseCsv(s: string): string[] {
  return s
    .split(/[,，]/)
    .map((x) => x.trim())
    .filter((x) => x.length > 0)
}

function applyToFormState(s: StageGateConfig) {
  formState[s.stageId] = {
    pass_threshold: s.effective.passThreshold,
    fail_threshold: s.effective.failThreshold,
    min_length: s.effective.minLength,
    required_sections_text: csvOf(s.effective.requiredSections),
    required_keywords_text: csvOf(s.effective.requiredKeywords),
    keyword_mode: s.effective.keywordMode === 'any' ? 'any' : 'all',
  }
}

async function loadConfig() {
  loading.value = true
  error.value = ''
  try {
    const res = await fetchQualityGateConfig(props.taskId)
    stages.value = res.stages
    for (const s of res.stages) applyToFormState(s)
    // Auto-expand any stage that already has overrides — that's where the
    // user is most likely to want to look.
    activeStages.value = res.stages.filter((s) => s.hasOverrides).map((s) => s.stageId)
    if (activeStages.value.length === 0 && res.stages.length > 0) {
      activeStages.value = [res.stages[0].stageId]
    }
  } catch (e: unknown) {
    error.value = t('QualityGateConfigDrawer.loadFailed', { msg: e instanceof Error ? e.message : String(e) })
  } finally {
    loading.value = false
  }
}

watch(visible, (open) => {
  if (open) loadConfig()
})

// ── Diff vs. effective defaults ─────────────────────────────────────
function stageHasDirty(stageId: string): boolean {
  const orig = stages.value.find((s) => s.stageId === stageId)?.effective
  const cur = formState[stageId]
  if (!orig || !cur) return false
  return (
    cur.pass_threshold !== orig.passThreshold ||
    cur.fail_threshold !== orig.failThreshold ||
    cur.min_length !== orig.minLength ||
    cur.keyword_mode !== orig.keywordMode ||
    csvOf(orig.requiredSections) !== cur.required_sections_text ||
    csvOf(orig.requiredKeywords) !== cur.required_keywords_text
  )
}

const hasUnsavedChanges = computed(() => stages.value.some((s) => stageHasDirty(s.stageId)))

function resetStage(stageId: string) {
  const s = stages.value.find((x) => x.stageId === stageId)
  if (s) applyToFormState(s)
}

async function handleClose() {
  if (hasUnsavedChanges.value) {
    try {
      await ElMessageBox.confirm(t('QualityGateConfigDrawer.unsavedConfirm'), t('QualityGateConfigDrawer.unsavedTitle'), {
        type: 'warning',
        confirmButtonText: t('QualityGateConfigDrawer.unsavedClose'),
        cancelButtonText: t('QualityGateConfigDrawer.unsavedContinue'),
      })
    } catch {
      return
    }
  }
  visible.value = false
}

async function handleSave() {
  // Build the overrides payload: only stages with at least one diff vs.
  // effective, and only the keys that diverge — that way per-task overrides
  // stay minimal and a future template change still cascades through.
  const payload: Record<string, Record<string, unknown>> = {}
  for (const s of stages.value) {
    if (!stageHasDirty(s.stageId)) continue
    const cur = formState[s.stageId]
    const orig = s.effective
    const stagePatch: Record<string, unknown> = {}
    if (cur.pass_threshold !== orig.passThreshold) stagePatch.pass_threshold = cur.pass_threshold
    if (cur.fail_threshold !== orig.failThreshold) stagePatch.fail_threshold = cur.fail_threshold
    if (cur.min_length !== orig.minLength) stagePatch.min_length = cur.min_length
    if (cur.keyword_mode !== orig.keywordMode) stagePatch.keyword_mode = cur.keyword_mode
    const newSections = parseCsv(cur.required_sections_text)
    const newKeywords = parseCsv(cur.required_keywords_text)
    if (csvOf(orig.requiredSections) !== cur.required_sections_text) {
      stagePatch.required_sections = newSections
    }
    if (csvOf(orig.requiredKeywords) !== cur.required_keywords_text) {
      stagePatch.required_keywords = newKeywords
    }
    payload[s.stageId] = stagePatch
  }

  saving.value = true
  try {
    await updateQualityGateConfig(props.taskId, payload)
    ElMessage.success(t('qualityGateConfigDrawer.elMessage_1'))
    emit('saved')
    visible.value = false
  } catch (e: unknown) {
    ElMessage.error(t('QualityGateConfigDrawer.saveFailed', { msg: e instanceof Error ? e.message : String(e) }))
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.drawer-header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.drawer-header h3 {
  margin: 0;
  font-size: 16px;
  color: #f1f5f9;
  display: flex;
  align-items: center;
  gap: 8px;
}
.unsaved-tag {
  color: #fb923c;
  font-size: 12px;
}

.drawer-loading,
.drawer-error,
.drawer-body {
  padding: 16px 20px;
}

.drawer-hint {
  color: #94a3b8;
  font-size: 12px;
  margin: 0 0 12px;
}
.drawer-hint strong {
  color: #cbd5e1;
}

.stage-header-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  font-weight: 500;
}
.stage-id-pill {
  font-family: ui-monospace, SFMono-Regular, monospace;
  background: #1e293b;
  color: #cbd5e1;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 12px;
}
.dirty-badge {
  background: #fb923c;
  color: #0b1220;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
}
.override-badge {
  background: #0f172a;
  color: #38bdf8;
  border: 1px solid #1e3a5f;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
}

.threshold-block {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 8px 4px 4px;
}
.threshold-row {
  display: flex;
  align-items: center;
  gap: 16px;
}
.threshold-row.vertical {
  flex-direction: column;
  align-items: stretch;
  gap: 6px;
}
.threshold-row.inline {
  justify-content: flex-end;
  margin-top: -4px;
}
.threshold-row label {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex-shrink: 0;
  min-width: 110px;
}
.label-main {
  font-size: 12.5px;
  color: #e2e8f0;
}
.label-sub {
  font-size: 10.5px;
  color: #64748b;
}

.control-col {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}
.control-col :deep(.el-slider) {
  flex: 1;
  min-width: 0;
}
.value-pill {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  color: #38bdf8;
  background: #082f49;
  padding: 1px 8px;
  border-radius: 4px;
  min-width: 42px;
  text-align: center;
}

.kw-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.kw-input {
  flex: 1;
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
}
</style>
