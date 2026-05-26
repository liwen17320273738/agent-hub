<template>
  <div class="design-token-panel" v-if="hasTokens">
    <div class="token-panel-header">
      <span class="token-panel-icon">🎨</span>
      <span class="token-panel-title">{{ t('designTokens.title') }}</span>
      <span v-if="applied" class="token-applied-badge">{{ t('designTokens.badgeApplied') }}</span>
      <el-button
        size="small"
        :type="applied ? 'warning' : 'primary'"
        class="token-apply-btn"
        @click="toggleApply"
      >
        {{ applied ? t('designTokens.clearBtn') : t('designTokens.applyBtn') }}
      </el-button>
    </div>

    <div class="token-grid" v-if="showTokens">
      <!-- Colors -->
      <div class="token-section" v-if="Object.keys(tokens.colors).length">
        <div class="token-section-title">{{ t('designTokens.colors') }}</div>
        <div class="token-items">
          <div
            v-for="(value, name) in tokens.colors"
            :key="'color-' + name"
            class="token-item"
          >
            <span class="color-swatch" :style="{ backgroundColor: value }" />
            <span class="token-name">{{ name }}</span>
            <code class="token-value">{{ value }}</code>
          </div>
        </div>
      </div>

      <!-- Typography -->
      <div class="token-section" v-if="Object.keys(tokens.typography).length">
        <div class="token-section-title">{{ t('designTokens.typography') }}</div>
        <div class="token-items">
          <div
            v-for="(value, name) in tokens.typography"
            :key="'typo-' + name"
            class="token-item"
          >
            <span class="token-name">{{ name }}</span>
            <code class="token-value">{{ value }}</code>
          </div>
        </div>
      </div>

      <!-- Spacing -->
      <div class="token-section" v-if="Object.keys(tokens.spacing).length">
        <div class="token-section-title">{{ t('designTokens.spacing') }}</div>
        <div class="token-items">
          <div
            v-for="(value, name) in tokens.spacing"
            :key="'space-' + name"
            class="token-item"
          >
            <span class="token-name">{{ name }}</span>
            <code class="token-value">{{ value }}</code>
          </div>
        </div>
      </div>
    </div>

    <div v-if="loading" class="token-loading">
      <el-icon class="is-loading"><Loading /></el-icon>
      {{ t('designTokens.loading') }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Loading } from '@element-plus/icons-vue'
import { useDesignTokens } from '@/composables/useDesignTokens'

const { t } = useI18n()

const props = defineProps<{
  taskId: string
}>()

const { tokens, loading, applied, apply, clear, hasTokens } = useDesignTokens()
const showTokens = ref(false)

function toggleApply() {
  if (applied.value) {
    clear()
  } else {
    showTokens.value = true
    apply(props.taskId)
  }
}

onMounted(async () => {
  if (props.taskId) {
    tokens.value = await (await import('@/services/designTokensApi')).fetchDesignTokens(props.taskId)
    showTokens.value = hasTokens()
  }
})

watch(() => props.taskId, async () => {
  if (props.taskId) {
    tokens.value = await (await import('@/services/designTokensApi')).fetchDesignTokens(props.taskId)
    showTokens.value = hasTokens()
  } else {
    clear()
    showTokens.value = false
  }
})
</script>

<style scoped>
.design-token-panel {
  background: #fff;
  border: 1px solid var(--el-border-color-lighter, #ebeef5);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
}

.token-panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.token-panel-icon {
  font-size: 16px;
}

.token-panel-title {
  font-weight: 600;
  font-size: 14px;
  flex: 1;
}

.token-applied-badge {
  display: inline-block;
  font-size: 11px;
  background: #e1f3d8;
  color: #529b2e;
  padding: 1px 8px;
  border-radius: 10px;
}

.token-apply-btn {
  margin-left: auto;
}

.token-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.token-section-title {
  font-size: 12px;
  font-weight: 600;
  color: #909399;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}

.token-items {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.token-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #f5f7fa;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 13px;
}

.color-swatch {
  display: inline-block;
  width: 16px;
  height: 16px;
  border-radius: 4px;
  border: 1px solid #d9d9d9;
  flex-shrink: 0;
}

.token-name {
  color: #606266;
}

.token-value {
  font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
  font-size: 12px;
  color: #909399;
}

.token-loading {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #909399;
  font-size: 13px;
  padding: 8px 0;
}
</style>
