<template>
  <div class="team-view">
    <h1>{{ t('team.title') }}</h1>
    <p class="view-subtitle">{{ t('team.subtitle') }}</p>

    <div class="agent-grid">
      <div
        v-for="agent in allAgents"
        :key="agent.id"
        class="agent-card"
        :style="{ borderColor: agent.color }"
        @click="goAgent(agent.id)"
      >
        <div class="agent-avatar" :style="{ background: agent.color + '22', color: agent.color }">
          <el-icon :size="28"><component :is="resolveAgentIcon(agent.icon)" /></el-icon>
        </div>
        <div class="agent-info">
          <div class="agent-name">{{ agent.name }}</div>
          <div class="agent-role">{{ agent.role || agent.id }}</div>
        </div>
        <el-tag size="small" :type="agent.category === 'core' ? 'primary' : 'info'" class="agent-tag">
          {{ agent.category === 'core' ? t('team.categoryCore') : t('team.categorySupport') }}
        </el-tag>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'
import { useAgentStore } from '@/stores/agents'
import { resolveAgentIcon } from '@/utils/agentIcon'

const router = useRouter()
const { t } = useI18n()
const agentStore = useAgentStore()
const { coreAgents, supportAgents } = storeToRefs(agentStore)

onMounted(() => {
  if (!agentStore.loaded) agentStore.fetchAgents()
})

const allAgents = computed(() => [
  ...coreAgents.value.map(a => ({ ...a, category: 'core' as const })),
  ...supportAgents.value.map(a => ({ ...a, category: 'support' as const })),
])

function goAgent(id: string) {
  router.push(`/agent/${id}`)
}
</script>

<style scoped>
.team-view {
  padding: 24px 32px;
  max-width: 1200px;
}

.team-view h1 {
  font-size: 22px;
  margin-bottom: 4px;
}

.view-subtitle {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-bottom: 24px;
}

.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}

.agent-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: 12px;
  border: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color);
  cursor: pointer;
  transition: all 0.2s;
}

.agent-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
  transform: translateY(-2px);
}

.agent-avatar {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.agent-info {
  flex: 1;
  min-width: 0;
}

.agent-name {
  font-weight: 600;
  font-size: 14px;
}

.agent-role {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-tag {
  flex-shrink: 0;
}
</style>
