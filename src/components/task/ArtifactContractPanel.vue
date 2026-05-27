<!-- eslint-disable vue/max-attributes-per-line, vue/singleline-html-element-content-newline -->
<template>
  <el-card shadow="never" class="contract-panel" :class="{ compact, terminal: isTerminal }">
    <template #header>
      <div class="contract-header">
        <div class="contract-title-row">
          <span class="contract-title">{{ t('artifactContract.title') }}</span>
          <el-tag v-if="data" :type="headerTagType" size="small" :effect="headerTagEffect">
            {{ headerTagLabel }}
          </el-tag>
          <span v-if="data && enforceOff" class="enforce-hint">
            {{ t('artifactContract.enforceOff') }}
          </span>
        </div>
        <div class="header-actions">
          <el-button
            v-if="isTerminal && data"
            size="small"
            text
            @click="userExpanded = !userExpanded"
          >
            {{ shouldShowDetails
              ? t('artifactContract.collapseDetails')
              : t('artifactContract.expandDetails') }}
          </el-button>
          <el-button size="small" text :loading="loading" @click="load" aria-label="action">
            <el-icon><Refresh /></el-icon>
            {{ t('artifactContract.refresh') }}
          </el-button>
        </div>
      </div>
      <p v-if="data?.schema_version" class="schema-meta">
        schema {{ data.schema_version }}
        <span v-if="!data.artifact_store_v2" class="warn"> · v2 off</span>
      </p>
    </template>

    <div v-if="loading" class="contract-loading">
      <el-icon class="is-loading" :size="20">
        <Loading />
      </el-icon>
      <span>{{ t('artifactContract.loading') }}</span>
    </div>

    <el-alert v-else-if="error" type="warning" :title="error" :closable="false" show-icon />

    <template v-else-if="data">
      <!-- Terminal summary line: when the task is closed and the user hasn't asked
           for details, just show a single neutral sentence so the contract panel
           doesn't drown out the actual delivery view below. -->
      <div v-if="isTerminal && !shouldShowDetails" class="terminal-summary">
        {{ terminalSummaryText }}
      </div>

      <el-collapse v-else accordion class="stage-collapse">
        <el-collapse-item v-for="sid in stageOrder" :key="sid" :name="sid">
          <template #title>
            <span class="collapse-title">
              {{ stageTitle(sid) }}
              <el-tag
                size="small"
                :type="stageTagType(sid)"
                effect="plain"
                class="stage-ok-tag"
              >
                {{ stageTagText(sid) }}
              </el-tag>
            </span>
          </template>

          <div v-if="stageBlock(sid)?.missing?.length" class="missing-row">
            <span class="muted">{{ missingLabelText }}</span>
            <el-tag
              v-for="m in stageBlock(sid).missing"
              :key="m"
              :type="missingTagType"
              size="small"
              effect="plain"
            >
              {{ m }}
            </el-tag>
          </div>

          <div v-if="stageBlock(sid)?.invalid?.length" class="missing-row">
            <span class="muted">{{ t('artifactContract.invalidRequired') }}</span>
            <el-tag
              v-for="m in stageBlock(sid).invalid"
              :key="m"
              type="warning"
              size="small"
              effect="plain"
            >
              {{ m }}
            </el-tag>
          </div>

          <div class="artifact-grid">
            <div
              v-for="{ atype, detail } in artifactRows(sid)"
              :key="atype"
              class="artifact-row"
            >
              <div class="artifact-row-head">
                <code class="atype">{{ atype }}</code>
                <el-tag v-if="detail.required" size="small" type="info" effect="plain">req</el-tag>
                <el-tag size="small" :type="detail.present ? 'success' : 'info'" effect="plain">
                  {{
                    detail.present ? t('artifactContract.present') : t('artifactContract.absent')
                  }}
                </el-tag>
                <el-tag
                  v-if="detail.present && detail.validation_errors?.length"
                  size="small"
                  type="warning"
                  effect="plain"
                >
                  {{ t('artifactContract.qualityGap') }}
                </el-tag>
                <span v-if="detail.version != null" class="ver">v{{ detail.version }}</span>
              </div>
              <p v-if="definitionBlurb(detail.definition)" class="def-blurb">
                {{ definitionBlurb(detail.definition) }}
              </p>
              <div v-if="detail.validation_errors?.length" class="val-errs">
                <el-alert
                  v-for="(ve, i) in detail.validation_errors"
                  :key="i"
                  type="warning"
                  :closable="false"
                  show-icon
                  class="val-alert"
                >
                  {{ formatValidationError(String(ve)) }}
                </el-alert>
              </div>
              <div v-if="detail.definition?.producing_stages?.length" class="meta-line muted">
                {{ t('artifactContract.producers') }}:
                {{ detail.definition.producing_stages.join(', ') }}
              </div>
              <div v-if="detail.definition?.consuming_stages?.length" class="meta-line muted">
                {{ t('artifactContract.consumers') }}:
                {{ detail.definition.consuming_stages.join(', ') }}
              </div>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </template>
  </el-card>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Loading, Refresh } from '@element-plus/icons-vue'
