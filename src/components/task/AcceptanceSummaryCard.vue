<template>
  <section v-if="task" class="acceptance-summary">
    <div class="as-card" :class="{ 'as-ready': hasPreviewUrl }">
      <div class="as-icon">{{ hasPreviewUrl ? '🚀' : '📦' }}</div>
      <div class="as-grid">
        <div class="as-field">
          <div class="as-label">{{ t('acceptanceSummary.delivered') }}</div>
          <div class="as-value">{{ deliveredLine }}</div>
        </div>
        <div class="as-field">
          <div class="as-label">{{ t('acceptanceSummary.tryIt') }}</div>
          <div class="as-value">
            <a v-if="hasPreviewUrl" :href="previewUrl" target="_blank" rel="noopener" class="as-link">
              {{ previewUrl }}
              <span class="as-external">↗</span>
            </a>
            <span v-else class="as-muted">{{ t('acceptanceSummary.tryItPending') }}</span>
          </div>
        </div>
        <div class="as-field">
          <div class="as-label">{{ t('acceptanceSummary.owner') }}</div>
          <div class="as-value">{{ ownerLine }}</div>
        </div>
        <div class="as-field">
          <div class="as-label">{{ t('acceptanceSummary.deadline') }}</div>
          <div class="as-value">{{ deadlineLine }}</div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

interface ArtifactRow {
  artifact_type: string
  content?: string
  metadata_json?: Record<string, unknown> | null
}

interface ShareTaskShape {
  title?: string
  status?: string
  created_at?: string | number
  expires_at?: string | number
  final_acceptance_status?: string
  owner_email?: string
  owner?: string
  artifacts?: ArtifactRow[]
  docs?: Array<{ name?: string; content?: string }>
}

const props = defineProps<{
  task: ShareTaskShape | null
}>()

const { t } = useI18n()

const allArts = computed<ArtifactRow[]>(() => {
  if (!props.task) return []
  const direct = props.task.artifacts || []
  const fromDocs = (props.task.docs || []).map(d => ({
    artifact_type: (d.name || '').replace('.md', '').replace(/^\d+-/, ''),
    content: d.content || '',
    metadata_json: null,
  }))
  return [...direct, ...fromDocs]
})

function findArt(type: string): ArtifactRow | undefined {
  return allArts.value.find(a => a.artifact_type === type)
}

function parseMeta(a: ArtifactRow | undefined): Record<string, unknown> {
  if (!a) return {}
  if (a.metadata_json) return a.metadata_json
  if (a.content) {
    try { return JSON.parse(a.content) } catch { /* not json */ }
  }
  return {}
}

const previewMeta = computed(() => parseMeta(findArt('preview_url')))
const previewUrl = computed(() => String(previewMeta.value.url || ''))
const hasPreviewUrl = computed(() => !!previewUrl.value)

const deliveredLine = computed(() => {
  const acceptArt = findArt('acceptance')
  if (acceptArt) {
    const meta = parseMeta(acceptArt)
    if (meta.summary) return String(meta.summary)
    if (meta.one_liner) return String(meta.one_liner)
    if (acceptArt.content) {
      const firstLine = acceptArt.content.split('\n').map(s => s.trim()).find(Boolean) || ''
      const stripped = firstLine.replace(/^#+\s*/, '').slice(0, 140)
      if (stripped) return stripped
    }
  }
  return props.task?.title || t('acceptanceSummary.deliveredFallback')
})

const ownerLine = computed(() => {
  if (props.task?.owner_email) return String(props.task.owner_email)
  if (props.task?.owner) return String(props.task.owner)
  return t('acceptanceSummary.ownerFallback')
})

const deadlineLine = computed(() => {
  if (props.task?.final_acceptance_status === 'accepted') {
    return t('acceptanceSummary.alreadyAccepted')
  }
  if (props.task?.expires_at) {
    const d = new Date(props.task.expires_at)
    return t('acceptanceSummary.expiresAt', { date: d.toLocaleDateString() })
  }
  return t('acceptanceSummary.deadlineFallback')
})
</script>

<style scoped>
.acceptance-summary {
  margin: 24px 0;
}
.as-card {
  display: flex;
  align-items: flex-start;
  gap: 20px;
  padding: 24px;
  border-radius: 14px;
  background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%);
  border: 1px solid #e2e8f0;
}
.as-card.as-ready {
  background: linear-gradient(135deg, #ecfdf5 0%, #e0f2fe 100%);
  border-color: #bbf7d0;
}
.as-icon {
  font-size: 40px;
  line-height: 1;
}
.as-grid {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px 24px;
}
.as-field {
  min-width: 0;
}
.as-label {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 4px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.as-value {
  font-size: 14px;
  color: #111827;
  word-break: break-word;
}
.as-link {
  color: #2563eb;
  text-decoration: none;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
}
.as-link:hover { text-decoration: underline; }
.as-external { margin-left: 4px; }
.as-muted { color: #9ca3af; }
@media (max-width: 640px) {
  .as-grid { grid-template-columns: 1fr; }
  .as-card { flex-direction: column; }
}
</style>
