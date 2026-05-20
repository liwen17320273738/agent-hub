<template>
  <el-card class="deploy-card" shadow="never">
    <template #header>
      <span class="card-title">{{ $t('deploy.deployCardTitle') }}</span>
    </template>

    <div v-if="loading" class="deploy-loading">
      <el-skeleton :rows="3" animated />
    </div>

    <div v-else-if="error" class="deploy-error">
      <el-empty :description="$t('deploy.noDeployData')" />
    </div>

    <div v-else class="deploy-content">
      <!-- URL row -->
      <div class="deploy-row">
        <span class="deploy-label">{{ $t('deploy.previewUrl') }}</span>
        <div class="deploy-value">
          <a v-if="deployUrl" :href="deployUrl" target="_blank" rel="noopener" class="deploy-link">
            {{ deployUrl }}
            <el-icon class="external-icon"><Link /></el-icon>
          </a>
          <span v-else class="text-muted">{{ $t('deploy.notAvailable') }}</span>
        </div>
      </div>

      <!-- Health status row -->
      <div class="deploy-row">
        <span class="deploy-label">{{ $t('deploy.healthStatus') }}</span>
        <div class="deploy-value">
          <el-tag :type="healthTagType" size="small" effect="dark">
            {{ healthLabel }}
          </el-tag>
        </div>
      </div>

      <!-- Provider row -->
      <div class="deploy-row">
        <span class="deploy-label">{{ $t('deploy.provider') }}</span>
        <div class="deploy-value">{{ providerLabel }}</div>
      </div>

      <!-- Deployed at row -->
      <div class="deploy-row" v-if="deployedAt">
        <span class="deploy-label">{{ $t('deploy.deployedAt') }}</span>
        <div class="deploy-value">{{ deployedAt }}</div>
      </div>

      <!-- Screenshot -->
      <div v-if="screenshotB64" class="deploy-screenshot">
        <el-divider />
        <div class="deploy-section-title">{{ $t('deploy.deployedScreenshot') }}</div>
        <el-image
          :src="'data:image/png;base64,' + screenshotB64"
          fit="contain"
          class="deploy-image"
          :preview-src-list="['data:image/png;base64,' + screenshotB64]"
        />
      </div>

      <!-- Open preview button -->
      <div v-if="deployUrl" class="deploy-actions">
        <el-button type="primary" size="small" @click="openPreview">
          {{ $t('deploy.openPreview') }}
        </el-button>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { getAuthToken } from '@/services/api'
import { Link } from '@element-plus/icons-vue'

const props = defineProps<{
  taskId: string
  shareToken?: string
}>()

const loading = ref(true)
const error = ref(false)

const deployUrl = ref('')
const healthStatus = ref('')
const provider = ref('')
const deployedAt = ref('')
const screenshotB64 = ref('')

onMounted(async () => {
  try {
    const baseUrl = import.meta.env.VITE_API_BASE || '/api'
    let arts: any[] = []

    if (props.shareToken) {
      // Public share mode — use share API
      const artRes = await fetch(`${baseUrl}/share/${props.shareToken}`)
      if (!artRes.ok) return
      const data = await artRes.json()
      arts = (data.artifacts || []).concat(data.docs?.map((d: any) => ({
        artifact_type: d.name?.replace('.md', '').replace(/^\d+-/, ''),
        metadata_json: d,
        content: d.content || '',
        storage_path: d.storage_path || '',
      })) || [])
    } else {
      const token = getAuthToken()
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`

      const artRes = await fetch(
        `${baseUrl}/tasks/${props.taskId}/artifacts`,
        { headers },
      )
      if (!artRes.ok) return
      const artData = await artRes.json()
      arts = artData.artifacts || []
    }

    const previewArt = arts.find((a: any) => a.artifact_type === 'preview_url')
    if (previewArt) {
      let meta = previewArt.metadata_json
      if (!meta && previewArt.content) {
        try {
          meta = JSON.parse(previewArt.content)
        } catch { /* ignore */ }
      }
      deployUrl.value = meta?.url || ''
      healthStatus.value = meta?.health_status || ''
      provider.value = meta?.provider || ''
      deployedAt.value = meta?.deployed_at || ''
    }

    const ssArt = arts.find((a: any) =>
      a.artifact_type === 'screenshot' && a.storage_path?.includes('deployed_screenshot')
    )
    if (ssArt?.content) {
      screenshotB64.value = ssArt.content
    }
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
})

const healthTagType = computed(() => {
  switch (healthStatus.value) {
    case 'healthy': return 'success'
    case 'unhealthy': return 'danger'
    default: return 'warning'
  }
})

const healthLabel = computed(() => {
  switch (healthStatus.value) {
    case 'healthy': return '正常'
    case 'unhealthy': return '异常'
    default: return '未知'
  }
})

const providerLabel = computed(() => {
  if (provider.value === 'vercel') return 'Vercel'
  if (provider.value === 'local') return 'Local'
  return provider.value || '-'
})

function openPreview() {
  if (deployUrl.value) {
    window.open(deployUrl.value, '_blank')
  }
}
</script>

<style scoped>
.deploy-card {
  margin-bottom: 20px;
}
.card-title {
  font-weight: 600;
  font-size: 16px;
}
.deploy-loading,
.deploy-error {
  padding: 20px 0;
}
.deploy-content {
  padding: 4px 0;
}
.deploy-row {
  display: flex;
  align-items: center;
  padding: 8px 0;
  gap: 12px;
}
.deploy-label {
  flex-shrink: 0;
  min-width: 80px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.deploy-value {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  word-break: break-all;
}
.deploy-link {
  color: var(--el-color-primary);
  text-decoration: none;
}
.deploy-link:hover {
  text-decoration: underline;
}
.external-icon {
  font-size: 13px;
}
.text-muted {
  color: var(--el-text-color-placeholder);
}
.deploy-section-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--el-text-color-primary);
}
.deploy-image {
  max-width: 100%;
  max-height: 360px;
  border-radius: 6px;
  border: 1px solid var(--el-border-color-lighter);
}
.deploy-actions {
  margin-top: 16px;
}
</style>
