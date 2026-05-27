<template>
  <div class="arch-diagram-view">
    <!-- Loading -->
    <div v-if="loading" class="arch-loading">
      <el-icon class="spin-icon" :size="20"><Loading /></el-icon>
      <span>{{ t('taskArchDiagram.loading') }}</span>
    </div>

    <!-- Diagram iframe (HTML with Mermaid.js) -->
    <div v-else-if="htmlPath" class="arch-diagram-frame-wrapper">
      <div class="frame-header">
        <span class="frame-icon">📐</span>
        <span>{{ t('taskArchDiagram.title') }}</span>
        <div class="frame-actions">
          <a :href="htmlPath" target="_blank" rel="noopener" class="open-link" :title="t('taskArchDiagram.openNewWindow')">
            <el-icon><FullScreen /></el-icon> {{ t('taskArchDiagram.openNewWindow') }}
          </a>
        </div>
      </div>
      <iframe
        :src="htmlPath"
        class="arch-diagram-frame"
        sandbox="allow-scripts allow-downloads"
        loading="lazy"
        :title="t('taskArchDiagram.title')"
      />
    </div>

    <!-- Mermaid code fallback -->
    <div v-else-if="mermaidCode" class="arch-fallback">
      <div class="fallback-header">
        <span class="frame-icon">📐</span>
        <span>{{ t('taskArchDiagram.mermaidTitle') }}</span>
      </div>
      <pre class="mermaid-code">{{ mermaidCode }}</pre>
    </div>

    <!-- Empty state -->
    <div v-else class="arch-empty">
      <div class="empty-icon">📐</div>
      <p class="empty-title">{{ compact ? '' : t('taskArchDiagram.emptyTitle') }}</p>
      <p class="empty-desc">
        {{ compact ? t('taskArchDiagram.emptyCompact') : t('taskArchDiagram.emptyFull') }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Loading, FullScreen } from '@element-plus/icons-vue'
import { getAuthToken } from '@/services/api'
import { normalizeWorktreeRelativePath, resolveWorktreeRawUrl } from '@/services/worktreeAssets'

const props = defineProps<{
  taskId: string
  shareToken?: string
  compact?: boolean
}>()

const { t } = useI18n()

const loading = ref(true)
const htmlPath = ref('')
const mermaidCode = ref('')

function resolveAssetUrl(path: string): string {
  if (!path) return ''
  if (props.shareToken) {
    const baseUrl = import.meta.env.VITE_API_BASE || '/api'
    const rel = normalizeWorktreeRelativePath(path, props.taskId)
    const encoded = rel.split('/').map((segment) => encodeURIComponent(segment)).join('/')
    return `${baseUrl}/share/${props.shareToken}/worktree/raw/${encoded}`
  }
  return resolveWorktreeRawUrl(props.taskId, path)
}

function applyDiagramArtifact(data: Record<string, unknown>) {
  const meta = (data.metadata_json || data.metadata) as Record<string, unknown> | undefined
  const fp = String(meta?.filePath || data.storage_path || '')
  if (fp) {
    htmlPath.value = resolveAssetUrl(fp)
  } else if (data.content) {
    mermaidCode.value = String(data.content)
  }
}

async function loadFromShare() {
  const baseUrl = import.meta.env.VITE_API_BASE || '/api'
  const res = await fetch(`${baseUrl}/share/${props.shareToken}`)
  if (!res.ok) return
  const payload = await res.json()
  const art = ((payload.artifacts || []) as Record<string, unknown>[]).find((a) => {
    const key = String(a.type_key || a.artifact_type || '')
    return key === 'architecture_diagram' && (a.stage_id === 'architecture' || !a.stage_id)
  })
  if (art) applyDiagramArtifact(art)
}

async function loadFromTaskApi() {
  const baseUrl = import.meta.env.VITE_API_BASE || '/api'
  const token = getAuthToken()
  const res = await fetch(
    `${baseUrl}/tasks/${props.taskId}/artifacts/architecture_diagram`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  )
  if (!res.ok) return
  applyDiagramArtifact(await res.json())
}

async function fetchArchDiagram() {
  loading.value = true
  htmlPath.value = ''
  mermaidCode.value = ''
  try {
    if (props.shareToken) {
      await loadFromShare()
    } else {
      await loadFromTaskApi()
    }
  } catch {
    // silent
  } finally {
    loading.value = false
  }
}

onMounted(() => fetchArchDiagram())
watch(() => [props.taskId, props.shareToken], () => fetchArchDiagram())
</script>

<style scoped>
.arch-diagram-view {
  padding: 8px 0;
}

.arch-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 24px;
  color: var(--el-text-color-secondary);
}

.spin-icon {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.arch-diagram-frame-wrapper {
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  background: #0f0f1a;
}

.frame-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: var(--el-fill-color-light);
  font-size: 14px;
  font-weight: 500;
}

.frame-actions {
  margin-left: auto;
}

.open-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--el-color-primary);
  text-decoration: none;
  font-size: 13px;
}

.arch-diagram-frame {
  display: block;
  width: 100%;
  height: min(520px, 65vh);
  border: none;
  background: #0f0f1a;
}

.arch-fallback {
  border-radius: 12px;
  border: 1px solid var(--el-border-color-lighter);
  overflow: hidden;
}

.fallback-header {
  padding: 12px 16px;
  background: var(--el-fill-color-light);
  font-size: 14px;
  font-weight: 500;
}

.mermaid-code {
  margin: 0;
  padding: 16px;
  font-size: 12px;
  line-height: 1.6;
  overflow-x: auto;
  max-height: 400px;
}

.arch-empty {
  text-align: center;
  padding: 48px 16px;
  color: var(--el-text-color-secondary);
}

.empty-icon {
  font-size: 40px;
  margin-bottom: 12px;
}

.empty-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 6px;
}

.empty-desc {
  font-size: 13px;
  max-max-width: 360px; width: 100%;
  margin: 0 auto;
}
</style>
