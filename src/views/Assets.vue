<template>
  <div class="assets-view">
    <h1>{{ t('assets.title') }}</h1>
    <p class="view-subtitle">{{ t('assets.subtitle') }}</p>

    <el-tabs v-model="activeTab">
      <el-tab-pane :label="t('assets.tabs.relay')" name="relay" lazy>
        <RelayGatewayPanel />
      </el-tab-pane>

      <el-tab-pane :label="t('assets.tabs.models')" name="models">
        <div class="asset-action">
          <el-button type="primary" @click="$router.push('/model-lab')">{{ t('assets.buttons.modelLab') }}</el-button>
        </div>
        <el-empty :description="t('assets.empty.models')" />
      </el-tab-pane>

      <el-tab-pane :label="t('assets.tabs.skills')" name="skills">
        <div class="asset-action">
          <el-button type="primary" @click="$router.push('/skills')">{{ t('assets.buttons.skillCenter') }}</el-button>
        </div>
        <el-empty :description="t('assets.empty.skills')" />
      </el-tab-pane>

      <el-tab-pane
        v-if="authStore.user?.role === 'admin'"
        :label="t('assets.tabs.skillReview')"
        name="skillReview"
        lazy
      >
        <p class="tab-lead">{{ t('assets.skillReviewLead') }}</p>
        <AdminSkillReview embedded />
      </el-tab-pane>

      <el-tab-pane :label="t('assets.tabs.mcp')" name="mcp">
        <div class="asset-action">
          <el-button type="primary" @click="$router.push('/mcp-servers')">{{ t('assets.buttons.mcp') }}</el-button>
        </div>
        <el-empty :description="t('assets.empty.mcp')" />
      </el-tab-pane>

      <el-tab-pane :label="t('assets.tabs.eval')" name="eval">
        <div class="asset-action">
          <el-button type="primary" @click="$router.push('/eval-lab')">{{ t('assets.buttons.evalLab') }}</el-button>
        </div>
        <el-empty :description="t('assets.empty.eval')" />
      </el-tab-pane>

      <el-tab-pane :label="t('assets.tabs.codebase')" name="codebase">
        <div class="asset-action">
          <el-button type="primary" @click="$router.push('/codebase-lab')">{{ t('assets.buttons.codebaseLab') }}</el-button>
        </div>
        <el-empty :description="t('assets.empty.codebase')" />
      </el-tab-pane>

      <el-tab-pane :label="t('assets.tabs.observability')" name="observability">
        <div class="asset-action">
          <el-button type="primary" @click="$router.push('/insights/observability')">{{ t('assets.buttons.observability') }}</el-button>
        </div>
        <el-empty :description="t('assets.empty.observability')" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import AdminSkillReview from '@/views/AdminSkillReview.vue'

import RelayGatewayPanel from '@/components/assets/RelayGatewayPanel.vue'

const BASE_TABS = ['models', 'skills', 'relay', 'mcp', 'eval', 'codebase', 'observability'] as const

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

function normalizeTab(fromQuery?: string): string {
  const isAdmin = authStore.user?.role === 'admin'
  if (fromQuery === 'skillReview') {
    return isAdmin ? 'skillReview' : 'models'
  }
  if (fromQuery && (BASE_TABS as readonly string[]).includes(fromQuery)) {
    return fromQuery
  }
  return 'models'
}

const activeTab = ref(normalizeTab(typeof route.query.tab === 'string' ? route.query.tab : undefined))

watch(
  () => [authStore.initialized, authStore.user?.role] as const,
  () => {
    if (!authStore.initialized) return
    const next = normalizeTab(typeof route.query.tab === 'string' ? route.query.tab : undefined)
    if (next !== activeTab.value) activeTab.value = next
  },
)

watch(
  () => route.query.tab,
  (tab) => {
    const next = normalizeTab(typeof tab === 'string' ? tab : undefined)
    if (next !== activeTab.value) activeTab.value = next
  },
)

watch(activeTab, (name) => {
  const want = name === 'models' ? undefined : name
  const cur = typeof route.query.tab === 'string' ? route.query.tab : undefined
  if (want === cur || (want === undefined && cur === undefined)) return
  const q = { ...route.query } as Record<string, string | string[]>
  if (want === undefined) delete q.tab
  else q.tab = want
  router.replace({ path: route.path, query: q }).catch(() => {})
})
</script>

<style scoped>
.assets-view {
  box-sizing: border-box;
  width: 100%;
  padding: clamp(16px, 2.5vw, 28px) clamp(16px, 3vw, 36px);
}

.assets-view h1 {
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -0.4px;
  margin-bottom: 4px;
  background: linear-gradient(135deg, var(--text-primary), var(--text-secondary));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.view-subtitle {
  color: var(--text-muted);
  font-size: 14px;
  margin-bottom: 24px;
}

.asset-action {
  margin-bottom: 18px;
}

.tab-lead {
  margin: 0 0 16px;
  font-size: 13px;
  color: var(--text-muted);
  line-height: 1.6;
}
</style>
