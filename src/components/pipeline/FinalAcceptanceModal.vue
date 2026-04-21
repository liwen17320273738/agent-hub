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
            <el-icon><Check /></el-icon> 接受交付
          </span>
        </template>
        <div class="tab-body">
          <p class="tab-hint">
            确认整个交付链已满足业务需求。任务将进入 <code>done</code> 终态，
            <strong>无法再继续修改</strong>（除非新建一个续作任务）。
          </p>
          <el-form label-position="top">
            <el-form-item label="可选备注（会写入审计日志）">
              <el-input
                v-model="acceptNotes"
                type="textarea"
                :rows="3"
                placeholder="例：客户验收通过，已部署到 staging。"
                maxlength="2000"
                show-word-limit
              />
            </el-form-item>
          </el-form>
          <div class="tab-actions">
            <el-button @click="visible = false">取消</el-button>
            <el-button type="success" :loading="submitting" @click="handleAccept">
              <el-icon><Check /></el-icon>
              确认接受
            </el-button>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane name="reject">
        <template #label>
          <span class="tab-label tab-reject">
            <el-icon><Close /></el-icon> 打回重做
          </span>
        </template>
        <div class="tab-body">
          <p class="tab-hint">
            说明问题在哪、希望从哪一步开始重做。<strong>选了重做阶段</strong>，
            后端会自动重置该阶段及之后所有阶段为 pending 并重新跑 DAG；
            <strong>不选</strong>则只暂停任务，由你后续决定。
          </p>
          <el-form label-position="top">
            <el-form-item label="打回原因（必填，会注入到重做的 prompt 里）">
              <el-input
                v-model="rejectReason"
                type="textarea"
                :rows="4"
                placeholder="例：API 设计文档缺少错误码列表，必须按 RFC 7807 风格枚举所有 4xx/5xx。"
                maxlength="4000"
                show-word-limit
              />
            </el-form-item>
            <el-form-item label="从哪个阶段重做（可选）">
              <el-select
                v-model="rejectStage"
                placeholder="（不重做，仅暂停）"
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
                选中后，该阶段及其下游全部重置为 pending，DAG 会立刻续跑。
              </span>
            </el-form-item>
          </el-form>
          <div class="tab-actions">
            <el-button @click="visible = false">取消</el-button>
            <el-button
              type="warning"
              :loading="submitting"
              :disabled="!rejectReason.trim()"
              @click="handleReject"
            >
              <el-icon><Close /></el-icon>
              {{ rejectStage ? `打回并从「${rejectStageLabel}」重做` : '打回并暂停' }}
            </el-button>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Close } from '@element-plus/icons-vue'
import { finalAcceptTask, finalRejectTask } from '@/services/pipelineApi'
import type { PipelineTask } from '@/agents/types'

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
const title = computed(() => `最终验收 · ${props.task.title}`)

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
    ElMessage.success('已确认验收，任务进入 done')
    emit('accepted')
    visible.value = false
  } catch (e: unknown) {
    ElMessage.error(`验收失败: ${e instanceof Error ? e.message : String(e)}`)
  } finally {
    submitting.value = false
  }
}

async function handleReject() {
  if (!rejectReason.value.trim()) {
    ElMessage.warning('请填写打回原因')
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
      ElMessage.success(res.message || `已打回并将从 ${res.restartFromStage} 重新运行`)
    } else if (res.paused) {
      ElMessage.warning(res.message || '已打回，任务已暂停')
    } else {
      ElMessage.success('已打回')
    }
    emit('rejected', res.restartFromStage || null)
    visible.value = false
  } catch (e: unknown) {
    ElMessage.error(`打回失败: ${e instanceof Error ? e.message : String(e)}`)
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
