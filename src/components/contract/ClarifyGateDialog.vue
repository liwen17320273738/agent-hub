<template>
  <el-dialog
    v-model="visible"
    :title="title"
    width="720px"
    top="5vh"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
    class="clarify-dialog"
  >
    <!-- Step indicator -->
    <div class="clarify-steps">
      <div
        v-for="(step, i) in steps"
        :key="i"
        class="clarify-step"
        :class="{ active: currentStep === i, done: currentStep > i }"
      >
        <el-icon v-if="currentStep > i"><Select /></el-icon>
        <el-icon v-else><MoreFilled /></el-icon>
        <span>{{ step.label }}</span>
      </div>
    </div>

    <!-- ── Step 0: Clarify business goal ── -->
    <div v-if="currentStep === 0" class="clarify-body">
      <p class="clarify-desc">{{ t('contract.clarifyStep0Desc') }}</p>
      <el-input
        v-model="draftGoal"
        type="textarea"
        :rows="4"
        :placeholder="t('contract.goalPlaceholder')"
      />
      <div class="clarify-actions">
        <el-button @click="onCancel">{{ t('contract.skip') }}</el-button>
        <el-button type="primary" @click="currentStep = 1" :disabled="!draftGoal.trim()">
          {{ t('contract.next') }}
        </el-button>
      </div>
    </div>

    <!-- ── Step 1: Review metrics ── -->
    <div v-if="currentStep === 1" class="clarify-body">
      <p class="clarify-desc">{{ t('contract.clarifyStep1Desc') }}</p>
      <div class="metric-list">
        <div v-for="(m, i) in draftMetrics" :key="i" class="metric-item">
          <div class="metric-row">
            <el-input
              v-model="m.name"
              :placeholder="t('contract.metricNamePlaceholder')"
              size="small"
              style="width: 180px"
            />
            <el-select v-model="m.direction" size="small" style="width: 120px">
              <el-option :label="t('contract.directionIncrease')" value="increase" />
              <el-option :label="t('contract.directionDecrease')" value="decrease" />
              <el-option :label="t('contract.directionReach')" value="reach" />
            </el-select>
            <el-input-number
              v-model="m.target_value"
              :min="0"
              size="small"
              style="width: 120px"
              :placeholder="t('contract.targetPlaceholder')"
            />
            <el-input
              v-model="m.source"
              size="small"
              style="width: 120px"
              :placeholder="t('contract.sourcePlaceholder')"
            />
            <el-button
              size="small"
              type="danger"
              :icon="Delete"
              circle
              @click="draftMetrics.splice(i, 1)"
            />
          </div>
          <div class="metric-row" v-if="m.name && draftGoal">
            <span class="metric-suggestion">
              {{ t('contract.suggestion') }}: {{ m.direction === 'increase' ? '≥' : m.direction === 'decrease' ? '≤' : '=' }}{{ m.target_value }}
              {{ t('contract.withinDays') }}
              <el-input-number v-model="m.measurement_window_days" :min="7" :max="365" size="small" style="width: 80px" />
              {{ t('contract.days') }}
            </span>
          </div>
        </div>
      </div>
      <el-button size="small" @click="addMetric" class="add-metric-btn">
        + {{ t('contract.addMetric') }}
      </el-button>
      <div class="clarify-actions">
        <el-button @click="currentStep = 0">{{ t('contract.back') }}</el-button>
        <el-button type="primary" @click="currentStep = 2" :disabled="!hasValidMetrics">
          {{ t('contract.next') }}
        </el-button>
      </div>
    </div>

    <!-- ── Step 2: Sign & execute ── -->
    <div v-if="currentStep === 2" class="clarify-body">
      <p class="clarify-desc">{{ t('contract.clarifyStep2Desc') }}</p>
      <div class="contract-summary">
        <div class="summary-section">
          <h4>{{ t('contract.businessGoal') }}</h4>
          <p>{{ draftGoal }}</p>
        </div>
        <div class="summary-section">
          <h4>{{ t('contract.metrics') }} ({{ draftMetrics.length }})</h4>
          <ul>
            <li v-for="(m, idx) in draftMetrics" :key="`${m.name}-${idx}`">
              <strong>{{ m.name || t('contract.unnamedMetric') }}</strong>:
              {{ formatMetricSymbol(m.direction) }}{{ m.target_value }}
              ({{ formatMetricSource(m.source) }}, {{ m.measurement_window_days || 30 }}{{ t('contract.days') }})
            </li>
          </ul>
        </div>
        <div class="summary-section">
          <h4>{{ t('contract.refundPolicy') }}</h4>
          <el-select v-model="draftRefundPolicy" size="small">
            <el-option :label="`${t('contract.fullRefund')} (100%)`" value="full" />
            <el-option :label="`${t('contract.partialRefund')} (50%)`" value="partial_50" />
            <el-option :label="`${t('contract.partialRefund30')} (30%)`" value="partial_30" />
            <el-option :label="t('contract.noRefund')" value="no_refund" />
          </el-select>
        </div>
      </div>
      <div v-if="submitLoading" class="signing-status">
        <el-icon class="is-loading"><Loading /></el-icon>
        {{ t('contract.signing') }}
      </div>
      <div class="clarify-actions">
        <el-button :disabled="submitLoading" @click="currentStep = 1">{{ t('contract.back') }}</el-button>
        <el-button
          type="primary"
          :loading="submitLoading"
          @click="handleSign"
        >
          {{ t('contract.signAndExecute') }}
        </el-button>
        <el-button
          :disabled="submitLoading"
          @click="handleSkipContract"
        >
          {{ t('contract.executeWithoutContract') }}
        </el-button>
      </div>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Select, MoreFilled, Delete, Loading } from '@element-plus/icons-vue'
