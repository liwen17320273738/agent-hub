<template>
  <div class="ui-mockup-view">
    <!-- Degraded: HTML fallback only (no PNG) -->
    <div v-if="isDegraded && htmlPath" class="mockup-section degraded-banner">
      <el-alert type="warning" :closable="false" show-icon>
        {{ t('uiMockupCard.degradedHint') }}
      </el-alert>
    </div>

    <!-- Image mockup -->
    <div v-if="imagePath && !isDegraded" class="mockup-section">
      <div class="section-header">
        <span class="section-icon">🖼️</span>
        <span>{{ t('uiMockupCard.imageTitle') }}</span>
      </div>
      <div class="image-preview" @click="openImage">
        <img :src="imagePath" :alt="t('uiMockupCard.imageTitle')" @error="onImageError" />
        <div class="image-overlay">
          <span class="overlay-text">{{ t('uiMockupCard.openImage') }}</span>
        </div>
      </div>
    </div>

    <!-- HTML prototype -->
    <div v-if="htmlPath && showPrototype" class="mockup-section">
      <div class="section-header">
        <span class="section-icon">🖌️</span>
        <span>{{ t('uiMockupCard.prototypeTitle') }}</span>
        <a :href="htmlPath" target="_blank" rel="noopener" class="open-link">{{ t('uiMockupCard.openNewWindow') }} ↗</a>
      </div>
      <iframe
        :src="htmlPath"
        class="prototype-frame"
        sandbox="allow-scripts allow-downloads"
        loading="lazy"
        :title="t('uiMockupCard.prototypeTitle')"
      />
    </div>

    <!-- Design spec -->
    <div v-if="showSpec && specText" class="mockup-section">
      <div class="section-header">
        <span class="section-icon">📋</span>
        <span>{{ t('uiMockupCard.specTitle') }}</span>
      </div>
      <div class="spec-content">
        <pre>{{ specText }}</pre>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!imagePath && !htmlPath" class="empty-state">
      <div class="empty-icon">🎨</div>
      <p class="empty-title">{{ compact ? '' : t('uiMockupCard.emptyTitle') }}</p>
      <p class="empty-desc">
        {{ compact ? t('uiMockupCard.emptyCompact') : t('uiMockupCard.emptyFull') }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getAuthToken } from '@/services/api'
import { isImageAssetPath, normalizeWorktreeRelativePath, resolveWorktreeRawUrl } from '@/services/worktreeAssets'

const props = withDefaults(defineProps<{
  taskId: string
  shareToken?: string
  compact?: boolean
  /** When set, show only the matching section (used by artifact tabs). */
  focus?: 'ui_mockup' | 'ui_mockup_html' | 'all'
}>(), {
  focus: 'all',
})

const { t } = useI18n()

const imagePath = ref('')
const htmlPath = ref('')
const specText = ref('')
const isDegraded = ref(false)

const showPrototype = computed(() =>
  props.focus === 'all' || props.focus === 'ui_mockup_html' || (props.focus === 'ui_mockup' && isDegraded.value),
)
const showSpec = computed(() => props.focus === 'all' || props.focus === 'ui_spec')

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

function applyArtifact(art: Record<string, unknown> | undefined) {
  if (!art) return
  const meta = (art.metadata_json || art.metadata) as Record<string, unknown> | undefined
  const type = String(art.type_key || art.artifact_type || '')
  if (type === 'ui_spec' && art.content) {
    specText.value = String(art.content)
  }
  if (type === 'ui_mockup') {
    isDegraded.value = Boolean(meta?.degraded)
    const fp = String(meta?.filePath || art.storage_path || '')
    if (fp && isImageAssetPath(fp) && !isDegraded.value) {
      imagePath.value = resolveAssetUrl(fp)
    } else if (isDegraded.value && fp && fp.toLowerCase().endsWith('.html') && !htmlPath.value) {
      htmlPath.value = resolveAssetUrl(fp)
    } else if (art.content && !specText.value) {
      specText.value = String(art.content)
    }
  }
  if (type === 'ui_mockup_html') {
    const fp = String(meta?.filePath || art.storage_path || '')
    if (fp) htmlPath.value = resolveAssetUrl(fp)
  }
}

