<template>
  <div class="failure-card" v-if="failedStage">
    <div class="fc-header">
      <span class="fc-icon">⚠️</span>
      <h3>任务执行遇到问题</h3>
    </div>

    <div class="fc-grid">
      <div class="fc-field">
        <label>卡在哪一关</label>
        <p>{{ failedStage.label || failedStage.id }} <span class="fc-role">（{{ failedStage.ownerRole }}）</span></p>
      </div>

      <div class="fc-field">
        <label>卡住原因</label>
        <p>{{ humanReason }}</p>
        <el-collapse v-if="rawError" class="fc-trace">
          <el-collapse-item title="查看技术详情">
            <pre class="fc-raw">{{ rawError }}</pre>
          </el-collapse-item>
        </el-collapse>
      </div>

      <div class="fc-field">
        <label>谁需要处理</label>
        <el-tag :type="ownerType" size="small">{{ ownerLabel }}</el-tag>
      </div>

      <div class="fc-field">
        <label>下一步怎么办</label>
        <div class="fc-actions">
          <el-button size="small" type="primary" @click="$emit('retry', failedStage.id)">
            重试本阶段
          </el-button>
          <el-button size="small" @click="$emit('retry-with-downgrade', failedStage.id)">
            换模型重试
          </el-button>
          <el-button size="small" @click="$emit('rollback', failedStage.id)">
            打回上一阶段
          </el-button>
          <el-button size="small" type="warning" @click="$emit('escalate', failedStage.id)">
            升级到人工
          </el-button>
        </div>
      </div>
    </div>

    <div v-if="rcaSummary" class="fc-rca">
      <label>AI 诊断建议</label>
      <p>{{ rcaSummary }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

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

const failedStage = computed(() =>
  props.stages.find(s => s.status === 'failed') || null
)

const rawError = computed(() => {
  if (!failedStage.value) return ''
  return (failedStage.value as any).lastError || (failedStage.value as any).last_error || ''
})

const humanReason = computed(() => {
  const raw = rawError.value
  if (!raw) return '未知原因'
  if (raw.includes('timeout') || raw.includes('超时')) return '调用模型超时'
  if (raw.includes('rate_limit') || raw.includes('429')) return '模型调用频率超限'
  if (raw.includes('401') || raw.includes('auth')) return 'API Key 认证失败'
  if (raw.includes('500')) return '模型服务内部错误'
  if (raw.includes('context_length') || raw.includes('too long')) return '输入内容超过模型上下文限制'
  if (raw.length > 100) return raw.slice(0, 100) + '…'
  return raw
})

const ownerLabel = computed(() => {
  const reason = humanReason.value
  if (reason.includes('API Key')) return 'Admin 需要检查密钥配置'
  if (reason.includes('超限') || reason.includes('频率')) return 'Admin 需要调整额度'
  if (reason.includes('超时') || reason.includes('错误')) return 'Agent 可以自动重试'
  if (reason.includes('上下文')) return '用户需要精简 prompt'
  return 'Agent 可以自动重试'
})

const ownerType = computed(() => {
  if (ownerLabel.value.startsWith('Admin')) return 'danger'
  if (ownerLabel.value.startsWith('用户')) return 'warning'
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
