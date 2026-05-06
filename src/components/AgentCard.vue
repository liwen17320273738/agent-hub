<template>
  <div class="agent-card" @click="$emit('click')">
    <div class="card-icon" :style="{ background: agent.color + '18', color: agent.color }">
      <el-icon :size="28"><component :is="resolveAgentIcon(agent.icon)" /></el-icon>
    </div>
    <div class="card-body">
      <div class="card-top">
        <h3>{{ agent.name }}</h3>
        <el-tag size="small" type="info" effect="plain">{{ agent.title }}</el-tag>
      </div>

      <p v-if="seniority" class="card-seniority">{{ seniority }}</p>

      <p class="card-desc">{{ agent.description }}</p>

      <div v-if="domainTags.length" class="card-tags">
        <el-tag
          v-for="tag in domainTags.slice(0, 4)"
          :key="tag"
          size="small"
          :color="agent.color + '20'"
          :style="{ color: agent.color, borderColor: agent.color + '40' }"
          effect="plain"
        >{{ tag }}</el-tag>
        <el-tag v-if="domainTags.length > 4" size="small" type="info" effect="plain">
          +{{ domainTags.length - 4 }}
        </el-tag>
      </div>

      <div class="card-footer">
        <span v-if="toolCount" class="card-meta">
          <el-icon :size="12"><SetUp /></el-icon>
          {{ toolCount }} 工具
        </span>
        <span v-if="skillCount" class="card-meta">
          <el-icon :size="12"><MagicStick /></el-icon>
          {{ skillCount }} 技能
        </span>
        <router-link
          :to="profileLink"
          class="card-profile-link"
          @click.stop
        >{{ t('agentCard.text_1') }}</router-link>
        <span v-if="conversationCount" class="conv-count">
          <el-icon :size="12"><ChatDotRound /></el-icon>
          {{ conversationCount }} 对话
        </span>
        <span v-else class="conv-count empty">{{ t('agentCard.text_2') }}</span>
      </div>
    </div>
    <div class="card-accent" :style="{ background: agent.color }" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AgentProfile } from '@/stores/agents'
import { resolveAgentIcon } from '@/utils/agentIcon'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

const { t } = useI18n()
const route = useRoute()

const props = defineProps<{
  agent: AgentProfile
  conversationCount: number
}>()

defineEmits(['click'])

const capabilities = computed(() => props.agent.capabilities || {})
const seniority = computed(() => capabilities.value.seniority as string || '')
const domainTags = computed(() => (capabilities.value.domain as string[]) || [])
const toolCount = computed(() => props.agent.tools?.length || 0)
const skillCount = computed(() => props.agent.skills?.length || 0)

const profileLink = computed(() => ({
  path: `/agent/${props.agent.id}/profile`,
  query: { from: route.fullPath },
}))
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
  margin-bottom: 4px;
}

.card-top h3 {
  font-size: 16px;
  font-weight: 600;
}

.card-seniority {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
  font-style: italic;
}

.card-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
  margin-bottom: 8px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
}

.card-tags .el-tag {
  font-size: 11px;
  height: 20px;
  padding: 0 6px;
}

.card-footer {
  display: flex;
  align-items: center;
  gap: 12px;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  color: var(--text-muted);
}

.conv-count {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted);
  margin-left: auto;
}

.conv-count.empty {
  color: var(--accent);
}

.card-profile-link {
  font-size: 11px;
  color: var(--text-muted);
  text-decoration: none;
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  transition: all 0.15s;
}
.card-profile-link:hover {
  color: var(--accent);
  border-color: var(--accent);
}
</style>
