<!-- eslint-disable vue/max-attributes-per-line, vue/singleline-html-element-content-newline -->
<template>
  <el-card shadow="never" class="contract-panel" :class="{ compact }">
    <template #header>
      <div class="contract-header">
        <div class="contract-title-row">
          <span class="contract-title">{{ t('artifactContract.title') }}</span>
          <el-tag v-if="data" :type="allOkTag" size="small" effect="dark">
            {{ allOkLabel }}
          </el-tag>
          <span v-if="data && enforceOff" class="enforce-hint">
            {{ t('artifactContract.enforceOff') }}
          </span>
        </div>
        <el-button size="small" text :loading="loading" @click="load">
          <el-icon><Refresh /></el-icon>
          {{ t('artifactContract.refresh') }}
        </el-button>
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
      <el-collapse accordion class="stage-collapse">
        <el-collapse-item v-for="sid in stageOrder" :key="sid" :name="sid">
          <template #title>
            <span class="collapse-title">
              {{ stageTitle(sid) }}
              <el-tag
                size="small"
                :type="stageBlock(sid)?.ok ? 'success' : 'danger'"
                effect="plain"
                class="stage-ok-tag"
              >
                {{ stageBlock(sid)?.ok ? t('artifactContract.stageOk') : t('artifactContract.stageGap') }}
              </el-tag>
            </span>
          </template>

          <div v-if="stageBlock(sid)?.missing?.length" class="missing-row">
            <span class="muted">{{ t('artifactContract.missingRequired') }}</span>
            <el-tag
              v-for="m in stageBlock(sid).missing"
              :key="m"
              type="danger"
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
  artifact_details: Record<string, ArtifactDetailRow>
}

const props = withDefaults(
  defineProps<{
    taskId?: string
    shareToken?: string
    compact?: boolean
  }>(),
  {
    taskId: undefined,
    shareToken: undefined,
    compact: false,
  },
)

const { t, locale } = useI18n()

const loading = ref(false)
const error = ref('')
const data = ref<Record<string, unknown> | null>(null)

const stageOrder = [
  'planning',
  'design',
  'architecture',
  'development',
  'testing',
  'reviewing',
  'deployment',
] as const

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

const allOkTag = computed(() => (data.value?.all_required_satisfied ? 'success' : 'warning'))

const allOkLabel = computed(() =>
  data.value?.all_required_satisfied
    ? t('artifactContract.allSatisfied')
    : t('artifactContract.hasGaps'),
)

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
.contract-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
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
  font-size: 11px;
}
</style>
