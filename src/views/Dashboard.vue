<template>
  <div class="dashboard">
    <header class="dashboard-header">
      <h1>一人公司智能体中心</h1>
      <p class="subtitle">你的 AI 团队已就位，选择一个智能体开始工作</p>
      <div class="status-bar" v-if="!settingsStore.isConfigured()">
        <el-alert type="warning" :closable="false" show-icon>
          <template #title>
            尚未配置 API Key，请先前往
            <router-link to="/settings" style="color: var(--accent)">设置页面</router-link>
            配置 LLM 服务
          </template>
        </el-alert>
      </div>
    </header>

    <el-alert class="model-lab-teaser" type="success" :closable="false" show-icon>
      <template #title>模型选型</template>
      内置多厂商模型维度参考与同一提示词下的延迟对比，见
      <router-link class="teaser-link" to="/model-lab">模型实验室</router-link>
      。
    </el-alert>

    <section class="agent-section">
      <h2 class="section-title">
        <el-icon><Star /></el-icon>
        核心智能体
      </h2>
      <div class="agent-grid">
        <AgentCard
          v-for="agent in coreAgents"
          :key="agent.id"
          :agent="agent"
          :conversation-count="chatStore.getConversationsByAgent(agent.id).length"
          @click="$router.push(`/agent/${agent.id}`)"
        />
      </div>
    </section>

    <section class="agent-section">
      <h2 class="section-title">
        <el-icon><Grid /></el-icon>
        辅助智能体
      </h2>
      <div class="agent-grid">
        <AgentCard
          v-for="agent in supportAgents"
          :key="agent.id"
          :agent="agent"
          :conversation-count="chatStore.getConversationsByAgent(agent.id).length"
          @click="$router.push(`/agent/${agent.id}`)"
        />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { agents } from '@/agents/registry'
import { useSettingsStore } from '@/stores/settings'
import { useChatStore } from '@/stores/chat'
import AgentCard from '@/components/AgentCard.vue'

const settingsStore = useSettingsStore()
const chatStore = useChatStore()

const coreAgents = computed(() => agents.filter((a) => a.category === 'core'))
const supportAgents = computed(() => agents.filter((a) => a.category === 'support'))
</script>

<style scoped>
.dashboard {
  padding: 40px;
  max-width: 1200px;
  margin: 0 auto;
}

.dashboard-header {
  margin-bottom: 40px;
}

.dashboard-header h1 {
  font-size: 32px;
  font-weight: 800;
  background: linear-gradient(135deg, #e4e4e8, #a0a0b0);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 8px;
}

.subtitle {
  color: var(--text-secondary);
  font-size: 15px;
}

.status-bar {
  margin-top: 20px;
}

.model-lab-teaser {
  margin-bottom: 28px;
  max-width: 720px;
}

.teaser-link {
  color: var(--accent);
  font-weight: 600;
  text-decoration: none;
}

.teaser-link:hover {
  text-decoration: underline;
}

.agent-section {
  margin-bottom: 36px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 16px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-color);
}

.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}
</style>