import { createContract, signContract } from '@/services/outcomeContractApi'
import { openClawIntake } from '@/services/gatewayApi'

const { t } = useI18n()

const props = defineProps<{
  modelValue: boolean
  taskText: string
  /** When false, intake skips plan gate and starts the pipeline immediately. */
  planMode?: boolean
}>()

const title = computed(() => {
  if (props.planMode === false) return t('contract.executeDirect')
  return t('contract.title')
})

const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'submitted', result: { taskId?: string; contractId?: string }): void
  (e: 'cancelled'): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const currentStep = ref(0)
const submitLoading = ref(false)

const steps = computed(() => [
  { label: t('contract.stepGoal') },
  { label: t('contract.stepMetrics') },
  { label: t('contract.stepSign') },
])

const draftGoal = ref('')
const draftRefundPolicy = ref('full')

interface DraftMetric {
  name: string
  source: string
  target_value: number
  direction: string
  measurement_window_days: number
  baseline_value?: number
  description?: string
}

const draftMetrics = ref<DraftMetric[]>([])

const hasValidMetrics = computed(() =>
  draftMetrics.value.some(
    (m) => m.name.trim().length > 0 && Number(m.target_value) > 0,
  ),
)

function formatMetricSymbol(direction: string): string {
  if (direction === 'decrease') return '≤'
  if (direction === 'reach') return '='
  return '≥'
}

function formatMetricSource(source: string): string {
  const key = `contract.metricSource.${source}`
  const translated = t(key)
  return translated === key ? source : translated
}

function onCancel() {
  visible.value = false
  emit('cancelled')
}

function initDraft() {
  currentStep.value = 0
  draftGoal.value = props.taskText
  draftMetrics.value = [{
    name: t('contract.defaultMetricName'),
    source: 'manual',
    target_value: 1,
    direction: 'increase',
    measurement_window_days: 30,
  }]
  draftRefundPolicy.value = 'full'
}

watch(() => props.modelValue, (val) => {
  if (val) initDraft()
})

function addMetric() {
  draftMetrics.value.push({
    name: '',
    source: 'manual',
    target_value: 1,
    direction: 'increase',
    measurement_window_days: 30,
  })
}

