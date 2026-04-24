<template>
  <div class="assets-view">
    <h1>{{ t('assets.title') }}</h1>
    <p class="view-subtitle">{{ t('assets.subtitle') }}</p>

    <el-tabs v-model="activeTab">
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
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const activeTab = ref('models')
</script>

<style scoped>
.assets-view {
  padding: 24px 32px;
  max-width: 1200px;
}

.assets-view h1 {
  font-size: 22px;
  margin-bottom: 4px;
}

.view-subtitle {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-bottom: 24px;
}

.asset-action {
  margin-bottom: 16px;
}
</style>
