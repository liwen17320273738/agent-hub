<template>
  <div class="model-lab-page">
    <header class="page-header">
      <h1>{{ t('modelLab.text_1') }}</h1>
      <p class="subtitle">
        {{ $t('modelLab.subtitle') }}
      </p>
    </header>

    <el-card class="lab-card core-card">
      <template #header>
        <div class="core-header">
          <span>{{ t('modelLab.text_2') }}</span>
          <el-tag type="warning" effect="dark">{{ t('modelLab.text_3') }}</el-tag>
        </div>
      </template>
      <div class="core-grid">
        <div v-for="model in Agent_CORE_MODELS" :key="model.id" class="core-model-card">
          <div class="core-model-top">
            <div>
              <div class="core-model-name">{{ model.label }}</div>
              <div class="core-model-provider">{{ PROVIDER_LABEL[model.provider] }}</div>
            </div>
            <el-tag size="small" type="info" effect="plain">{{ $t('modelLab.core') }}</el-tag>
          </div>
          <div class="core-model-role">{{ model.recommendedRole }}</div>
          <p class="core-model-blurb">{{ model.blurb }}</p>
        </div>
      </div>
      <p class="core-note">
        {{ $t('modelLab.coreNote') }}
      </p>
    </el-card>

    <el-alert type="info" show-icon :closable="false" class="lab-alert">
      <template #title>{{ $t('modelLab.aboutScoring') }}</template>
      {{ $t('modelLab.scoringIntro') }}
    </el-alert>

    <el-card class="lab-card">
      <template #header>
        <span>{{ $t('modelLab.catalogTitle') }}</span>
      </template>
      <el-table :data="MODEL_CATALOG" stripe size="small" class="catalog-table">
        <el-table-column :label="$t('modelLab.colCore')" width="72" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.isCore" size="small" type="warning" effect="plain">{{ $t('modelLab.core') }}</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="label" :label="$t('modelLab.colName')" width="140" />
        <el-table-column prop="recommendedRole" :label="$t('modelLab.colRole')" width="180" show-overflow-tooltip />
        <el-table-column prop="id" :label="$t('modelLab.colModelId')" min-width="130" />
        <el-table-column :label="$t('modelLab.colProvider')" width="100">
          <template #default="{ row }">
            {{ PROVIDER_LABEL[row.provider] }}
          </template>
        </el-table-column>
        <el-table-column prop="contextK" :label="$t('modelLab.colContext')" width="110" align="center" />
        <el-table-column v-for="col in SCORE_LABELS" :key="col.key" :label="col.label" width="76" align="center">
          <template #default="{ row }">
            <span class="score-cell">{{ row.scores[col.key] }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="blurb" :label="$t('modelLab.colBlurb')" min-width="200" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-card class="lab-card">
      <template #header>
        <span>{{ $t('modelLab.benchmarkTitle') }}</span>
      </template>
      <p v-if="!settingsStore.isConfigured()" class="warn-text">
        <template v-if="isEnterpriseBuild">{{ $t('modelLab.waitAdmin') }}</template>
        <template v-else>{{ $t('modelLab.configureApiKey') }}</template>
      </p>
      <template v-else>
        <p class="hint-text">
          {{ $t('modelLab.hint1') }}
          {{ $t('modelLab.hint2') }}
        </p>
        <p v-if="matchingCatalog.length" class="hint-text">
          {{ $t('modelLab.hint3') }}
        </p>
        <p v-else class="warn-text">
          {{ $t('modelLab.hint4') }}
        </p>

        <el-checkbox-group v-if="matchingCatalog.length" v-model="benchModelIds" class="bench-checks">
          <el-checkbox
            v-for="m in matchingCatalog"
            :key="m.id"
            :label="m.id"
            :disabled="benchModelIds.length >= 4 && !benchModelIds.includes(m.id)"
          >
            {{ m.label }} ({{ m.id }})
          </el-checkbox>
        </el-checkbox-group>

        <el-input
          v-else
          v-model="benchCustomIdsText"
          type="textarea"
          :rows="3"
          :placeholder="$t('modelLab.benchPlaceholder')"
          class="bench-custom"
        />

        <div class="bench-prompt-block">
          <div class="prompt-label">{{ $t('modelLab.testPrompt') }}</div>
          <el-input v-model="benchPrompt" type="textarea" :rows="4" />
        </div>

        <el-button type="primary" :loading="benchRunning" :disabled="resolvedBenchModels.length === 0" @click="runBenchmark">
          {{ $t('modelLab.runBench') }}
        </el-button>

        <el-table v-if="benchResults.length" :data="benchResults" class="result-table" stripe style="margin-top: 16px">
          <el-table-column prop="model" label="model" width="160" />
          <el-table-column prop="latencyMs" :label="$t('modelLab.latencyMs')" width="100" align="right" />
          <el-table-column :label="$t('modelLab.tokens')" min-width="120">
            <template #default="{ row }">
              <span v-if="row.usage">
                {{ $t('modelLab.tokensInOut', { in: row.usage.prompt_tokens ?? '—', out: row.usage.completion_tokens ?? '—' }) }}
              </span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column prop="error" :label="$t('modelLab.error')" min-width="120" show-overflow-tooltip />
          <el-table-column :label="$t('modelLab.replySummary')" min-width="200">
            <template #default="{ row }">
              <span class="reply-preview">{{ row.error ? '—' : row.content.slice(0, 200) }}{{ row.content.length > 200 ? '…' : '' }}</span>
            </template>
          </el-table-column>
        </el-table>

        <el-collapse v-if="benchResults.length" class="bench-collapse">
          <el-collapse-item :title="$t('modelLab.viewFullReply')" name="1">
            <div v-for="r in benchResults" :key="r.model" class="full-block">
              <h4>{{ r.model }}</h4>
              <pre v-if="r.error" class="err-pre">{{ r.error }}</pre>
              <pre v-else class="content-pre">{{ r.content }}</pre>
            </div>
          </el-collapse-item>
        </el-collapse>
      </template>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  MODEL_CATALOG,
  SCORE_LABELS,
  PROVIDER_LABEL,
  Agent_CORE_MODELS,
  catalogMatchingApiUrl,
  inferDefaultApiFromLlmHost,
} from '@/services/modelCatalog'
import { useSettingsStore } from '@/stores/settings'
import { useAuthStore } from '@/stores/auth'
import { isEnterpriseBuild } from '@/services/enterpriseApi'
import { chatCompletionOnce } from '@/services/llm'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const settingsStore = useSettingsStore()
const authStore = useAuthStore()

