<template>
  <!--
    Right-side drawer that edits a single BuilderNode's `data`.

    Uses ``v-model`` two-way binding on each Element Plus control so
    parent state (Vue Flow's nodes array) updates in real time. The
    parent is responsible for re-running topology validation after
    every change — the drawer doesn't know about the rest of the graph.

    Why no save button? The builder is "live" — every keystroke
    persists to localStorage via the parent's debounced watcher. A
    "Save" button would imply revertable drafts, which we don't
    have yet. If we add undo/redo, we'll add a button then.
  -->
  <el-drawer
    v-model="visibleProxy"
    :title="`${$t('StageConfigDrawer.configStage')} · ${data?.label || data?.stageId || ''}`"
    direction="rtl"
    size="380px"
    :destroy-on-close="false"
    :before-close="handleClose"
  >
    <div v-if="data" class="cfg-form">
      <el-form label-position="top" size="default">
        <el-form-item :label="t('stageConfigDrawer.label_1')">
          <el-input
            v-model="data.stageId"
            placeholder="development"
            clearable
            @input="onStageIdInput"
          >
            <template #append>
              <el-tooltip :content="`${$t('StageConfigDrawer.stableId')}；${$t('StageConfigDrawer.lowercaseEnglish')}，${$t('StageConfigDrawer.alphanumeric')}`">
                <el-icon><InfoFilled /></el-icon>
              </el-tooltip>
            </template>
          </el-input>
          <div v-if="stageIdError" class="hint hint-error">{{ stageIdError }}</div>
          <div v-else class="hint">{{ $t('StageConfigDrawer.stageIdHint') }}</div>
        </el-form-item>

        <el-form-item :label="$t('StageConfigDrawer.label')">
          <el-input v-model="data.label" :placeholder="$t('StageConfigDrawer.labelPlaceholder')" clearable />
        </el-form-item>

        <el-form-item :label="$t('StageConfigDrawer.agentRole')">
          <el-select v-model="data.role" :placeholder="$t('StageConfigDrawer.selectRole')" style="width: 100%">
            <el-option
              v-for="r in KNOWN_ROLES"
              :key="r.value"
              :label="`${r.emoji}  ${r.label}（${r.value}）`"
              :value="r.value"
            />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">{{ $t('StageConfigDrawer.advanced') }}</el-divider>

        <el-form-item :label="$t('StageConfigDrawer.modelOverride')">
          <el-input
            v-model="modelInput"
            :placeholder="$t('StageConfigDrawer.modelOverridePlaceholder')"
            clearable
            @blur="commitModel"
            @keyup.enter="commitModel"
          />
          <div class="hint">{{ $t('StageConfigDrawer.modelOverrideHint') }}</div>
        </el-form-item>

        <el-form-item :label="$t('StageConfigDrawer.qualityThreshold')">
          <el-slider
            :model-value="(data.qualityGateMin ?? 0) * 100"
            :min="0"
            :max="100"
            :step="5"
            :format-tooltip="(v: number) => v === 0 ? $t('StageConfigDrawer.qualityOff') : `${v}%`"
            @input="(v: number) => (data.qualityGateMin = v === 0 ? undefined : v / 100)"
          />
          <div class="hint">{{ $t('StageConfigDrawer.qualityHint') }}</div>
        </el-form-item>

        <el-form-item :label="$t('StageConfigDrawer.rejectAction')">
          <el-radio-group v-model="rejectActionProxy" size="small">
            <el-radio-button value="self-heal">{{ $t('StageConfigDrawer.rejectSelfHeal') }}</el-radio-button>
            <el-radio-button value="escalate">{{ $t('StageConfigDrawer.rejectEscalate') }}</el-radio-button>
            <el-radio-button value="manual">{{ $t('StageConfigDrawer.rejectManual') }}</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item :label="$t('StageConfigDrawer.failureStrategy')">
          <el-radio-group v-model="onFailureProxy" size="small">
            <el-radio-button value="halt">{{ $t('StageConfigDrawer.failureHalt') }}</el-radio-button>
            <el-radio-button value="rollback">{{ $t('StageConfigDrawer.failureRollback') }}</el-radio-button>
            <el-radio-button value="skip">{{ $t('StageConfigDrawer.failureSkip') }}</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item>
          <el-checkbox v-model="data.humanGate">
            {{ $t('StageConfigDrawer.humanGate') }}
          </el-checkbox>
        </el-form-item>
      </el-form>

      <el-divider content-position="left">{{ $t('StageConfigDrawer.dependencies') }}</el-divider>
      <div class="deps-block">
        <div v-if="dependsOn.length === 0" class="hint">
          {{ $t('StageConfigDrawer.noDeps') }}
        </div>
        <div v-else class="dep-list">
          <el-tag
            v-for="d in dependsOn"
            :key="d"
            type="info"
            effect="dark"
            size="default"
          >
            {{ d }}
          </el-tag>
        </div>
      </div>

      <div class="footer-actions">
        <el-button type="danger" plain size="small" @click="emit('delete', nodeId)">
          <el-icon><Delete /></el-icon>
          {{ $t('StageConfigDrawer.deleteStage') }}
        </el-button>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Delete, InfoFilled } from '@element-plus/icons-vue'
