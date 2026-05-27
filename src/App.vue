<template>
  <el-config-provider :locale="elLocale">
    <div class="app-container" :class="[themeClass, { 'is-login-route': isLoginRoute }]">
      <aside v-if="!isLoginRoute" class="app-sidebar">
      <div class="sidebar-header" @click="$router.push('/')">
        <svg class="brand-octopus" viewBox="0 0 64 64" width="28" height="28" aria-hidden="true">
          <!-- Octopus body -->
          <ellipse cx="32" cy="22" rx="10" ry="12" fill="currentColor" opacity="0.9" />
          <!-- Eyes -->
          <circle cx="28" cy="18" r="2.5" fill="var(--el-bg-color)" />
          <circle cx="36" cy="18" r="2.5" fill="var(--el-bg-color)" />
          <circle cx="28.5" cy="18.5" r="1" fill="currentColor" />
          <circle cx="36.5" cy="18.5" r="1" fill="currentColor" />
          <!-- Tentacles -->
          <path d="M24 30 Q18 38 16 48" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" class="tentacle t1" />
          <path d="M28 32 Q26 42 24 52" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" class="tentacle t2" />
          <path d="M32 33 Q32 44 32 54" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" class="tentacle t3" />
          <path d="M36 32 Q38 42 40 52" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" class="tentacle t4" />
          <path d="M40 30 Q46 38 48 48" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" class="tentacle t5" />
        </svg>
        <span class="sidebar-title">Agent Hub</span>
      </div>

      <WorkspaceSwitcher />

      <div class="sidebar-search-wrap">
        <el-input
          v-model="searchQuery"
          :placeholder="$t('nav.searchPlaceholder')"
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
        <div v-else-if="searchQuery.trim()" class="sidebar-search-empty">{{ $t('nav.searchEmpty') }}</div>
      </div>

      <nav class="sidebar-nav">
        <router-link to="/" class="nav-item" active-class="active" exact>
          <el-icon><HomeFilled /></el-icon>
          <span>{{ $t('nav.dashboard') }}</span>
        </router-link>

        <router-link to="/inbox" class="nav-item" active-class="active">
          <el-icon><Files /></el-icon>
          <span>{{ $t('nav.inbox') }}</span>
        </router-link>

        <router-link to="/team" class="nav-item" active-class="active">
          <el-icon><User /></el-icon>
          <span>{{ $t('nav.team') }}</span>
        </router-link>

        <router-link to="/workflow" class="nav-item" active-class="active">
          <el-icon><Share /></el-icon>
          <span>{{ $t('nav.workflow') }}</span>
        </router-link>

        <router-link to="/assets" class="nav-item" active-class="active">
          <el-icon><SetUp /></el-icon>
          <span>{{ $t('nav.assets') }}</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <div v-if="isEnterpriseBuild && authStore.user" class="sidebar-user">
          <span class="user-org" :title="authStore.user.orgName">{{ authStore.user.orgName }}</span>
          <span class="user-email" :title="authStore.user.email">{{ authStore.user.displayName || authStore.user.email }}</span>
          <el-button text type="danger" size="small" class="logout-btn" @click="handleLogout" aria-label="action">
            <el-icon><SwitchButton /></el-icon>
            {{ $t('nav.logout') }}
          </el-button>
        </div>
        <div class="nav-item theme-toggle" @click="toggleTheme">
          <el-icon><Sunny v-if="!isDarkMode" /><Moon v-else /></el-icon>
          <span>{{ isDarkMode ? $t('nav.darkMode') : $t('nav.lightMode') }}</span>
        </div>

        <el-dropdown trigger="click" @command="onPickLocale" placement="top-start">
          <div class="nav-item lang-toggle">
            <el-icon><Opportunity /></el-icon>
            <span>{{ currentLocaleLabel }}</span>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item
                v-for="code in SUPPORTED_LOCALES"
                :key="code"
                :command="code"
                :class="{ active: code === currentLocale }"
              >
                {{ LOCALE_LABEL[code] }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <router-link to="/settings" class="nav-item" active-class="active">
          <el-icon><Setting /></el-icon>
          <span>{{ $t('nav.settings') }}</span>
        </router-link>
      </div>
    </aside>

    <div class="app-body" v-if="!isLoginRoute">
      <SystemHealthBar />
      <main class="app-main">
        <ErrorBoundary>
          <router-view />
        </ErrorBoundary>
      </main>
    </div>
    <main v-else class="app-main app-main--full">
      <ErrorBoundary>
        <router-view />
      </ErrorBoundary>
    </main>
    </div>
  </el-config-provider>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'
import { SwitchButton, Sunny, Moon } from '@element-plus/icons-vue'
import type { ConversationSearchHit } from '@/agents/types'
import { useAgentStore } from '@/stores/agents'
import { useChatStore } from '@/stores/chat'
import { useAuthStore } from '@/stores/auth'
import { isEnterpriseBuild } from '@/services/enterpriseApi'
import { setLocale, getLocale, SUPPORTED_LOCALES, LOCALE_LABEL, type AppLocale } from '@/i18n'
import { useI18n } from 'vue-i18n'
import WorkspaceSwitcher from '@/components/workspace/WorkspaceSwitcher.vue'
import SystemHealthBar from '@/components/layout/SystemHealthBar.vue'
// Element Plus locale — 同步内置组件语言（分页/日期选择器/弹窗按钮等）
import elZhCn from 'element-plus/es/locale/lang/zh-cn.mjs'
import elEn from 'element-plus/es/locale/lang/en.mjs'
import elJa from 'element-plus/es/locale/lang/ja.mjs'
import elKo from 'element-plus/es/locale/lang/ko.mjs'
import elFr from 'element-plus/es/locale/lang/fr.mjs'
import elDe from 'element-plus/es/locale/lang/de.mjs'
import elEs from 'element-plus/es/locale/lang/es.mjs'

const EL_LOCALE_MAP: Record<string, typeof elZhCn> = {
  zh: elZhCn,
  en: elEn,
  ja: elJa,
  ko: elKo,
  fr: elFr,
  de: elDe,
  es: elEs,
}

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const chatStore = useChatStore()
const authStore = useAuthStore()
const searchQuery = ref('')

const isLoginRoute = computed(() => route.name === 'login')

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

const { locale: activeLocale } = useI18n()
const currentLocale = computed<AppLocale>(() => activeLocale.value as AppLocale)
const currentLocaleLabel = computed(() => LOCALE_LABEL[currentLocale.value] || currentLocale.value)

// Element Plus 内置组件语言随 app 语言同步切换
const elLocale = computed(() => EL_LOCALE_MAP[currentLocale.value] || elEn)

function onPickLocale(code: AppLocale) {
  if (code === currentLocale.value) return
  setLocale(code)
}
// Kept for backward compat callers (hotkeys, etc.)
function toggleLocale() {
  const idx = SUPPORTED_LOCALES.indexOf(currentLocale.value)
  const next = SUPPORTED_LOCALES[(idx + 1) % SUPPORTED_LOCALES.length]
  setLocale(next)
}
void toggleLocale

// ── Theme toggle ──
const THEME_KEY = 'agent-hub-theme'
const isDarkMode = ref(true)

function applyThemeClass(dark: boolean) {
  // Toggle on <html> so Element Plus teleported components (dropdowns, dialogs) inherit theme
  document.documentElement.classList.toggle('dark', dark)
}

function loadTheme(): boolean {
  try {
    const saved = localStorage.getItem(THEME_KEY)
    return saved !== 'light'  // default to dark
  } catch { return true }
}

function toggleTheme() {
  isDarkMode.value = !isDarkMode.value
  applyThemeClass(isDarkMode.value)
  try {
    localStorage.setItem(THEME_KEY, isDarkMode.value ? 'dark' : 'light')
  } catch { /* ignore */ }
}

const themeClass = computed(() => isDarkMode.value ? 'dark' : 'light')

// Apply theme on mount
isDarkMode.value = loadTheme()
applyThemeClass(isDarkMode.value)

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
  font-size: 12px;
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

.theme-toggle {
  cursor: pointer;
  user-select: none;
}

.sidebar-user {
  padding: 10px 12px 12px;
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 4px;
  font-size: 12px;
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

.app-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

.app-main--full {
  width: 100%;
  min-height: 100vh;
}

.is-login-route .app-main--full {
  max-width: none;
}

/* ── Brand Octopus ── */
.brand-octopus {
  flex-shrink: 0;
  color: var(--accent);
  transition: transform 0.3s ease;
}
.sidebar-header:hover .brand-octopus {
  transform: scale(1.08) rotate(-3deg);
}

.brand-octopus .tentacle {
  transform-origin: top center;
  animation: tentacle-wave 2.4s ease-in-out infinite;
}
.brand-octopus .t1 { animation-delay: 0s; }
.brand-octopus .t2 { animation-delay: 0.15s; }
.brand-octopus .t3 { animation-delay: 0.3s; }
.brand-octopus .t4 { animation-delay: 0.45s; }
.brand-octopus .t5 { animation-delay: 0.6s; }

@keyframes tentacle-wave {
  0%, 100% { transform: rotate(0deg) translateY(0); }
  25% { transform: rotate(4deg) translateY(1px); }
  75% { transform: rotate(-3deg) translateY(-1px); }
}

/* Pause animation when user prefers reduced motion */
@media (prefers-reduced-motion: reduce) {
  .brand-octopus .tentacle {
    animation: none;
  }
}
</style>
