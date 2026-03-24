<template>
  <div class="app-container dark">
    <aside class="app-sidebar">
      <div class="sidebar-header" @click="$router.push('/')">
        <el-icon :size="28"><Monitor /></el-icon>
        <span class="sidebar-title">Agent Hub</span>
      </div>

      <div class="sidebar-search-wrap">
        <el-input
          v-model="searchQuery"
          placeholder="搜索全部会话…"
          clearable
          size="small"
          class="sidebar-search"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <div v-if="searchQuery.trim() && searchHits.length" class="sidebar-search-results">
          <div
            v-for="h in searchHits"
            :key="h.conversationId"
            class="search-hit"
            @click="openSearchHit(h)"
          >
            <div class="search-hit-title">{{ h.title }}</div>
            <div class="search-hit-meta">{{ agentName(h.agentId) }}</div>
            <div class="search-hit-snippet">{{ h.snippet }}</div>
          </div>
        </div>
        <div v-else-if="searchQuery.trim()" class="sidebar-search-empty">无匹配会话</div>
      </div>

      <nav class="sidebar-nav">
        <router-link to="/" class="nav-item" active-class="active" exact>
          <el-icon><HomeFilled /></el-icon>
          <span>控制台</span>
        </router-link>

        <router-link to="/model-lab" class="nav-item" active-class="active">
          <el-icon><DataAnalysis /></el-icon>
          <span>模型实验室</span>
        </router-link>

        <div class="nav-group-label">核心智能体</div>
        <router-link
          v-for="agent in coreAgents"
          :key="agent.id"
          :to="`/agent/${agent.id}`"
          class="nav-item"
          active-class="active"
        >
          <el-icon :style="{ color: agent.color }">
            <component :is="agent.icon" />
          </el-icon>
          <span>{{ agent.name }}</span>
        </router-link>

        <div class="nav-group-label">辅助智能体</div>
        <router-link
          v-for="agent in supportAgents"
          :key="agent.id"
          :to="`/agent/${agent.id}`"
          class="nav-item"
          active-class="active"
        >
          <el-icon :style="{ color: agent.color }">
            <component :is="agent.icon" />
          </el-icon>
          <span>{{ agent.name }}</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <router-link to="/settings" class="nav-item" active-class="active">
          <el-icon><Setting /></el-icon>
          <span>设置</span>
        </router-link>
      </div>
    </aside>

    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { agents } from '@/agents/registry'
import type { ConversationSearchHit } from '@/agents/types'
import { useChatStore } from '@/stores/chat'

const router = useRouter()
const chatStore = useChatStore()
const searchQuery = ref('')

const coreAgents = computed(() => agents.filter((a) => a.category === 'core'))
const supportAgents = computed(() => agents.filter((a) => a.category === 'support'))

const searchHits = computed(() => chatStore.searchConversations(searchQuery.value))

function agentName(id: string) {
  return agents.find((a) => a.id === id)?.name ?? id
}

function openSearchHit(h: ConversationSearchHit) {
  searchQuery.value = ''
  router.push({
    name: 'agent-chat',
    params: { id: h.agentId },
    query: { c: h.conversationId },
  })
}
</script>

<style scoped>
.sidebar-search-wrap {
  padding: 0 12px 10px;
  border-bottom: 1px solid var(--border-color);
}

.sidebar-search :deep(.el-input__wrapper) {
  border-radius: 8px;
}

.sidebar-search-results {
  margin-top: 8px;
  max-height: 220px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.search-hit {
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--bg-tertiary);
  cursor: pointer;
  font-size: 12px;
  border: 1px solid transparent;
}

.search-hit:hover {
  border-color: var(--accent);
}

.search-hit-title {
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.search-hit-meta {
  font-size: 11px;
  color: var(--accent);
  margin: 2px 0;
}

.search-hit-snippet {
  color: var(--text-muted);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.sidebar-search-empty {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 8px;
  padding: 0 4px;
}
</style>