import { fetchShareArtifactContract, fetchTaskArtifactContract } from '@/services/pipelineApi'

interface ArtifactDetailRow {
  required: boolean
  present: boolean
  version: number | null
  validation_errors: string[]
  definition: {
    producing_stages?: string[]
    consuming_stages?: string[]
    description_zh?: string
    description_en?: string
  }
}

interface StageContractBlock {
  ok: boolean
  missing: string[]
  invalid?: string[]
  artifact_details: Record<string, ArtifactDetailRow>
}

const props = withDefaults(
  defineProps<{
    taskId?: string
    shareToken?: string
    compact?: boolean
    /**
     * Current task lifecycle status — controls whether the panel screams
     * "MISSING / DEFECTIVE" (in-flight, gaps are action items) or speaks
     * neutrally about partial delivery (terminal, the work is over).
     * Optional so unrelated callers / tests keep the old loud behavior.
     */
    taskStatus?: string
  }>(),
  {
    taskId: undefined,
    shareToken: undefined,
    compact: false,
    taskStatus: undefined,
  },
)

const { t, locale } = useI18n()

const loading = ref(false)
const error = ref('')
const data = ref<Record<string, unknown> | null>(null)
/**
 * User explicitly toggled the details visibility. Null = use the
 * lifecycle-driven default (terminal+clean → collapsed, otherwise expanded).
 */
const userExpanded = ref<boolean | null>(null)

const stageOrder = [
  'planning',
  'design',
  'architecture',
  'development',
  'testing',
  'reviewing',
  'deployment',
] as const

// ── Lifecycle awareness ─────────────────────────────────────────────────
// Terminal = task is closed and the user can no longer do anything about
// gaps. We use this to soften the language and default to a one-line
// summary so a finished demo task doesn't look like it failed.
const TERMINAL_STATUSES = new Set([
  'done', 'accepted', 'cancelled', 'canceled', 'failed', 'error', 'rejected',
])
const isTerminal = computed(() => {
  const s = (props.taskStatus || '').toLowerCase()
  return TERMINAL_STATUSES.has(s)
})

function hasAnyQualityIssue(): boolean {
  const st = data.value?.stages as Record<string, StageContractBlock> | undefined
  if (!st) return false
  return Object.values(st).some((b) => Array.isArray(b?.invalid) && b.invalid.length > 0)
}

const shouldShowDetails = computed(() => {
  if (userExpanded.value !== null) return userExpanded.value
  if (!isTerminal.value) return true
  // Terminal: only auto-expand when there are quality issues worth surfacing.
  return hasAnyQualityIssue()
})

