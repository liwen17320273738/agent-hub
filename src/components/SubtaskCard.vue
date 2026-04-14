<script setup lang="ts">
/**
 * SubtaskCard — deer-flow 风格的子任务追踪卡片
 *
 * 在 Chat 或 Pipeline 视图中展示子任务的实时状态：
 * - 运行中: 旋转动画 + 进度描述
 * - 完成: 绿色勾 + 可展开查看产出
 * - 失败: 红色叉 + 错误信息
 */
import { ref, computed } from 'vue'
import type { SubtaskInfo } from '@/agents/types'

const props = defineProps<{
  subtask: SubtaskInfo
}>()

const expanded = ref(false)

const roleLabels: Record<string, string> = {
  'product-manager': '产品经理',
  'developer': '架构师',
  'executor': '执行者',
  'qa-lead': 'QA',
  'orchestrator': '总控',
}

const roleColors: Record<string, string> = {
  'product-manager': '#409EFF',
  'developer': '#67C23A',
  'executor': '#E6A23C',
  'qa-lead': '#F56C6C',
  'orchestrator': '#909399',
}

const roleLabel = computed(() => roleLabels[props.subtask.role] || props.subtask.role)
const roleColor = computed(() => roleColors[props.subtask.role] || '#909399')

const statusIcon = computed(() => {
  switch (props.subtask.status) {
    case 'running': return '⟳'
    case 'completed': return '✓'
    case 'failed': return '✗'
    default: return '○'
  }
})

const statusClass = computed(() => `status-${props.subtask.status}`)

const duration = computed(() => {
  if (!props.subtask.startTime) return ''
  const end = props.subtask.endTime || Date.now()
  const ms = end - props.subtask.startTime
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}min`
})

const outputPreview = computed(() => {
  if (!props.subtask.output) return ''
  return props.subtask.output.length > 200
    ? props.subtask.output.slice(0, 200) + '...'
    : props.subtask.output
})
</script>

<template>
  <div class="subtask-card" :class="statusClass" @click="expanded = !expanded">
    <div class="subtask-header">
      <span class="status-icon" :class="statusClass">{{ statusIcon }}</span>
      <span class="role-badge" :style="{ backgroundColor: roleColor + '20', color: roleColor, borderColor: roleColor }">
        {{ roleLabel }}
      </span>
      <span class="subtask-title">{{ subtask.title }}</span>
      <span v-if="duration" class="duration">{{ duration }}</span>
      <span class="expand-icon">{{ expanded ? '▾' : '▸' }}</span>
    </div>

    <div v-if="subtask.status === 'running'" class="progress-bar">
      <div class="progress-fill" />
    </div>

    <div v-if="expanded" class="subtask-body">
      <div v-if="subtask.error" class="error-msg">
        {{ subtask.error }}
      </div>
      <div v-else-if="subtask.output" class="output-content" v-html="renderMd(subtask.output)" />
      <div v-else class="pending-msg">
        {{ subtask.status === 'running' ? 'AI 正在处理...' : '等待执行' }}
      </div>
    </div>

    <div v-else-if="subtask.status === 'completed' && outputPreview" class="subtask-preview">
      {{ outputPreview }}
    </div>
  </div>
</template>

<script lang="ts">
import { renderMarkdown as renderMd } from '@/services/markdown'
export { renderMd }
</script>

<style scoped>
.subtask-card {
  border: 1px solid var(--border-color, #e4e7ed);
  border-radius: 8px;
  padding: 12px 16px;
  margin: 8px 0;
  cursor: pointer;
  transition: all 0.2s;
  background: var(--bg-secondary, #fff);
}
.subtask-card:hover {
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
.subtask-card.status-running {
  border-color: #409EFF;
  background: linear-gradient(135deg, rgba(64,158,255,0.08) 0%, var(--bg-secondary, #fff) 100%);
}
.subtask-card.status-completed {
  border-color: #67C23A;
}
.subtask-card.status-failed {
  border-color: #F56C6C;
  background: rgba(245,108,108,0.06);
}

.subtask-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.status-icon {
  font-weight: bold;
  font-size: 16px;
}
.status-icon.status-running {
  color: #409EFF;
  animation: spin 1s linear infinite;
}
.status-icon.status-completed { color: #67C23A; }
.status-icon.status-failed { color: #F56C6C; }
.status-icon.status-pending { color: #c0c4cc; }

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.role-badge {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  border: 1px solid;
  white-space: nowrap;
}

.subtask-title {
  flex: 1;
  font-weight: 500;
  color: var(--text-primary, #303133);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.duration {
  font-size: 12px;
  color: var(--text-muted, #909399);
}

.expand-icon {
  color: var(--text-muted, #c0c4cc);
  font-size: 12px;
}

.progress-bar {
  height: 2px;
  background: #e4e7ed;
  border-radius: 1px;
  margin-top: 8px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  width: 30%;
  background: linear-gradient(90deg, #409EFF, #67C23A);
  border-radius: 1px;
  animation: progress-sweep 2s ease-in-out infinite;
}
@keyframes progress-sweep {
  0% { width: 10%; margin-left: 0; }
  50% { width: 40%; margin-left: 30%; }
  100% { width: 10%; margin-left: 90%; }
}

.subtask-body {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border-color, #ebeef5);
}

.output-content {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary, #303133);
  max-height: 400px;
  overflow-y: auto;
}
.output-content :deep(h2), .output-content :deep(h3), .output-content :deep(h4) {
  margin: 8px 0 4px;
  color: var(--text-primary, #303133);
}
.output-content :deep(code) {
  background: var(--bg-tertiary, #f5f7fa);
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 12px;
}

.error-msg {
  color: #F56C6C;
  font-size: 13px;
}

.pending-msg {
  color: var(--text-muted, #909399);
  font-size: 13px;
  font-style: italic;
}

.subtask-preview {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-muted, #909399);
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
</style>