function findArtifact(artifacts: Record<string, unknown>[], type: string, stageId?: string) {
  return artifacts.find((a) => {
    const key = String(a.type_key || a.artifact_type || '')
    if (key !== type) return false
    if (stageId && a.stage_id !== stageId) return false
    return a.is_latest !== false
  })
}

async function loadFromShare() {
  const baseUrl = import.meta.env.VITE_API_BASE || '/api'
  const res = await fetch(`${baseUrl}/share/${props.shareToken}`)
  if (!res.ok) return
  const data = await res.json()
  const artifacts = (data.artifacts || []) as Record<string, unknown>[]
  applyArtifact(findArtifact(artifacts, 'ui_spec', 'design'))
  applyArtifact(findArtifact(artifacts, 'ui_mockup', 'design'))
  applyArtifact(findArtifact(artifacts, 'ui_mockup_html', 'design'))
}

async function loadFromTaskApi() {
  const baseUrl = import.meta.env.VITE_API_BASE || '/api'
  const token = getAuthToken()
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`

  const [specRes, imageRes, htmlRes] = await Promise.all([
    fetch(`${baseUrl}/tasks/${props.taskId}/artifacts/ui_spec`, { headers }),
    fetch(`${baseUrl}/tasks/${props.taskId}/artifacts/ui_mockup`, { headers }),
    fetch(`${baseUrl}/tasks/${props.taskId}/artifacts/ui_mockup_html`, { headers }),
  ])

  if (specRes.ok) {
    const specData = await specRes.json()
    if (specData.content) specText.value = specData.content
  }
  if (imageRes.ok) {
    applyArtifact(await imageRes.json())
  }
  if (htmlRes.ok) {
    applyArtifact(await htmlRes.json())
  }
}

async function loadMockup() {
  imagePath.value = ''
  htmlPath.value = ''
  specText.value = ''
  isDegraded.value = false
  try {
    if (props.shareToken) {
      await loadFromShare()
    } else {
      await loadFromTaskApi()
    }
  } catch (err) {
    console.error('[ui-mockup] fetch error:', err)
  }
}

onMounted(() => loadMockup())
watch(() => [props.taskId, props.shareToken, props.focus], () => loadMockup())

function openImage() {
  if (imagePath.value) {
    window.open(imagePath.value, '_blank', 'noopener')
  }
}

function onImageError() {
  imagePath.value = ''
}
</script>

<style scoped>
.ui-mockup-view {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 8px;
}

.mockup-section {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  overflow: hidden;
}

.degraded-banner {
  padding: 12px 16px;
  background: transparent;
  border: none;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  font-size: 14px;
  font-weight: 500;
}

.section-icon {
  font-size: 18px;
}

.open-link {
  margin-left: auto;
  color: #818cf8;
  text-decoration: none;
  font-size: 13px;
  font-weight: 400;
}

.open-link:hover {
  text-decoration: underline;
}

.image-preview {
  position: relative;
  cursor: pointer;
  overflow: hidden;
}

.image-preview img {
  width: 100%;
  max-height: 500px;
  object-fit: contain;
  display: block;
  background: #0a0a1a;
}

.image-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.3s;
}

.image-preview:hover .image-overlay {
  background: rgba(0, 0, 0, 0.4);
}

.overlay-text {
  color: #fff;
  font-size: 14px;
  opacity: 0;
  transition: opacity 0.3s;
  padding: 8px 16px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.5);
}

.image-preview:hover .overlay-text {
  opacity: 1;
}

.prototype-frame {
  display: block;
  width: 100%;
  height: min(600px, 70vh);
  border: none;
  background: #fff;
}

.spec-content {
  padding: 20px;
  max-height: 400px;
  overflow-y: auto;
}

.spec-content pre {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.8);
  white-space: pre-wrap;
  word-break: break-word;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.empty-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 8px;
}

.empty-desc {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.5);
  max-max-width: 400px; width: 100%;
  margin: 0 auto;
}
</style>
