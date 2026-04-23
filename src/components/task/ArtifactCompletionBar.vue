<template>
  <div class="artifact-completion-bar">
    <div
      v-for="item in items"
      :key="item.stageId"
      class="artifact-item"
      :class="item.statusClass"
      :title="item.tooltip"
    >
      <span class="artifact-icon">{{ item.icon }}</span>
      <span class="artifact-label">{{ item.label }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface StageInfo {
  id: string
  label: string
  status: string
  output?: string | null
}

const props = defineProps<{
  stages: StageInfo[]
}>()

const ARTIFACT_MAP: { stageId: string; icon: string; label: string }[] = [
  { stageId: 'planning',     icon: '📋', label: '需求' },
  { stageId: 'design',       icon: '🎨', label: 'UI' },
  { stageId: 'architecture', icon: '🏗', label: '架构' },
  { stageId: 'development',  icon: '💻', label: '代码' },
  { stageId: 'testing',      icon: '🧪', label: '测试' },
  { stageId: 'reviewing',    icon: '✅', label: '验收' },
  { stageId: 'deployment',   icon: '🚀', label: '运维' },
]

const items = computed(() => {
  const stageMap = new Map(props.stages.map(s => [s.id, s]))
  return ARTIFACT_MAP.map(a => {
    const stage = stageMap.get(a.stageId)
    let statusClass = 'not-started'
    let tooltip = `${a.label}：未开始`

    if (stage) {
      if (stage.status === 'done' && stage.output) {
        statusClass = 'completed'
        tooltip = `${a.label}：已完成`
      } else if (['active', 'reviewing', 'awaiting_approval'].includes(stage.status)) {
        statusClass = 'in-progress'
        tooltip = `${a.label}：进行中`
      } else if (stage.status === 'rejected' || stage.status === 'failed') {
        statusClass = 'failed'
        tooltip = `${a.label}：失败/被打回`
      } else if (stage.output) {
        statusClass = 'completed'
        tooltip = `${a.label}：已产出`
      }
    }

    return { ...a, statusClass, tooltip }
  })
})
</script>

<style scoped>
.artifact-completion-bar {
  display: flex;
  gap: 4px;
  padding: 10px 0;
  flex-wrap: wrap;
}

.artifact-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 13px;
  transition: all 0.2s;
  cursor: default;
  user-select: none;
}

.artifact-icon {
  font-size: 15px;
}

.artifact-label {
  font-weight: 500;
}

.artifact-item.not-started {
  background: var(--el-fill-color-light, #f5f7fa);
  color: var(--el-text-color-placeholder, #a8abb2);
}

.artifact-item.in-progress {
  background: #fdf6ec;
  color: #e6a23c;
}

.artifact-item.completed {
  background: #f0f9eb;
  color: #67c23a;
}

.artifact-item.failed {
  background: #fef0f0;
  color: #f56c6c;
}
</style>
