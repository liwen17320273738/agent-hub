<template>
  <div class="app-container dark" :class="{ 'is-login-route': isLoginRoute }">
    <aside v-if="!isLoginRoute" class="app-sidebar">
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

        <router-link to="/wayne-stack" class="nav-item" active-class="active">
          <el-icon><Connection /></el-icon>
          <span>Wayne Stack</span>
        </router-link>

        <router-link to="/wayne-console" class="nav-item" active-class="active">
          <el-icon><Operation /></el-icon>
          <span>Wayne Console</span>
        </router-link>

        <router-link to="/pipeline" class="nav-item" active-class="active">
          <el-icon><Aim /></el-icon>
          <span>AI 军团流水线</span>
        </router-link>

        <router-link to="/agents-console" class="nav-item" active-class="active">
          <el-icon><User /></el-icon>
          <span>专家工作台</span>
        </router-link>

        <router-link to="/mcp-servers" class="nav-item" active-class="active">
          <el-icon><Link /></el-icon>
          <span>MCP 服务器</span>
        </router-link>

        <router-link to="/eval-lab" class="nav-item" active-class="active">
          <el-icon><DataLine /></el-icon>
          <span>评测实验室</span>
        </router-link>

        <router-link to="/plan-inbox" class="nav-item" active-class="active">
          <el-icon><Files /></el-icon>
          <span>计划收件箱</span>
        </router-link>

        <router-link to="/codebase-lab" class="nav-item" active-class="active">
          <el-icon><Reading /></el-icon>
          <span>代码索引</span>
        </router-link>

        <router-link to="/insights/digest" class="nav-item" active-class="active">
          <el-icon><DataAnalysis /></el-icon>
          <span>Agent 周报</span>
        </router-link>

        <router-link to="/skills" class="nav-item" active-class="active">
          <el-icon><SetUp /></el-icon>
          <span>技能中心</span>
        </router-link>

      
        <!-- <a
          class="nav-item"
          :href="beihaiTripStandaloneUrl"
          target="_blank"
          rel="noopener noreferrer"
        > 
          <el-icon><Tickets /></el-icon>
          <span>北海行程</span>
        </a> -->

        <div class="nav-group-label">核心智能体</div>
        <router-link
          v-for="agent in coreAgents"
          :key="agent.id"
          :to="`/agent/${agent.id}`"
          class="nav-item"
          active-class="active"
        >
          <el-icon :style="{ color: agent.color }">
            <component :is="resolveAgentIcon(agent.icon)" />
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
            <component :is="resolveAgentIcon(agent.icon)" />
          </el-icon>
          <span>{{ agent.name }}</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <div v-if="isEnterpriseBuild && authStore.user" class="sidebar-user">
          <span class="user-org" :title="authStore.user.orgName">{{ authStore.user.orgName }}</span>
          <span class="user-email" :title="authStore.user.email">{{ authStore.user.displayName || authStore.user.email }}</span>
          <el-button text type="danger" size="small" class="logout-btn" @click="handleLogout">
            <el-icon><SwitchButton /></el-icon>
            退出
          </el-button>
        </div>
        <router-link to="/settings" class="nav-item" active-class="active">
          <el-icon><Setting /></el-icon>
          <span>设置</span>
        </router-link>
      </div>
    </aside>

    <main class="app-main" :class="{ 'app-main--full': isLoginRoute }">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { Connection, Operation, SetUp, SwitchButton } from '@element-plus/icons-vue'
import { resolveAgentIcon } from '@/utils/agentIcon'
import type { ConversationSearchHit } from '@/agents/types'
import { useAgentStore } from '@/stores/agents'
import { useChatStore } from '@/stores/chat'
import { useAuthStore } from '@/stores/auth'
import { isEnterpriseBuild } from '@/services/enterpriseApi'

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const chatStore = useChatStore()
const authStore = useAuthStore()
const searchQuery = ref('')

const isLoginRoute = computed(() => route.name === 'login')

const { coreAgents, supportAgents } = storeToRefs(agentStore)

const searchHits = computed(() => chatStore.searchConversations(searchQuery.value))

function agentName(id: string) {
  return agentStore.getAgent(id)?.name ?? id
}

onMounted(() => {
  if (authStore.isLoggedIn && !agentStore.loaded) {
    agentStore.fetchAgents()
  }
})

function openSearchHit(h: ConversationSearchHit) {
  searchQuery.value = ''
  router.push({
    name: 'agent-chat',
    params: { id: h.agentId },
    query: { c: h.conversationId },
  })
}

async function handleLogout() {
  await authStore.logout()
  router.push({ name: 'login' })
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

.sidebar-user {
  padding: 10px 12px 12px;
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 4px;
  font-size: 11px;
  color: var(--text-muted);
}

.user-org {
  display: block;
  font-weight: 600;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-email {
  display: block;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.logout-btn {
  margin-top: 8px;
  padding: 0 !important;
}

.app-main--full {
  width: 100%;
  min-height: 100vh;
}

.is-login-route .app-main--full {
  max-width: none;
}
</style>