import { KNOWN_ROLES } from '@/services/workflowBuilder'
import type { BuilderNode } from '@/services/workflowBuilder'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps<{
  visible: boolean
  nodeId: string | null
  data: BuilderNode['data'] | null
  /** Stage ids upstream of this node, derived in the parent. */
  dependsOn: string[]
  /** Other nodes' stage ids — for dup detection. */
  otherStageIds: string[]
}>()

const emit = defineEmits<{
  (e: 'update:visible', v: boolean): void
  (e: 'delete', id: string): void
}>()

const visibleProxy = computed({
  get: () => props.visible,
  set: (v) => emit('update:visible', v),
})

// Local model field — committed on blur to avoid re-rendering the
// canvas on every keystroke. Empty string ⇒ unset (back to router).
const modelInput = ref('')
watch(
  () => props.data?.model,
  (v) => {
    modelInput.value = v || ''
  },
  { immediate: true },
)
function commitModel() {
  if (!props.data) return
  props.data.model = modelInput.value.trim() || null
}

const rejectActionProxy = computed({
  get: () => props.data?.rejectAction || 'self-heal',
  set: (v) => {
    if (props.data) props.data.rejectAction = v as 'self-heal' | 'escalate' | 'manual'
  },
})

const onFailureProxy = computed({
  get: () => props.data?.onFailure || 'halt',
  set: (v) => {
    if (props.data) props.data.onFailure = v as 'halt' | 'rollback' | 'skip'
  },
})

// Stage-id validation: lowercase / digits / dashes only, and must
// not collide with a sibling's stage id. We surface the message
// inline; the parent decides whether to refuse the save based on
// `builderToStages` returning duplicate-stage-id.
const STAGE_ID_RE = /^[a-z][a-z0-9-]{0,40}$/
const stageIdError = computed(() => {
  const id = props.data?.stageId || ''
  if (!id) return t('StageConfigDrawer.stageIdEmpty')
  if (!STAGE_ID_RE.test(id)) return t('StageConfigDrawer.stageIdInvalid')
  if (props.otherStageIds.includes(id)) return t('StageConfigDrawer.stageIdDuplicate', { id })
  return ''
})

function onStageIdInput(v: string) {
  if (props.data) props.data.stageId = v.toLowerCase().replace(/\s+/g, '-')
}

function handleClose(done: () => void) {
  // We don't actually block close even when stageIdError is set —
  // the parent's "Run" / "Export" guards will still refuse to ship
  // a broken graph. Easier UX: let people close, fix later.
  done()
}
</script>

<style scoped>
.cfg-form {
  padding: 4px 6px 80px 6px;
}
.hint {
  margin-top: 4px;
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.4;
}
.hint-error {
  color: #ef4444;
  font-weight: 500;
}
.deps-block {
  margin-top: 4px;
}
.dep-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.footer-actions {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
}
</style>
