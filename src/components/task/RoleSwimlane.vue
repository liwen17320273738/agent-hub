<template>
  <div class="role-swimlane">
    <div
      v-for="lane in lanes"
      :key="lane.stageId"
      class="swim-lane"
      :class="lane.statusClass"
    >
      <div class="lane-header">
        <span class="lane-icon">{{ lane.icon }}</span>
        <span class="lane-label">{{ lane.label }}</span>
        <el-tag :type="lane.tagType" size="small" class="lane-status">{{ lane.statusText }}</el-tag>
      </div>
      <div class="lane-body">
        <div class="lane-agent">
          <el-icon><User /></el-icon>
          <span>{{ lane.agentName }}</span>
        </div>
        <div v-if="lane.output" class="lane-output-preview">
          {{ lane.outputPreview }}
        </div>
        <div v-if="lane.feedback" class="lane-feedback">
          <el-icon><ChatDotRound /></el-icon>
          <span>{{ lane.feedback }}</span>
        </div>
      </div>
      <div class="lane-connector" v-if="!lane.isLast">
        <span class="connector-arrow">→</span>
      </div>
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
  assigned_agent?: string | null
  reviewer_feedback?: string | null
}

const props = defineProps<{
  stages: StageInfo[]
}>()

const LANE_META: { stageId: string; icon: string; label: string; defaultAgent: string }[] = [
  { stageId: 'planning',     icon: '📋', label: '需求规划', defaultAgent: 'CEO / 产品经理' },
  { stageId: 'design',       icon: '🎨', label: 'UI/UX 设计', defaultAgent: '设计师' },
  { stageId: 'architecture', icon: '🏗', label: '架构设计', defaultAgent: '架构师' },
  { stageId: 'development',  icon: '💻', label: '开发实现', defaultAgent: '开发工程师' },
  { stageId: 'testing',      icon: '🧪', label: '测试验证', defaultAgent: 'QA 负责人' },
  { stageId: 'reviewing',    icon: '✅', label: '审查验收', defaultAgent: '验收官' },
  { stageId: 'deployment',   icon: '🚀', label: '部署上线', defaultAgent: 'DevOps' },
]

const lanes = computed(() => {
  const stageMap = new Map(props.stages.map(s => [s.id, s]))

  return LANE_META.map((meta, idx) => {
    const stage = stageMap.get(meta.stageId)
    const status = stage?.status || 'pending'

    let statusClass = 'lane-pending'
    let tagType: 'info' | 'warning' | 'success' | 'danger' | 'primary' = 'info'
    let statusText = '未开始'

    if (status === 'done') {
      statusClass = 'lane-done'
      tagType = 'success'
      statusText = '已完成'
    } else if (['active', 'running', 'reviewing', 'awaiting_approval'].includes(status)) {
      statusClass = 'lane-active'
      tagType = 'primary'
      statusText = '进行中'
    } else if (status === 'rejected' || status === 'failed') {
      statusClass = 'lane-rejected'
      tagType = 'danger'
      statusText = status === 'rejected' ? '被打回' : '失败'
    } else if (status === 'skipped') {
      statusClass = 'lane-skipped'
      tagType = 'info'
      statusText = '跳过'
    }

    const output = stage?.output || ''
    const outputPreview = output.length > 80 ? output.slice(0, 80) + '…' : output

    return {
      ...meta,
      statusClass,
      tagType,
      statusText,
      agentName: stage?.assigned_agent || meta.defaultAgent,
      output,
      outputPreview,
      feedback: stage?.reviewer_feedback ? stage.reviewer_feedback.slice(0, 100) : '',
      isLast: idx === LANE_META.length - 1,
    }
  })
})
</script>

<style scoped>
.role-swimlane {
  display: flex;
  gap: 2px;
  overflow-x: auto;
  padding: 12px 0;
}

.swim-lane {
  flex: 1;
  min-width: 140px;
  max-width: 200px;
  border-radius: 10px;
  padding: 12px;
  position: relative;
  transition: all 0.2s;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}

.lane-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}

.lane-icon {
  font-size: 16px;
}

.lane-label {
  font-weight: 600;
  font-size: 12px;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lane-body {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.lane-agent {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 6px;
  font-weight: 500;
}

.lane-output-preview {
  font-size: 11px;
  color: var(--el-text-color-regular);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: 6px;
}

.lane-feedback {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  font-size: 11px;
  color: var(--el-color-warning);
  background: rgba(230, 162, 60, 0.08);
  border-radius: 6px;
  padding: 4px 6px;
}

.lane-connector {
  position: absolute;
  right: -12px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 1;
  color: var(--el-text-color-placeholder);
  font-size: 14px;
}

/* Status styles */
.lane-pending {
  opacity: 0.5;
}

.lane-active {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 1px var(--el-color-primary-light-5);
}

.lane-done {
  border-color: var(--el-color-success-light-3);
  background: rgba(103, 194, 58, 0.04);
}

.lane-rejected {
  border-color: var(--el-color-danger-light-3);
  background: rgba(245, 108, 108, 0.04);
}

.lane-skipped {
  opacity: 0.4;
}
</style>
