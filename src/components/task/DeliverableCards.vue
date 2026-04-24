<template>
  <div class="deliverable-cards">
    <div class="cards-header">
      <h3>{{ t('deliverableCards.text_1') }}</h3>
      <el-button v-if="!isShareMode" size="small" @click="refresh" :loading="loading">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
    </div>

    <div class="cards-grid">
      <div
        v-for="card in cards"
        :key="card.name"
        class="deliverable-card"
        :class="{ 'has-content': card.exists, 'is-active': activeDoc === card.name }"
        @click="toggleDoc(card)"
      >
        <div class="card-icon">{{ card.icon }}</div>
        <div class="card-body">
          <div class="card-title">{{ card.title }}</div>
          <div class="card-meta">
            <span v-if="card.exists" class="card-status done">{{ t('deliverableCards.text_2') }}</span>
            <span v-else class="card-status empty">{{ t('deliverableCards.text_3') }}</span>
            <span v-if="card.updatedAt" class="card-time">{{ formatTime(card.updatedAt) }}</span>
          </div>
        </div>
      </div>
    </div>

    <transition name="slide">
      <div v-if="activeDoc && docContent !== null" class="doc-viewer">
        <div class="viewer-header">
          <span class="viewer-title">{{ activeTitle }}</span>
          <div class="viewer-actions">
            <el-button v-if="!editing && !isShareMode" size="small" text @click="editing = true">
              <el-icon><Edit /></el-icon>
              编辑
            </el-button>
            <template v-if="editing">
              <el-button size="small" type="primary" @click="save" :loading="saving">{{ t('deliverableCards.text_4') }}</el-button>
              <el-button size="small" text @click="cancelEdit">{{ t('deliverableCards.text_5') }}</el-button>
            </template>
            <el-button size="small" text @click="closeViewer">
              <el-icon><Close /></el-icon>
            </el-button>
          </div>
        </div>
        <div v-if="!editing" class="viewer-body markdown-body" v-html="renderedContent"></div>
        <el-input
          v-else
          v-model="editBuffer"
          type="textarea"
          :autosize="{ minRows: 12, maxRows: 30 }"
          class="viewer-editor"
        />
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { listTaskDocs, readTaskDoc, writeTaskDoc, initTaskWorkspace } from '@/services/deliveryDocs'
import type { TaskDocMeta } from '@/services/deliveryDocs'

const { t } = useI18n()

