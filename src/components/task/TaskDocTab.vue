<template>
  <div class="task-doc-tab">
    <div class="doc-toolbar" v-if="versions.length > 1 || hasContent">
      <div class="doc-version-select" v-if="versions.length > 1">
        <el-select
          v-model="selectedVersion"
          size="small"
          style="width: 200px"
          @change="handleVersionChange"
        >
          <el-option
            v-for="v in versions"
            :key="v.version"
            :label="`v${v.version} ${v.status === 'superseded' ? '(已打回)' : v.status === 'active' ? '(当前)' : ''}`"
            :value="v.version"
          />
        </el-select>
        <el-tag
          v-if="currentArtifact?.status === 'superseded'"
          type="warning"
          size="small"
          style="margin-left: 8px"
        >
          已打回
        </el-tag>
      </div>
      <div class="doc-meta" v-if="currentArtifact?.updated_at">
        <span class="meta-time">{{ formatTime(currentArtifact.updated_at) }}</span>
      </div>
    </div>

    <div v-if="loading" class="doc-loading">
      <el-icon class="spin-icon" :size="20"><Loading /></el-icon>
      <span>{{ t('taskDocTab.text_1') }}</span>
    </div>

    <div v-else-if="hasContent" class="doc-content">
      <div class="markdown-body" v-html="renderedContent"></div>
    </div>

    <div v-else class="doc-empty">
      <span class="empty-icon">{{ icon }}</span>
      <p>{{ displayName }} 尚未生成</p>
      <p class="empty-hint">{{ t('taskDocTab.text_2') }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { renderMarkdown } from '@/services/markdown'
import { getAuthToken } from '@/services/api'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

interface ArtifactDetail {
  id: string
  content: string
  version: number
  status: string
  is_latest: boolean
  updated_at: string | null
  versions: { version: number; status: string; created_at: string | null }[]
}

const props = defineProps<{
  taskId: string
  artifactType: string
  displayName: string
  icon: string
}>()

const loading = ref(false)
const currentArtifact = ref<ArtifactDetail | null>(null)
const selectedVersion = ref<number>(0)
const versions = computed(() => currentArtifact.value?.versions || [])
const hasContent = computed(() => !!(currentArtifact.value?.content))
const renderedContent = computed(() =>
  hasContent.value ? renderMarkdown(currentArtifact.value!.content) : ''
)

function formatTime(ts: string | null) {
  if (!ts) return ''
  return new Date(ts).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

async function fetchArtifact(version?: number) {
  loading.value = true
  try {
    const baseUrl = import.meta.env.VITE_API_BASE || '/api'
    const token = getAuthToken()
    const qs = version ? `?version=${version}` : ''
    const res = await fetch(
      `${baseUrl}/tasks/${props.taskId}/artifacts/${props.artifactType}${qs}`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    )
    if (res.status === 404 || res.status === 401) {
      currentArtifact.value = null
      await fetchFromWorktree()
      return
    }
    if (!res.ok) throw new Error(`${res.status}`)
    const data = await res.json()
    if (data.content) {
      currentArtifact.value = data
    } else {
      currentArtifact.value = null
      await fetchFromWorktree(data.storage_path || undefined)
      if (currentArtifact.value?.content) {
        currentArtifact.value = { ...data, content: currentArtifact.value.content }
      } else {
        currentArtifact.value = data
      }
    }
    selectedVersion.value = currentArtifact.value?.version ?? 0
  } catch {
    currentArtifact.value = null
  } finally {
    loading.value = false
  }
}

const ARTIFACT_TO_DOC: Record<string, string> = {
  brief: 'docs/00-brief.md',
  prd: 'docs/01-prd.md',
  ui_spec: 'docs/02-ui-spec.md',
  architecture: 'docs/03-architecture.md',
  implementation: 'docs/04-implementation-notes.md',
  code_link: 'docs/04-implementation-notes.md',
  test_report: 'docs/05-test-report.md',
  acceptance: 'docs/06-acceptance.md',
  ops_runbook: 'docs/07-ops-runbook.md',
  deploy_manifest: 'docs/07-ops-runbook.md',
}

async function fetchFromWorktree(path?: string) {
  const docPath = path || ARTIFACT_TO_DOC[props.artifactType]
  if (!docPath) return
  try {
    const baseUrl = import.meta.env.VITE_API_BASE || '/api'
    const token = getAuthToken()
    const res = await fetch(
      `${baseUrl}/tasks/${props.taskId}/worktree/${docPath}`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    )
    if (!res.ok) return
    const data = await res.json()
    if (data.content) {
      currentArtifact.value = {
        id: '',
        content: data.content,
        version: 1,
        status: 'active',
        is_latest: true,
        updated_at: null,
        versions: [],
      }
    }
  } catch { /* silent fallback */ }
}

function handleVersionChange(v: number) {
  fetchArtifact(v)
}

onMounted(() => fetchArtifact())

watch(() => props.taskId, () => fetchArtifact())
watch(() => props.artifactType, () => fetchArtifact())
</script>

<style scoped>
.task-doc-tab { padding: 16px 0; }

.doc-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding: 0 4px;
}

.doc-version-select { display: flex; align-items: center; }

.doc-meta { font-size: 12px; color: var(--text-muted); }

.doc-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: center;
  padding: 40px;
  color: var(--text-muted);
}

.doc-content {
  background: var(--bg-secondary, #fafafa);
  border-radius: 10px;
  padding: 24px;
  max-height: 70vh;
  overflow-y: auto;
}

.markdown-body { font-size: 14px; line-height: 1.8; color: var(--text-primary); }
.markdown-body :deep(h1) { font-size: 20px; font-weight: 700; margin: 16px 0 10px; }
.markdown-body :deep(h2) { font-size: 16px; font-weight: 700; margin: 14px 0 8px; }
.markdown-body :deep(h3) { font-size: 14px; font-weight: 600; margin: 10px 0 6px; }
.markdown-body :deep(code) { background: rgba(99,102,241,.12); padding: 1px 5px; border-radius: 3px; font-size: 12px; }
.markdown-body :deep(pre) { background: #1a1d23; padding: 12px; border-radius: 6px; overflow-x: auto; }
.markdown-body :deep(pre code) { background: none; }
.markdown-body :deep(table) { width: 100%; border-collapse: collapse; margin: 12px 0; }
.markdown-body :deep(th),
.markdown-body :deep(td) { border: 1px solid var(--border-color); padding: 6px 10px; font-size: 13px; }
.markdown-body :deep(th) { background: var(--bg-tertiary); font-weight: 600; }
.markdown-body :deep(li) { margin-left: 16px; margin-bottom: 2px; list-style: disc; }

.doc-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 20px;
  color: var(--text-muted);
}
.empty-icon { font-size: 36px; margin-bottom: 12px; opacity: 0.5; }
.empty-hint { font-size: 12px; margin-top: 6px; }

.spin-icon { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