function stageTitle(sid: string): string {
  const k = `artifactContract.stage_${sid}` as const
  const tr = t(k)
  return tr === k ? sid : tr
}

function stageBlock(sid: string): StageContractBlock | null {
  const st = data.value?.stages as Record<string, unknown> | undefined
  if (!st || typeof st !== 'object') return null
  const raw = st[sid]
  if (!raw || typeof raw !== 'object') return null
  return raw as unknown as StageContractBlock
}

function stageTagType(sid: string): 'success' | 'warning' | 'info' | 'danger' {
  const block = stageBlock(sid)
  if (!block) return isTerminal.value ? 'info' : 'danger'
  if (block.ok) return 'success'
  if (!block.missing?.length && block.invalid?.length) return 'warning'
  // Pure missing (no quality issues): demote red→gray once the task is closed,
  // because "didn't deliver" is informational at that point, not blocking.
  return isTerminal.value ? 'info' : 'danger'
}

function stageTagText(sid: string): string {
  const block = stageBlock(sid)
  if (!block) {
    return isTerminal.value
      ? t('artifactContract.stageNotInScope')
      : t('artifactContract.stageGap')
  }
  if (block.ok) {
    return isTerminal.value
      ? t('artifactContract.stageDelivered')
      : t('artifactContract.stageOk')
  }
  if (!block.missing?.length && block.invalid?.length) {
    return t('artifactContract.stageQualityIssue')
  }
  return isTerminal.value
    ? t('artifactContract.stageNotInScope')
    : t('artifactContract.stageGap')
}

function artifactRows(
  sid: string,
): Array<{ atype: string; detail: ArtifactDetailRow }> {
  const block = stageBlock(sid)
  if (!block?.artifact_details) return []
  return Object.entries(block.artifact_details).map(([atype, detail]) => ({
    atype,
    detail: detail as ArtifactDetailRow,
  }))
}

// ── Header tag (top-right of card title) ────────────────────────────────
// In-flight  : success/warning  ("已齐备" / "仍有缺口") — keeps action urgency
// Terminal   : success/info     ("完整交付" / "局部交付") — neutral framing
//   (only the rare case of has quality issues stays warning, since those
//    are real fixable defects regardless of lifecycle)
const headerTagType = computed<'success' | 'warning' | 'info'>(() => {
  const allOk = Boolean(data.value?.all_required_satisfied)
  if (allOk) return 'success'
  if (isTerminal.value) return hasAnyQualityIssue() ? 'warning' : 'info'
  return 'warning'
})

const headerTagEffect = computed<'dark' | 'plain'>(() =>
  isTerminal.value && !hasAnyQualityIssue() ? 'plain' : 'dark',
)

const headerTagLabel = computed<string>(() => {
  const allOk = Boolean(data.value?.all_required_satisfied)
  if (isTerminal.value) {
    if (allOk) return t('artifactContract.fullDelivery')
    return t('artifactContract.partialDelivery')
  }
  return allOk
    ? t('artifactContract.allSatisfied')
    : t('artifactContract.hasGaps')
})

// Inside-card per-stage missing list: use neutral language for terminal tasks
const missingLabelText = computed(() =>
  isTerminal.value
    ? t('artifactContract.notDeliveredTypes')
    : t('artifactContract.missingRequired'),
)
const missingTagType = computed<'info' | 'danger'>(() =>
  isTerminal.value ? 'info' : 'danger',
)

// ── Terminal one-liner summary ──────────────────────────────────────────
const terminalSummaryText = computed<string>(() => {
  const st = (data.value?.stages || {}) as Record<string, StageContractBlock>
  const sids = stageOrder
  const total = sids.length
  let done = 0
  let quality = 0
  for (const sid of sids) {
    const block = st[sid]
    if (block?.ok) done += 1
    if (Array.isArray(block?.invalid) && block.invalid.length > 0) quality += 1
  }
  const missing = total - done - quality
  if (done === total) {
    return t('artifactContract.terminalSummaryFull', { n: total })
  }
  if (quality > 0) {
    return t('artifactContract.terminalSummaryWithQuality', {
      done, total, quality,
    })
  }
  return t('artifactContract.terminalSummaryPartial', {
    done, total, missing,
  })
})

