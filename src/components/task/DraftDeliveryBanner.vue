<template>
  <el-alert
    v-if="show"
    class="draft-delivery-banner"
    type="warning"
    :closable="false"
    show-icon
  >
    <template #title>{{ t('draftDelivery.title') }}</template>
    <p class="ddb-summary">{{ summary }}</p>
    <ul v-if="missingItems.length" class="ddb-list">
      <li v-for="item in missingItems" :key="item.key">
        <span class="ddb-cat">{{ categoryLabel(item.category) }}</span>
        <span class="ddb-key">{{ item.key }}</span>
        <span v-if="item.detail" class="ddb-detail"> — {{ item.detail }}</span>
      </li>
    </ul>
  </el-alert>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getAuthToken } from '@/services/api'

interface EvidenceItem {
  category: string
  key: string
  ok: boolean
  detail: string
}

interface EvidencePayload {
  ok?: boolean
  summary?: string
  items?: EvidenceItem[]
}

const props = defineProps<{
  taskId?: string
  status?: string
  evidence?: EvidencePayload | null
  forceShow?: boolean
}>()

const { t } = useI18n()

const loadedEvidence = ref<EvidencePayload | null>(null)

const activeEvidence = computed(() => props.evidence ?? loadedEvidence.value)

const show = computed(() => {
  if (props.forceShow) return true
  if (props.status === 'awaiting_evidence') return true
  const ev = activeEvidence.value
  return ev != null && ev.ok === false
})

const summary = computed(() => {
  return activeEvidence.value?.summary || t('draftDelivery.defaultSummary')
})

const missingItems = computed(() => {
  const items = activeEvidence.value?.items || []
  return items.filter((i) => !i.ok)
})

function categoryLabel(cat: string): string {
  const key = `draftDelivery.category.${cat}` as const
  const translated = t(key)
  return translated === key ? cat : translated
}

async function loadEvidence() {
  if (props.evidence || !props.taskId) return
  try {
    const baseUrl = import.meta.env.VITE_API_BASE || '/api'
    const token = getAuthToken()
    const headers: Record<string, string> = {}
    if (token) headers.Authorization = `Bearer ${token}`
    const res = await fetch(`${baseUrl}/pipeline/tasks/${props.taskId}/evidence`, { headers })
    if (!res.ok) return
    loadedEvidence.value = await res.json()
  } catch {
    /* ignore */
  }
}

onMounted(() => loadEvidence())
watch(() => props.taskId, () => loadEvidence())
</script>

<style scoped>
.draft-delivery-banner {
  margin: 16px 0;
}
.ddb-summary {
  margin: 0 0 8px;
  font-size: 13px;
  line-height: 1.5;
}
.ddb-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.6;
}
.ddb-cat {
  font-weight: 600;
  margin-right: 6px;
}
.ddb-key {
  font-family: ui-monospace, monospace;
}
.ddb-detail {
  color: var(--el-text-color-secondary);
}
</style>