const benchPrompt = ref(
  t('modelLab.defaultBenchPrompt'),
)
const benchModelIds = ref<string[]>([])
const benchCustomIdsText = ref('')
const benchRunning = ref(false)
const benchResults = ref<
  Array<{
    model: string
    latencyMs: number
    content: string
    usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number }
    error?: string
  }>
>([])

const catalogSourceUrl = computed(() => {
  const u = settingsStore.settings.apiUrl?.trim()
  if (u) return u
  if (isEnterpriseBuild && authStore.publicLlm?.host) {
    return inferDefaultApiFromLlmHost(authStore.publicLlm.host)
  }
  return ''
})

const matchingCatalog = computed(() => catalogMatchingApiUrl(catalogSourceUrl.value))

watch(
  matchingCatalog,
  (list) => {
    if (list.length >= 2) {
      benchModelIds.value = [list[0].id, list[1].id]
    } else if (list.length === 1) {
      benchModelIds.value = [list[0].id]
    } else {
      benchModelIds.value = []
    }
  },
  { immediate: true },
)

const resolvedBenchModels = computed(() => {
  if (matchingCatalog.value.length) {
    return benchModelIds.value.slice(0, 4)
  }
  const raw = benchCustomIdsText.value
    .split(/[\n,，;；]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  return [...new Set(raw)].slice(0, 4)
})

async function runBenchmark() {
  const models = resolvedBenchModels.value
  if (!models.length) {
    ElMessage.warning(t('modelLab.elMessage_1'))
    return
  }
  if (!settingsStore.isConfigured()) return

  benchRunning.value = true
  benchResults.value = []
  const msgs = [{ role: 'user' as const, content: benchPrompt.value }]

  try {
    for (const model of models) {
      const r = await chatCompletionOnce(msgs, settingsStore.settings, { model })
      benchResults.value.push({
        model,
        latencyMs: r.latencyMs,
        content: r.content,
        usage: r.usage,
        error: r.error,
      })
    }
    ElMessage.success(t('modelLab.elMessage_2'))
  } finally {
    benchRunning.value = false
  }
}
</script>

<style scoped>
.model-lab-page {
  padding: 32px 40px 48px;
  max-max-width: 1400px; width: 100%;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h1 {
  font-size: 26px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.subtitle {
  color: var(--text-secondary);
  font-size: 14px;
}

.lab-alert {
  margin-bottom: 20px;
}

.lab-card {
  margin-bottom: 20px;
  background: var(--bg-card);
  border-color: var(--border-color);
}

.core-card {
  margin-bottom: 20px;
}

.core-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.core-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.core-model-card {
  border-radius: 14px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  padding: 14px;
}

.core-model-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.core-model-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.core-model-provider {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

.core-model-role {
  font-size: 13px;
  color: var(--accent);
  font-weight: 600;
  margin-bottom: 8px;
}

.core-model-blurb {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.core-note {
  margin-top: 12px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-muted);
}

.hint-text {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 10px;
}

.hint-text code {
  font-size: 12px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg-tertiary);
}

.warn-text {
  color: #e6a23c;
  font-size: 14px;
}

.bench-checks {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.bench-custom {
  margin-bottom: 16px;
}

.bench-prompt-block {
  margin: 16px 0;
}

.prompt-label {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.score-cell {
  font-weight: 600;
  color: var(--accent);
}

.result-table .muted {
  color: var(--text-muted);
}

.reply-preview {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.bench-collapse {
  margin-top: 12px;
}

.full-block {
  margin-bottom: 20px;
}

.full-block h4 {
  font-size: 14px;
  margin-bottom: 8px;
  color: var(--text-primary);
}

.content-pre,
.err-pre {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.6;
  padding: 12px;
  border-radius: 8px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  max-height: 320px;
  overflow: auto;
}

.err-pre {
  color: #f56c6c;
}
</style>