const enforceOff = computed(
  () =>
    Boolean(
      data.value && (!data.value.enforce || !data.value.artifact_store_v2),
    ),
)

function definitionBlurb(
  def: ArtifactDetailRow['definition'] | undefined,
): string {
  if (!def) return ''
  const zh = String(def.description_zh || '')
  const en = String(def.description_en || '')
  if (locale.value.toLowerCase().startsWith('zh')) return zh || en
  return en || zh
}

function formatValidationError(code: string): string {
  if (code.startsWith('min_chars')) {
    const n = code.split(':')[1] || '?'
    return t('artifactContract.errMinChars', { n })
  }
  if (code === 'json_invalid') return t('artifactContract.errJsonInvalid')
  if (code === 'json_not_object') return t('artifactContract.errJsonNotObject')
  if (code.startsWith('markdown_sections')) return t('artifactContract.errMarkdownSections')
  if (code === 'mock_content') return t('artifactContract.errMockContent')
  if (code === 'requires_visual_asset') return t('artifactContract.errRequiresVisualAsset')
  if (code === 'requires_diagram') return t('artifactContract.errRequiresDiagram')
  if (code === 'mock_deploy_url') return t('artifactContract.errMockDeployUrl')
  if (code === 'mock_deploy_health') return t('artifactContract.errMockDeployHealth')
  return code
}

async function load(): Promise<void> {
  if (!props.taskId && !props.shareToken) return
  loading.value = true
  error.value = ''
  try {
    if (props.shareToken) {
      data.value = (await fetchShareArtifactContract(props.shareToken)) as Record<
        string,
        unknown
      >
    } else if (props.taskId) {
      data.value = (await fetchTaskArtifactContract(props.taskId)) as Record<
        string,
        unknown
      >
    }
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
    data.value = null
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.taskId, props.shareToken] as const,
  () => {
    void load()
  },
  { immediate: true },
)

defineExpose({ reload: load })
</script>

<style scoped>
.contract-panel {
  margin-bottom: 16px;
  border-radius: 10px;
}
.contract-panel.compact {
  margin-bottom: 12px;
}
.contract-panel.compact :deep(.el-card__body) {
  padding: 10px 12px;
}
/* Terminal-state cards shouldn't draw the eye away from the actual delivery
   view below — keep them readable but visually quiet. */
.contract-panel.terminal {
  border-color: var(--el-border-color-lighter);
  background: var(--el-fill-color-blank);
}
.contract-panel.terminal :deep(.el-card__body) {
  padding: 8px 12px;
}
.terminal-summary {
  font-size: 13px;
  color: var(--el-text-color-regular);
  padding: 4px 2px;
  line-height: 1.6;
}
.contract-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}
.contract-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.contract-title {
  font-weight: 600;
  font-size: 15px;
}
.enforce-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.schema-meta {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.schema-meta .warn {
  color: var(--el-color-warning);
}
.contract-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--el-text-color-secondary);
  padding: 8px 0;
}
.stage-collapse {
  border: none;
  --el-collapse-header-bg-color: transparent;
}
.collapse-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}
.stage-ok-tag {
  margin-left: 4px;
}
.missing-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin-bottom: 10px;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.artifact-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.artifact-row {
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--el-fill-color-light, #f5f7fa);
}
.artifact-row-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.atype {
  font-size: 13px;
  font-weight: 600;
}
.ver {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.def-blurb {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--el-text-color-regular);
  line-height: 1.45;
}
.val-errs {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.val-alert {
  padding: 6px 10px;
}
.meta-line {
  margin-top: 4px;
  font-size: 12px;
}
</style>
