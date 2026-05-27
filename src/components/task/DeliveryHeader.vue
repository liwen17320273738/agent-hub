<template>
  <section v-if="show" class="delivery-header" :class="{ 'is-ready': hasPreviewUrl }">
    <div class="dh-main">
      <div class="dh-icon">{{ hasPreviewUrl ? '🚀' : '📦' }}</div>
      <div class="dh-body">
        <div class="dh-title">
          {{ hasPreviewUrl ? $t('deliveryHeader.titleLive') : $t('deliveryHeader.titlePending') }}
        </div>
        <div class="dh-summary">{{ summary }}</div>
        <div v-if="hasPreviewUrl" class="dh-url-row">
          <a :href="previewUrl" target="_blank" rel="noopener" class="dh-url">
            {{ previewUrl }}
          </a>
          <el-tag :type="healthTagType" size="small" effect="dark" class="dh-health">
            {{ healthLabel }}
          </el-tag>
        </div>
      </div>
      <div class="dh-actions">
        <el-button
          v-if="hasPreviewUrl"
          type="primary"
          size="default"
          @click="openPreview"
        >
          {{ $t('deliveryHeader.tryItOut') }}
        </el-button>
        <el-button size="default" @click="emit('share')">
          {{ $t('deliveryHeader.share') }}
        </el-button>
        <el-button
          v-if="canAccept"
          type="success"
          size="default"
          @click="emit('accept')"
        >
          {{ $t('deliveryHeader.accept') }}
        </el-button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getAuthToken } from '@/services/api'

interface ArtifactRow {
  artifact_type: string
  content?: string
  metadata_json?: Record<string, unknown> | null
  storage_path?: string
}

const props = defineProps<{
  taskId: string
  status?: string
  artifactCount?: number
}>()

const emit = defineEmits<{
  (e: 'share'): void
  (e: 'accept'): void
}>()

const { t } = useI18n()

const previewUrl = ref('')
const healthStatus = ref('')
const acceptanceSummary = ref('')
const loaded = ref(false)

const hasPreviewUrl = computed(() => !!previewUrl.value)
const show = computed(() => loaded.value && (hasPreviewUrl.value || (props.artifactCount ?? 0) > 0))

const summary = computed(() => {
  if (acceptanceSummary.value) return acceptanceSummary.value
  if (hasPreviewUrl.value) {
    return t('deliveryHeader.fallbackSummaryLive')
  }
  return t('deliveryHeader.fallbackSummaryDocs', { n: props.artifactCount ?? 0 })
})

const canAccept = computed(() =>
  props.status === 'awaiting_final_acceptance' || props.status === 'completed',
)

const healthTagType = computed(() => {
  switch (healthStatus.value) {
    case 'healthy': return 'success'
    case 'unhealthy': return 'danger'
    default: return 'warning'
  }
})

const healthLabel = computed(() => {
  const key = healthStatus.value || 'unknown'
  return t(`deploy.health_${key}`)
})

function openPreview(): void {
  if (previewUrl.value) {
    window.open(previewUrl.value, '_blank', 'noopener')
  }
}

async function loadArtifacts(): Promise<void> {
  try {
    const baseUrl = import.meta.env.VITE_API_BASE || '/api'
    const token = getAuthToken()
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`

    const res = await fetch(`${baseUrl}/tasks/${props.taskId}/artifacts`, { headers })
    if (!res.ok) return
    const data = await res.json()
    const arts: ArtifactRow[] = data.artifacts || []

    const previewArt = arts.find(a => a.artifact_type === 'preview_url')
    if (previewArt) {
      let meta = previewArt.metadata_json as Record<string, unknown> | undefined
      if (!meta && previewArt.content) {
        try { meta = JSON.parse(previewArt.content) } catch { /* ignore */ }
      }
      previewUrl.value = String(meta?.url || '')
      healthStatus.value = String(meta?.health_status || '')
    }

    const acceptArt = arts.find(a => a.artifact_type === 'acceptance')
    if (acceptArt) {
      const meta = acceptArt.metadata_json as Record<string, unknown> | undefined
      const metaSummary = meta?.summary || meta?.one_liner
      if (metaSummary) {
        acceptanceSummary.value = String(metaSummary)
      } else if (acceptArt.content) {
        // first non-empty line of acceptance doc, capped to keep header compact
        const firstLine = acceptArt.content.split('\n').map(s => s.trim()).find(Boolean) || ''
        acceptanceSummary.value = firstLine.replace(/^#+\s*/, '').slice(0, 140)
      }
    }
  } finally {
    loaded.value = true
  }
}

onMounted(loadArtifacts)
watch(() => props.taskId, loadArtifacts)
</script>

<style scoped>
.delivery-header {
  margin: 0 0 24px;
  padding: 20px 24px;
  border-radius: 12px;
  background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%);
  border: 1px solid #e2e8f0;
}
.delivery-header.is-ready {
  background: linear-gradient(135deg, #ecfdf5 0%, #e0f2fe 100%);
  border-color: #bbf7d0;
}
.dh-main {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}
.dh-icon {
  font-size: 32px;
  line-height: 1;
  flex-shrink: 0;
}
.dh-body {
  flex: 1;
  min-width: 0;
}
.dh-title {
  font-size: 16px;
  font-weight: 600;
  color: #111827;
  margin-bottom: 4px;
}
.dh-summary {
  font-size: 14px;
  color: #4b5563;
  margin-bottom: 8px;
}
.dh-url-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.dh-url {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  color: #2563eb;
  text-decoration: none;
  word-break: break-all;
}
.dh-url:hover { text-decoration: underline; }
.dh-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
  align-self: center;
}
@media (max-max-width: 720px; width: 100%) {
  .dh-main { flex-direction: column; }
  .dh-actions { width: 100%; }
}
</style>