function formatTime(ts: string | number | null | undefined) {
  if (ts == null || ts === '') return ''
  const n = typeof ts === 'number' ? ts : Date.parse(ts)
  if (Number.isNaN(n)) return ''
  return new Date(n).toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const props = defineProps<{
  taskId: string
  shareToken?: string
}>()

const isShareMode = computed(() => !!props.shareToken)

const DOC_ICONS: Record<string, string> = {
  '00-brief.md': '📝',
  '01-prd.md': '📋',
  '02-ui-spec.md': '🎨',
  '03-architecture.md': '🏗',
  '04-implementation-notes.md': '💻',
  '05-test-report.md': '🧪',
  '06-acceptance.md': '✅',
  '07-ops-runbook.md': '🚀',
}

const loading = ref(false)
const docs = ref<TaskDocMeta[]>([])
const activeDoc = ref<string | null>(null)
const docContent = ref<string | null>(null)
const editing = ref(false)
const editBuffer = ref('')
const saving = ref(false)

const cards = computed(() =>
  docs.value.map(d => ({
    ...d,
    icon: DOC_ICONS[d.name] || '📄',
    updatedAt: d.updated_at,
  }))
)

const activeTitle = computed(() => {
  const doc = docs.value.find(d => d.name === activeDoc.value)
  return doc?.title || ''
})

const renderedContent = computed(() => {
  if (!docContent.value) return '<p style="color:var(--el-text-color-secondary)">空文档</p>'
  return docContent.value
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    .replace(/\n/g, '<br>')
})

function getBaseUrl(): string {
  return import.meta.env.VITE_API_BASE || '/api'
}

async function refresh() {
  loading.value = true
  try {
    if (isShareMode.value) {
      const res = await fetch(`${getBaseUrl()}/share/${props.shareToken}`)
      if (res.ok) {
        const data = await res.json()
        const all8 = Object.keys(DOC_ICONS)
        docs.value = all8.map(name => {
          const found = (data.docs || []).find((d: any) => d.name === name || d.name === name.replace('.md', ''))
          return {
            name,
            title: name.replace('.md', '').replace(/^\d+-/, '').replace(/-/g, ' '),
            exists: !!found,
            updated_at: found?.updated_at || null,
          }
        })
      }
    } else {
      await initTaskWorkspace(props.taskId)
      docs.value = await listTaskDocs(props.taskId)
    }
  } catch {
    ElMessage.warning(t('deliverableCards.elMessage_1'))
  } finally {
    loading.value = false
  }
}

async function toggleDoc(card: TaskDocMeta & { icon: string }) {
  if (activeDoc.value === card.name) {
    closeViewer()
    return
  }
  activeDoc.value = card.name
  docContent.value = null
  editing.value = false
  try {
    if (isShareMode.value) {
      const docKey = card.name.replace('.md', '')
      const res = await fetch(`${getBaseUrl()}/share/${props.shareToken}/doc/${docKey}`)
      if (res.ok) {
        const data = await res.json()
        docContent.value = data.content
      } else {
        docContent.value = '*(加载失败)*'
      }
    } else {
      const doc = await readTaskDoc(props.taskId, card.name)
      docContent.value = doc.content
    }
  } catch {
    docContent.value = '*(加载失败)*'
  }
}

function closeViewer() {
  activeDoc.value = null
  docContent.value = null
  editing.value = false
}

function cancelEdit() {
  editing.value = false
  editBuffer.value = ''
}

async function save() {
  if (!activeDoc.value) return
  saving.value = true
  try {
    const doc = await writeTaskDoc(props.taskId, activeDoc.value, editBuffer.value)
    docContent.value = doc.content
    editing.value = false
    ElMessage.success(t('deliverableCards.elMessage_2'))
    await refresh()
  } catch {
    ElMessage.error(t('deliverableCards.elMessage_3'))
  } finally {
    saving.value = false
  }
}

onMounted(refresh)

watch(editing, (val) => {
  if (val && docContent.value) {
    editBuffer.value = docContent.value
  }
})
</script>

<style scoped>
.deliverable-cards {
  margin-top: 8px;
}

.cards-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.cards-header h3 {
  font-size: 16px;
  font-weight: 600;
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.deliverable-card {
  padding: 14px;
  border-radius: 10px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
  cursor: pointer;
  transition: all 0.2s;
  text-align: center;
}

.deliverable-card:hover {
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
  transform: translateY(-1px);
}

.deliverable-card.has-content {
  border-color: var(--el-color-success-light-5);
}

.deliverable-card.is-active {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 1px var(--el-color-primary-light-5);
}

.card-icon {
  font-size: 28px;
  margin-bottom: 8px;
}

.card-title {
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 4px;
}

.card-meta {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.card-status {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
}

.card-status.done {
  background: rgba(103, 194, 58, 0.1);
  color: #67c23a;
}

.card-status.empty {
  background: var(--el-fill-color-light);
  color: var(--el-text-color-placeholder);
}

.card-time {
  font-size: 10px;
  color: var(--el-text-color-secondary);
}

/* ── Doc viewer ── */
.doc-viewer {
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  overflow: hidden;
  background: var(--el-bg-color);
}

.viewer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-lighter);
}

.viewer-title {
  font-weight: 600;
  font-size: 14px;
}

.viewer-actions {
  display: flex;
  gap: 4px;
}

.viewer-body {
  padding: 16px 20px;
  max-height: 500px;
  overflow-y: auto;
  font-size: 13px;
  line-height: 1.7;
}

.viewer-editor :deep(.el-textarea__inner) {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 13px;
  line-height: 1.6;
  padding: 16px 20px;
}

.slide-enter-active, .slide-leave-active {
  transition: all 0.3s ease;
}
.slide-enter-from, .slide-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

@media (max-width: 768px) {
  .cards-grid {
    grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  }
}
</style>
