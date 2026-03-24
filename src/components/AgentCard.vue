<template>
  <div class="agent-card" @click="$emit('click')">
    <div class="card-icon" :style="{ background: agent.color + '18', color: agent.color }">
      <el-icon :size="28"><component :is="agent.icon" /></el-icon>
    </div>
    <div class="card-body">
      <div class="card-top">
        <h3>{{ agent.name }}</h3>
        <el-tag size="small" type="info" effect="plain">{{ agent.title }}</el-tag>
      </div>
      <p class="card-desc">{{ agent.description }}</p>
      <div class="card-footer">
        <span v-if="conversationCount" class="conv-count">
          <el-icon :size="12"><ChatDotRound /></el-icon>
          {{ conversationCount }} 个对话
        </span>
        <span v-else class="conv-count empty">开始对话 →</span>
      </div>
    </div>
    <div class="card-accent" :style="{ background: agent.color }" />
  </div>
</template>

<script setup lang="ts">
import type { AgentConfig } from '@/agents/types'

defineProps<{
  agent: AgentConfig
  conversationCount: number
}>()

defineEmits(['click'])
</script>

<style scoped>
.agent-card {
  position: relative;
  display: flex;
  gap: 16px;
  padding: 20px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  cursor: pointer;
  transition: all 0.2s;
  overflow: hidden;
}

.agent-card:hover {
  border-color: var(--text-muted);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
}

.card-accent {
  position: absolute;
  top: 0;
  left: 0;
  width: 3px;
  height: 100%;
  opacity: 0;
  transition: opacity 0.2s;
}

.agent-card:hover .card-accent {
  opacity: 1;
}

.card-icon {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.card-body {
  flex: 1;
  min-width: 0;
}

.card-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.card-top h3 {
  font-size: 16px;
  font-weight: 600;
}

.card-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin-bottom: 10px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-footer {
  display: flex;
  align-items: center;
}

.conv-count {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted);
}

.conv-count.empty {
  color: var(--accent);
}
</style>
