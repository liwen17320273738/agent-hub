<template>
  <!--
    Terminal "最终验收" modal.

    Two flows behind one modal so the operator only ever sees one entry
    point on the dashboard:

      1. Accept — optional notes, transitions task → done.
      2. Reject — required reason, optional "restart from stage X". Picking
         a stage triggers a *re-run* of that stage and everything
         downstream of it (the backend handles the cascade); leaving it
         empty just pauses the task and lets the operator decide later.

    Picker semantics: only stages that actually ran get listed. We exclude
    "done" sentinel stage_ids ("done", "final_acceptance") because they're
    not real work units.
  -->
  <el-dialog
    v-model="visible"
    :title="title"
    :width="dialogWidth"
    :close-on-click-modal="false"
    @closed="onClosed"
  >
    <el-tabs v-model="mode" stretch>
      <el-tab-pane name="accept">
        <template #label>
          <span class="tab-label tab-accept">
            <el-icon><Check /></el-icon> {{ t('finalAccept.tabAccept') }}
          </span>
        </template>
        <div class="tab-body">
          <p class="tab-hint" v-html="t('finalAccept.acceptHint')"></p>
          <el-form label-position="top">
            <el-form-item :label="t('finalAccept.notesLabel')">
              <el-input
                v-model="acceptNotes"
                type="textarea"
                :rows="3"
                :placeholder="t('finalAccept.notesPlaceholder')"
                maxlength="2000"
                show-word-limit
              />
            </el-form-item>
          </el-form>
          <div class="tab-actions">
            <el-button @click="visible = false">{{ t('common.cancel') }}</el-button>
            <el-button type="success" :loading="submitting" @click="handleAccept">
              <el-icon><Check /></el-icon>
              {{ t('finalAccept.confirmAccept') }}
            </el-button>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane name="reject">
        <template #label>
          <span class="tab-label tab-reject">
            <el-icon><Close /></el-icon> {{ t('finalAccept.tabReject') }}
          </span>
        </template>
        <div class="tab-body">
          <p class="tab-hint" v-html="t('finalAccept.rejectHint')"></p>
          <el-form label-position="top">
            <el-form-item :label="t('finalAccept.reasonLabel')">
              <el-input
                v-model="rejectReason"
                type="textarea"
                :rows="4"
                :placeholder="t('finalAccept.reasonPlaceholder')"
                maxlength="4000"
                show-word-limit
              />
            </el-form-item>
            <el-form-item :label="t('finalAccept.restartStageLabel')">
              <el-select
                v-model="rejectStage"
                :placeholder="t('finalAccept.restartStagePlaceholder')"
                clearable
                style="width: 100%"
              >
                <el-option
                  v-for="s in restartableStages"
                  :key="s.id"
                  :label="`${s.label} (${s.id})`"
                  :value="s.id"
                />
              </el-select>
              <span class="form-foot-hint">
                {{ t('finalAccept.restartStageHint') }}
              </span>
            </el-form-item>
          </el-form>
          <div class="tab-actions">
            <el-button @click="visible = false">{{ t('common.cancel') }}</el-button>
            <el-button
              type="warning"
              :loading="submitting"
              :disabled="!rejectReason.trim()"
              @click="handleReject"
            >
              <el-icon><Close /></el-icon>
              {{ rejectStage ? t('finalAccept.rejectAndRestart', { stage: rejectStageLabel }) : t('finalAccept.rejectAndPause') }}
            </el-button>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Check, Close } from '@element-plus/icons-vue'
import { finalAcceptTask, finalRejectTask } from '@/services/pipelineApi'
import type { PipelineTask } from '@/agents/types'

const { t } = useI18n()

const props = defineProps<{
  task: PipelineTask
  modelValue: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', open: boolean): void
  (e: 'accepted'): void
  (e: 'rejected', restartFromStage: string | null): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const mode = ref<'accept' | 'reject'>('accept')
const acceptNotes = ref('')
const rejectReason = ref('')
const rejectStage = ref('')
const submitting = ref(false)

const dialogWidth = ref('520px')
const title = computed(() => `${t('finalAccept.title')} · ${props.task.title}`)

const SENTINEL_STAGE_IDS = new Set(['done', 'final_acceptance'])
const restartableStages = computed(() =>
  props.task.stages.filter((s) => !SENTINEL_STAGE_IDS.has(s.id)),
)
const rejectStageLabel = computed(() => {
  const found = restartableStages.value.find((s) => s.id === rejectStage.value)
  return found?.label || rejectStage.value
})

watch(visible, (open) => {
  if (open) {
    mode.value = 'accept'
    acceptNotes.value = ''
    rejectReason.value = ''
    rejectStage.value = ''
  }
})

function onClosed() {
  // Defensive cleanup — covers the case where the user dismisses with ESC
  // before watch(visible) fires its `false` branch.
  acceptNotes.value = ''
  rejectReason.value = ''
  rejectStage.value = ''
  submitting.value = false
}

async function handleAccept() {
  submitting.value = true
  try {
    await finalAcceptTask(props.task.id, acceptNotes.value || undefined)
    ElMessage.success(t('finalAccept.toastAccepted'))
    emit('accepted')
    visible.value = false
  } catch (e: unknown) {
    ElMessage.error(`${t('finalAccept.toastAcceptFail')}: ${e instanceof Error ? e.message : String(e)}`)
  } finally {
    submitting.value = false
  }
}

async function handleReject() {
  if (!rejectReason.value.trim()) {
    ElMessage.warning(t('finalAccept.reasonRequired'))
    return
  }
  submitting.value = true
  try {
    const res = await finalRejectTask(
      props.task.id,
      rejectReason.value,
      rejectStage.value || undefined,
    )
    if (res.queued) {
      ElMessage.success(res.message || t('finalAccept.toastRestart', { stage: res.restartFromStage }))
    } else if (res.paused) {
      ElMessage.warning(res.message || t('finalAccept.toastPaused'))
    } else {
      ElMessage.success(t('finalAccept.toastRejected'))
    }
    emit('rejected', res.restartFromStage || null)
    visible.value = false
  } catch (e: unknown) {
    ElMessage.error(`${t('finalAccept.toastRejectFail')}: ${e instanceof Error ? e.message : String(e)}`)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
}
.tab-accept {
  color: #22c55e;
}
.tab-reject {
  color: #f59e0b;
}
.tab-body {
  padding: 12px 4px 0;
}
.tab-hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--text-secondary, #94a3b8);
  line-height: 1.5;
}
.tab-hint code {
  background: rgba(148, 163, 184, 0.18);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 11px;
}
.tab-hint strong {
  color: var(--text-primary, #e2e8f0);
}
.form-foot-hint {
  font-size: 11px;
  color: var(--text-muted, #64748b);
  display: block;
  margin-top: 4px;
}
.tab-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border-color, #1e293b);
  margin-top: 12px;
}
</style>