async function handleSkipContract() {
  submitLoading.value = true
  try {
    const result = await openClawIntake({
      title: props.taskText.slice(0, 80),
      description: props.taskText,
      source: 'web',
      userId: 'dashboard',
      messageId: `web-${Date.now()}`,
      planMode: props.planMode !== false,
      autoFinalAccept: false,
    })
    visible.value = false
    emit('submitted', { taskId: result.taskId })
  } catch (e: any) {
    ElMessage.error(e.message || t('contract.submitError'))
  } finally {
    submitLoading.value = false
  }
}

function parseContractError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err)
  if (raw.includes('empty_metrics') || raw.includes('missing:name')) {
    return t('contract.metricNameRequired')
  }
  if (raw.includes('invalid_metrics')) {
    return t('contract.invalidMetrics')
  }
  return raw || t('contract.signError')
}

async function handleSign() {
  const filteredMetrics = draftMetrics.value
    .filter((m) => m.name.trim())
    .map((m) => ({
      name: m.name.trim(),
      source: m.source || 'manual',
      target_value: m.target_value,
      direction: m.direction || 'increase',
      measurement_window_days: m.measurement_window_days || 30,
    }))

  if (filteredMetrics.length === 0) {
    ElMessage.warning(t('contract.metricNameRequired'))
    currentStep.value = 1
    return
  }

  submitLoading.value = true
  try {
    // Step 1: create the task via gateway
    const intakeResult = await openClawIntake({
      title: props.taskText.slice(0, 80),
      description: props.taskText,
      source: 'web',
      userId: 'dashboard',
      messageId: `web-contract-${Date.now()}`,
      planMode: props.planMode !== false,
      autoFinalAccept: false,
    })
    const taskId = intakeResult.taskId
    if (!taskId) {
      throw new Error(t('contract.noTaskId'))
    }

    const verifyPlan = [
      { day: 30, method: 'auto_metric_check' },
      { day: 60, method: 'auto_metric_check' },
      { day: 90, method: 'customer_survey' },
    ]

    const contractResult = await createContract({
      task_id: taskId,
      business_goal: draftGoal.value,
      success_metrics: filteredMetrics,
      verification_plan: verifyPlan,
      refund_policy: draftRefundPolicy.value,
    })

    // Step 3: sign the contract
    await signContract(contractResult.id, {
      signed_by_customer: 'dashboard-user',
      signature_meta: { source: 'web', method: 'auto' },
    })

    visible.value = false
    emit('submitted', { taskId, contractId: contractResult.id })
    ElMessage.success(t('contract.signedSuccess'))
  } catch (e: unknown) {
    ElMessage.error(parseContractError(e))
  } finally {
    submitLoading.value = false
  }
}
</script>

<style scoped>
.clarify-dialog :deep(.el-dialog__body) {
  padding-top: 12px;
}

.clarify-steps {
  display: flex;
  justify-content: center;
  gap: 16px;
  margin-bottom: 24px;
}

.clarify-step {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  opacity: 0.5;
  transition: all 0.2s;
}
.clarify-step.active {
  opacity: 1;
  color: var(--el-color-primary);
  font-weight: 600;
}
.clarify-step.done {
  opacity: 0.8;
  color: var(--el-color-success);
}

.clarify-body {
  min-height: 260px;
}

.clarify-desc {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 16px;
  line-height: 1.6;
}

.metric-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 12px;
}

.metric-item {
  padding: 12px;
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
  border: 1px solid var(--el-border-color-lighter);
}

.metric-row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.metric-suggestion {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}

.add-metric-btn {
  margin-bottom: 16px;
}

.clarify-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.contract-summary {
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}

.summary-section {
  margin-bottom: 12px;
}
.summary-section:last-child {
  margin-bottom: 0;
}

.summary-section h4 {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--el-text-color-primary);
}

.summary-section p {
  font-size: 13px;
  color: var(--el-text-color-regular);
  line-height: 1.5;
}

.summary-section ul {
  list-style: none;
  padding: 0;
  margin: 0;
}

.summary-section li {
  font-size: 13px;
  color: var(--el-text-color-regular);
  padding: 3px 0;
}

.signing-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--el-color-primary);
  margin-bottom: 12px;
}
</style>
