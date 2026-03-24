<template>
  <div class="settings-page">
    <header class="page-header">
      <h1>设置</h1>
      <p class="subtitle">配置 LLM API 连接（兼容 OpenAI 接口格式）</p>
    </header>

    <el-alert
      class="settings-security-alert"
      type="warning"
      show-icon
      :closable="false"
      title="安全与部署说明"
    >
      <p>
        API Key 保存在浏览器 localStorage，公共设备或恶意脚本可能导致泄露。生产环境建议由后端或网关代调模型 API，密钥仅放在服务端。若部署时配置了与
        <code>vite.config</code> 相同的 <code>/api/proxy/*</code> 反向代理，可在构建环境设置
        <code>VITE_USE_RELATIVE_PROXY=true</code>，使前端请求走同源路径（与 dev、<code>pnpm preview</code> 行为一致），便于隐藏真实 API 域名并统一走网关。
      </p>
    </el-alert>

    <el-card class="settings-card">
      <template #header>
        <div class="card-header">
          <el-icon><Connection /></el-icon>
          <span>API 配置</span>
        </div>
      </template>

      <el-form :model="form" label-width="120px" label-position="left">
        <el-form-item label="API 地址">
          <el-input v-model="form.apiUrl" placeholder="https://api.deepseek.com/v1/chat/completions" />
          <div class="form-tip">支持 OpenAI 兼容接口：DeepSeek / Qwen / OpenAI / Claude(via proxy)</div>
          <div class="quick-providers">
            <span class="quick-label">快速填入：</span>
            <el-button link type="primary" @click="fillProviderApi('deepseek')">DeepSeek</el-button>
            <el-button link type="primary" @click="fillProviderApi('openai')">OpenAI</el-button>
            <el-button link type="primary" @click="fillProviderApi('qwen')">通义千问</el-button>
          </div>
        </el-form-item>

        <el-form-item label="API Key">
          <el-input v-model="form.apiKey" type="password" show-password placeholder="sk-..." />
        </el-form-item>

        <el-form-item label="模型">
          <el-select
            v-if="catalogMatches.length"
            :model-value="catalogSelectValue"
            placeholder="从当前厂商推荐中选择（可选）"
            clearable
            filterable
            class="model-preset-select"
            @change="onCatalogModelChange"
          >
            <el-option
              v-for="m in catalogMatches"
              :key="m.id"
              :label="`${m.label} (${m.id})`"
              :value="m.id"
            />
          </el-select>
          <el-input v-model="form.model" class="model-id-input" placeholder="model id，如 deepseek-chat" />
          <div class="form-tip">
            各模型维度与横向对比见
            <router-link class="inline-link" to="/model-lab">模型实验室</router-link>
            ；也可直接手填任意兼容 model。
          </div>
        </el-form-item>

        <el-form-item label="Temperature">
          <el-slider v-model="form.temperature" :min="0" :max="2" :step="0.1" show-input :show-input-controls="false" />
        </el-form-item>

        <el-form-item label="最大 Token">
          <el-input-number v-model="form.maxTokens" :min="256" :max="16384" :step="256" />
          <div class="form-tip">千问等模型上限 16384，超出会报错</div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="handleSave">
            <el-icon><Check /></el-icon>
            保存设置
          </el-button>
          <el-button @click="handleTest" :loading="testing">
            <el-icon><Connection /></el-icon>
            测试连接
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="settings-card">
      <template #header>
        <div class="card-header">
          <el-icon><ChatDotRound /></el-icon>
          <span>对话上下文</span>
        </div>
      </template>
      <el-form :model="form" label-width="120px" label-position="left">
        <el-form-item label="窗口消息条数">
          <el-input-number v-model="form.contextMaxMessages" :min="4" :max="128" :step="2" />
          <div class="form-tip">单次请求最多携带的用户+助手消息条数（从最新往前截断）</div>
        </el-form-item>
        <el-form-item label="窗口字符上限">
          <el-input-number v-model="form.contextMaxChars" :min="4000" :max="200000" :step="2000" />
          <div class="form-tip">在条数限制之后，再按总字符收紧，用于控制费用与上下文长度</div>
        </el-form-item>
        <el-form-item label="工具调用">
          <el-switch v-model="form.enableTools" />
          <div class="form-tip">
            开启后模型可调用内置工具：当前时间、文本统计、随机整数。走非流式多轮请求；若接口报错，请关闭此项。
          </div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSave">
            <el-icon><Check /></el-icon>
            保存设置
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="settings-card">
      <template #header>
        <div class="card-header">
          <el-icon><InfoFilled /></el-icon>
          <span>快速接入指南</span>
        </div>
      </template>
      <div class="guide-list">
        <div class="guide-item">
          <strong>DeepSeek (推荐)</strong>
          <p>地址: https://api.deepseek.com/v1/chat/completions</p>
          <p>模型: deepseek-chat / deepseek-reasoner</p>
          <p>获取 Key: <a href="https://platform.deepseek.com" target="_blank">platform.deepseek.com</a></p>
        </div>
        <el-divider />
        <div class="guide-item">
          <strong>通义千问</strong>
          <p>地址: https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions</p>
          <p>模型: qwen-turbo / qwen-plus / qwen-max</p>
          <p>获取 Key: <a href="https://dashscope.console.aliyun.com" target="_blank">dashscope.console.aliyun.com</a></p>
        </div>
        <el-divider />
        <div class="guide-item">
          <strong>OpenAI</strong>
          <p>地址: https://api.openai.com/v1/chat/completions</p>
          <p>模型: gpt-4o / gpt-4o-mini</p>
          <p>获取 Key: <a href="https://platform.openai.com" target="_blank">platform.openai.com</a></p>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useSettingsStore } from '@/stores/settings'
import { chatCompletion } from '@/services/llm'
import {
  catalogMatchingApiUrl,
  PROVIDER_DEFAULT_API,
  type ModelProvider,
} from '@/services/modelCatalog'

const settingsStore = useSettingsStore()
const testing = ref(false)

const form = reactive({ ...settingsStore.settings })

const catalogMatches = computed(() => catalogMatchingApiUrl(form.apiUrl))

const catalogSelectValue = computed(() => {
  const hit = catalogMatches.value.find((m) => m.id === form.model)
  return hit ? hit.id : undefined
})

function onCatalogModelChange(id: string | undefined) {
  if (id) form.model = id
}

function fillProviderApi(p: ModelProvider) {
  form.apiUrl = PROVIDER_DEFAULT_API[p]
}

function handleSave() {
  settingsStore.save({ ...form })
  ElMessage.success('设置已保存')
}

async function handleTest() {
  if (!form.apiKey) {
    ElMessage.warning('请先填写 API Key')
    return
  }
  testing.value = true
  try {
    const reply = await chatCompletion(
      [{ role: 'user', content: '你好，请用一句话回复确认连接成功。' }],
      { ...form },
    )
    ElMessage.success(`连接成功！回复: ${reply.slice(0, 60)}`)
  } catch (e: any) {
    ElMessage.error(`连接失败: ${e.message}`)
  } finally {
    testing.value = false
  }
}
</script>

<style scoped>
.settings-page {
  padding: 40px;
  max-width: 800px;
  margin: 0 auto;
}

.settings-security-alert {
  margin-bottom: 24px;
  max-width: 800px;
}

.settings-security-alert p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.settings-security-alert code {
  font-size: 12px;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg-tertiary);
}

.page-header {
  margin-bottom: 32px;
}

.page-header h1 {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.subtitle {
  color: var(--text-secondary);
  font-size: 14px;
}

.settings-card {
  margin-bottom: 20px;
  background: var(--bg-card);
  border-color: var(--border-color);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.form-tip {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}

.quick-providers {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-muted);
}

.quick-label {
  margin-right: 4px;
}

.model-preset-select {
  width: 100%;
  max-width: 420px;
  margin-bottom: 10px;
}

.model-id-input {
  max-width: 420px;
}

.inline-link {
  color: var(--accent);
  text-decoration: none;
}

.inline-link:hover {
  text-decoration: underline;
}

.guide-list {
  font-size: 14px;
  line-height: 1.8;
}

.guide-item strong {
  font-size: 15px;
  color: var(--text-primary);
}

.guide-item p {
  color: var(--text-secondary);
  margin: 2px 0;
}

.guide-item a {
  color: var(--accent);
  text-decoration: none;
}

.guide-item a:hover {
  text-decoration: underline;
}
</style>
