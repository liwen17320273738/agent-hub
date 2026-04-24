<template>
  <div class="failure-card" v-if="failedStage">
    <div class="fc-header">
      <span class="fc-icon">⚠️</span>
      <h3>{{ t('failureCard.title') }}</h3>
    </div>

    <div class="fc-grid">
      <div class="fc-field">
        <label>{{ t('failureCard.whichStage') }}</label>
        <p>{{ failedStage.label || failedStage.id }} <span class="fc-role">（{{ failedStage.ownerRole }}）</span></p>
      </div>

      <div class="fc-field">
        <label>{{ t('failureCard.whyStuck') }}</label>
        <p>{{ humanReason }}</p>
        <el-collapse v-if="rawError" class="fc-trace">
          <el-collapse-item :title="t('failureCard.viewTechDetails')">
            <pre class="fc-raw">{{ rawError }}</pre>
          </el-collapse-item>
        </el-collapse>
      </div>

      <div class="fc-field">
        <label>{{ t('failureCard.whoHandles') }}</label>
        <el-tag :type="ownerType" size="small">{{ ownerLabel }}</el-tag>
      </div>

      <div class="fc-field">
        <label>{{ t('failureCard.nextStep') }}</label>
        <div class="fc-actions">
          <el-button size="small" type="primary" @click="$emit('retry', failedStage.id)">
            {{ t('failureCard.retryStage') }}
          </el-button>
          <el-button size="small" @click="$emit('retry-with-downgrade', failedStage.id)">
            {{ t('failureCard.retryDowngrade') }}
          </el-button>
          <el-button size="small" @click="$emit('rollback', failedStage.id)">
            {{ t('failureCard.rollback') }}
          </el-button>
          <el-button size="small" type="warning" @click="$emit('escalate', failedStage.id)">
            {{ t('failureCard.escalate') }}
          </el-button>
        </div>
      </div>
    </div>

    <div v-if="rcaSummary" class="fc-rca">
      <label>{{ t('failureCard.aiDiagnosis') }}</label>
      <p>{{ rcaSummary }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

interface StageInfo {
  id: string
  label: string
  status: string
  ownerRole: string
  output?: string
  lastError?: string
}

const props = defineProps<{
  stages: StageInfo[]
  rcaSummary?: string
}>()

defineEmits<{
  retry: [stageId: string]
  'retry-with-downgrade': [stageId: string]
  rollback: [stageId: string]
  escalate: [stageId: string]
}>()

const { t } = useI18n()

const failedStage = computed(() =>
  props.stages.find(s => s.status === 'failed') || null
)

const rawError = computed(() => {
  if (!failedStage.value) return ''
  return (failedStage.value as any).lastError || (failedStage.value as any).last_error || ''
})

const humanReason = computed(() => {
  const raw = rawError.value
  if (!raw) return t('failureCard.reasonUnknown')
  if (raw.includes('timeout') || raw.includes('超时')) return t('failureCard.reasonTimeout')
  if (raw.includes('rate_limit') || raw.includes('429')) return t('failureCard.reasonRateLimit')
  if (raw.includes('401') || raw.includes('auth')) return t('failureCard.reasonAuth')
  if (raw.includes('500')) return t('failureCard.reasonServer')
  if (raw.includes('context_length') || raw.includes('too long')) return t('failureCard.reasonContext')
  if (raw.length > 100) return raw.slice(0, 100) + '…'
  return raw
})

const ownerLabel = computed(() => {
  const reason = humanReason.value
  if (reason.includes('API Key') || reason.includes(t('failureCard.reasonAuth'))) return t('failureCard.ownerAdminKey')
  if (reason.includes('超限') || reason.includes('频率') || reason === t('failureCard.reasonRateLimit')) return t('failureCard.ownerAdminQuota')
  if (reason.includes('超时') || reason.includes('错误') || reason === t('failureCard.reasonTimeout') || reason === t('failureCard.reasonServer')) return t('failureCard.ownerAgentRetry')
  if (reason.includes('上下文') || reason === t('failureCard.reasonContext')) return t('failureCard.ownerUserPrompt')
  return t('failureCard.ownerAgentRetry')
})

const ownerType = computed(() => {
  if (ownerLabel.value === t('failureCard.ownerAdminKey') || ownerLabel.value === t('failureCard.ownerAdminQuota')) return 'danger'
  if (ownerLabel.value === t('failureCard.ownerUserPrompt')) return 'warning'
  return 'primary'
})
</script>

<style scoped>
.failure-card {
  padding: 20px 24px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(245, 108, 108, 0.06), rgba(230, 162, 60, 0.04));
  border: 1px solid rgba(245, 108, 108, 0.2);
  margin-bottom: 16px;
}

.fc-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.fc-icon { font-size: 20px; }

.fc-header h3 {
  font-size: 16px;
  font-weight: 700;
  color: #f56c6c;
  margin: 0;
}

.fc-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.fc-field label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.fc-field p {
  margin: 0;
  font-size: 14px;
  line-height: 1.5;
}

.fc-role {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.fc-trace {
  margin-top: 8px;
}

.fc-raw {
  font-size: 11px;
  background: var(--el-fill-color-light);
  padding: 8px;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}

.fc-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
}

.fc-rca {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.fc-rca label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}

.fc-rca p {
  font-size: 14px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}

@media (max-width: 768px) {
  .fc-grid { grid-template-columns: 1fr; }
}
</style>
