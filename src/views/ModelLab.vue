<template>
  <div class="model-lab-page">
    <header class="page-header">
      <h1>{{ t('modelLab.text_1') }}</h1>
      <p class="subtitle">
        参考评分 + 同一提示词下的延迟与输出对比（个人模式使用本地 API Key；企业模式经服务端统一网关）
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
        <div v-for="model in WAYNE_CORE_MODELS" :key="model.id" class="core-model-card">
          <div class="core-model-top">
            <div>
              <div class="core-model-name">{{ model.label }}</div>
              <div class="core-model-provider">{{ PROVIDER_LABEL[model.provider] }}</div>
            </div>
            <el-tag size="small" type="info" effect="plain">核心</el-tag>
          </div>
          <div class="core-model-role">{{ model.recommendedRole }}</div>
          <p class="core-model-blurb">{{ model.blurb }}</p>
        </div>
      </div>
      <p class="core-note">
        说明：`GPT-4.5 / Opus 4.6 / Sonnet 4.6 / Gemini 4 / 智谱 GLM-4.5` 已纳入 Agent Hub 核心映射。部分模型在当前界面更适合作为静态选型参考，实测建议通过兼容网关或统一服务端路由接入。
      </p>
    </el-card>

    <el-alert type="info" show-icon :closable="false" class="lab-alert">
      <template #title>关于「维度评分」</template>
      下表 1–5 分为静态参考（性价比、速度、推理、中文、代码、指令），便于选型；不同厂商定价会变，请以账单为准。真实体感请用下方「对比实测」。
    </el-alert>

    <el-card class="lab-card">
      <template #header>
        <span>模型目录与维度</span>
      </template>
      <el-table :data="MODEL_CATALOG" stripe size="small" class="catalog-table">
        <el-table-column label="核心" width="72" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.isCore" size="small" type="warning" effect="plain">核心</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="label" label="名称" width="140" />
        <el-table-column prop="recommendedRole" label="推荐角色" width="180" show-overflow-tooltip />
        <el-table-column prop="id" label="model id" min-width="130" />
        <el-table-column label="厂商" width="100">
          <template #default="{ row }">
            {{ PROVIDER_LABEL[row.provider] }}
          </template>
        </el-table-column>
        <el-table-column prop="contextK" label="约上下文(K)" width="110" align="center" />
        <el-table-column v-for="col in SCORE_LABELS" :key="col.key" :label="col.label" width="76" align="center">
          <template #default="{ row }">
            <span class="score-cell">{{ row.scores[col.key] }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="blurb" label="说明" min-width="200" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-card class="lab-card">
      <template #header>
        <span>对比实测</span>
      </template>
      <p v-if="!settingsStore.isConfigured()" class="warn-text">
        <template v-if="isEnterpriseBuild">请等待管理员配置服务端 LLM 环境变量后再运行。</template>
        <template v-else>请先在「设置」中配置 API Key 后再运行。</template>
      </p>
      <template v-else>
        <p class="hint-text">
          将使用设置里的 API 地址与 Key，仅替换 <code>model</code> 字段。请选择与当前 API
          <strong>同一厂商</strong>下的模型，否则会直接报错。
        </p>
        <p v-if="matchingCatalog.length" class="hint-text">
          根据当前 API 地址，推荐对比以下模型（最多选 4 个）：
        </p>
        <p v-else class="warn-text">
          当前 API 地址未匹配内置厂商（DeepSeek / OpenAI / 通义），请在下框手动输入 model id，用逗号或换行分隔（最多 4 个）。
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
          placeholder="例如：deepseek-chat&#10;deepseek-reasoner"
          class="bench-custom"
        />

        <div class="bench-prompt-block">
          <div class="prompt-label">测试提示词</div>
          <el-input v-model="benchPrompt" type="textarea" :rows="4" />
        </div>

        <el-button type="primary" :loading="benchRunning" :disabled="resolvedBenchModels.length === 0" @click="runBenchmark">
          运行对比
        </el-button>

        <el-table v-if="benchResults.length" :data="benchResults" class="result-table" stripe style="margin-top: 16px">
          <el-table-column prop="model" label="model" width="160" />
          <el-table-column prop="latencyMs" label="延迟(ms)" width="100" align="right" />
          <el-table-column label="tokens" min-width="120">
            <template #default="{ row }">
              <span v-if="row.usage">
                入 {{ row.usage.prompt_tokens ?? '—' }} / 出 {{ row.usage.completion_tokens ?? '—' }}
              </span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column prop="error" label="错误" min-width="120" show-overflow-tooltip />
          <el-table-column label="回复摘要" min-width="200">
            <template #default="{ row }">
              <span class="reply-preview">{{ row.error ? '—' : row.content.slice(0, 200) }}{{ row.content.length > 200 ? '…' : '' }}</span>
            </template>
          </el-table-column>
        </el-table>

        <el-collapse v-if="benchResults.length" class="bench-collapse">
          <el-collapse-item title="查看完整回复" name="1">
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
import { ElMessage } from 'element-plus'
import {
  MODEL_CATALOG,
  SCORE_LABELS,
  PROVIDER_LABEL,
  WAYNE_CORE_MODELS,
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
  '请用约 200 字以内中文，说明「企业」使用 AI 的三条务实建议，每条一句话举例。',
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
  max-width: 1400px;
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
