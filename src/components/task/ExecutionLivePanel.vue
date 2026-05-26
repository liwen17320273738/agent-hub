<template>
  <section class="execution-live" :class="{ running: isRunning }">
    <div class="exec-live-header">
      <div class="exec-live-title-row">
        <span v-if="isRunning" class="live-dot" />
        <h2 class="exec-live-title">{{ t('executionLive.title') }}</h2>
        <el-tag v-if="isRunning" size="small" type="warning" effect="light">
          {{ t('pipelineTaskDetail.tagAiRunning') }}
        </el-tag>
      </div>
      <div class="exec-live-actions">
        <el-button size="small" text type="primary" @click="$emit('open-overview')">
          {{ t('executionLive.viewOverview') }}
        </el-button>
        <el-button size="small" text type="primary" @click="$emit('open-log')">
          {{ t('executionLive.viewLog') }}
        </el-button>
      </div>
    </div>

    <div class="exec-progress-row">
      <div class="exec-progress-meta">
        <span class="exec-stage-label">{{ progress.currentLabel }}</span>
        <span v-if="progress.currentRole" class="exec-stage-role">{{ progress.currentRole }}</span>
      </div>
      <span class="exec-progress-count">
        {{ t('executionLive.progress', { done: progress.done, total: progress.total }) }}
      </span>
    </div>
    <el-progress
      :percentage="progress.percent"
      :stroke-width="8"
      :status="isRunning ? undefined : 'success'"
      class="exec-progress-bar"
    />

    <p v-if="bannerSub" class="exec-banner-sub">{{ bannerSub }}</p>

    <div v-if="narrative" class="exec-narrative">
      <span class="narrative-icon">{{ narrative.icon }}</span>
      <span class="narrative-agent">{{ narrative.agent }}</span>
      <span class="narrative-text">{{ narrative.narrative }}</span>
    </div>

    <div class="exec-log-feed">
      <div class="exec-log-head">{{ t('executionLive.recentEvents') }}</div>
      <div v-if="!logs.length" class="exec-log-empty">
        {{ t('executionLive.noEventsYet') }}
      </div>
      <ul v-else class="exec-log-list">
        <li v-for="(log, i) in logs" :key="`${log.timestamp}-${i}`" class="exec-log-item">
          <span class="log-time">{{ log.time }}</span>
          <span class="log-event">{{ log.eventLabel }}</span>
          <span v-if="log.detail" class="log-detail">{{ log.detail }}</span>
        </li>
      </ul>
    </div>
  </section>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

export interface ExecutionLogLine {
  time: string
  eventLabel: string
  detail?: string
  timestamp: number
}

export interface ExecutionNarrative {
  agent: string
  icon: string
  narrative: string
}

export interface StageProgress {
  done: number
  total: number
  percent: number
  currentLabel: string
  currentRole: string
}

defineProps<{
  isRunning: boolean
  progress: StageProgress
  bannerSub?: string
  narrative?: ExecutionNarrative | null
  logs: ExecutionLogLine[]
}>()

defineEmits<{
  'open-overview': []
  'open-log': []
}>()

const { t } = useI18n()
</script>

<style scoped>
.execution-live {
  margin-bottom: 20px;
  padding: 16px 18px;
  border-radius: 12px;
  border: 1px solid var(--border-color, #2a2f3a);
  background: var(--bg-card, #1a1d24);
}

.execution-live.running {
  border-color: rgba(245, 158, 11, 0.45);
  box-shadow: 0 0 0 1px rgba(245, 158, 11, 0.12);
}

.exec-live-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.exec-live-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.exec-live-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary, #e8eaed);
}

.exec-live-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.live-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #f59e0b;
  animation: live-pulse 1.4s infinite;
}

.exec-progress-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.exec-stage-label {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary, #e8eaed);
}

.exec-stage-role {
  margin-left: 8px;
  font-size: 12px;
  color: var(--text-muted, #8a8f99);
}

.exec-progress-count {
  font-size: 12px;
  color: var(--text-secondary, #a0a4ae);
  white-space: nowrap;
}

.exec-progress-bar {
  margin-bottom: 10px;
}

.exec-banner-sub {
  margin: 0 0 10px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-secondary, #a0a4ae);
}

.exec-narrative {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 10px 12px;
  margin-bottom: 12px;
  border-radius: 8px;
  background: rgba(124, 92, 255, 0.08);
  border: 1px solid rgba(124, 92, 255, 0.2);
  font-size: 13px;
}

.narrative-icon { font-size: 16px; }
.narrative-agent { font-weight: 600; color: var(--text-primary, #e8eaed); }
.narrative-text { color: var(--text-secondary, #a0a4ae); }

.exec-log-feed {
  border-top: 1px solid var(--border-color, #2a2f3a);
  padding-top: 10px;
}

.exec-log-head {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted, #8a8f99);
  margin-bottom: 8px;
}

.exec-log-empty {
  font-size: 12px;
  color: var(--text-muted, #8a8f99);
  font-style: italic;
}

.exec-log-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 140px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.exec-log-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
  line-height: 1.4;
}

.log-time {
  flex-shrink: 0;
  color: var(--text-muted, #8a8f99);
  font-family: ui-monospace, monospace;
}

.log-event {
  flex-shrink: 0;
  color: var(--accent, #7c5cff);
  font-weight: 500;
}

.log-detail {
  color: var(--text-secondary, #a0a4ae);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@keyframes live-pulse {
  0% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.5); }
  70% { box-shadow: 0 0 0 8px rgba(245, 158, 11, 0); }
  100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0); }
}
</style>
