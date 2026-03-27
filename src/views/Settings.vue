<template>
  <div class="settings-page">
    <header class="page-header">
      <h1>设置</h1>
      <p class="subtitle">配置 LLM API 连接（兼容 OpenAI 接口格式）</p>
    </header>

    <el-alert
      v-if="!isEnterpriseBuild"
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

    <el-alert
      v-else
      class="settings-security-alert"
      type="success"
      show-icon
      :closable="false"
      title="企业模式"
    >
      <p>
        当前为构建时启用的企业部署：会话保存在服务端数据库，同组织成员共享；模型 API Key 仅存在于服务器环境变量，浏览器不保存密钥。
      </p>
    </el-alert>

    <el-card v-if="isEnterpriseBuild" class="settings-card">
      <template #header>
        <div class="card-header">
          <el-icon><Connection /></el-icon>
          <span>组织与模型网关（只读）</span>
        </div>
      </template>
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item label="组织">{{ authStore.user?.orgName ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="上游 Host">{{ authStore.publicLlm?.host || '未配置' }}</el-descriptions-item>
        <el-descriptions-item label="默认模型">{{ authStore.publicLlm?.model || '—' }}</el-descriptions-item>
        <el-descriptions-item label="网关状态">
          <el-tag :type="authStore.llmConfigured ? 'success' : 'danger'" size="small">
            {{ authStore.llmConfigured ? '已配置' : '未配置 LLM 环境变量' }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>
      <p class="form-tip" style="margin-top: 12px">
        下方「模型」可覆盖默认 model id（须与当前上游兼容）；留空则使用服务端 LLM_MODEL。
      </p>
    </el-card>

    <el-card v-if="!isEnterpriseBuild" class="settings-card">
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

    <el-card v-else class="settings-card">
      <template #header>
        <div class="card-header">
          <el-icon><Connection /></el-icon>
          <span>模型与参数</span>
        </div>
      </template>
      <el-form :model="form" label-width="120px" label-position="left">
        <el-form-item label="模型">
          <el-select
            v-if="catalogMatches.length"
            :model-value="catalogSelectValue"
            placeholder="从推荐中选择（可选）"
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
          <el-input v-model="form.model" class="model-id-input" placeholder="留空则用服务端默认 model" />
        </el-form-item>
        <el-form-item label="Temperature">
          <el-slider v-model="form.temperature" :min="0" :max="2" :step="0.1" show-input :show-input-controls="false" />
        </el-form-item>
        <el-form-item label="最大 Token">
          <el-input-number v-model="form.maxTokens" :min="256" :max="16384" :step="256" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSave">
            <el-icon><Check /></el-icon>
            保存个人偏好
          </el-button>
          <el-button v-if="settingsStore.isConfigured()" @click="handleTest" :loading="testing">
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

    <el-card v-if="isEnterpriseBuild && authStore.user?.role === 'admin'" class="settings-card">
      <template #header>
        <div class="card-header">
          <el-icon><User /></el-icon>
          <span>添加组织成员</span>
        </div>
      </template>
      <el-form :model="newUser" label-width="100px" label-position="left" class="admin-user-form">
        <el-form-item label="邮箱">
          <el-input v-model="newUser.email" type="email" autocomplete="off" placeholder="member@company.com" />
        </el-form-item>
        <el-form-item label="初始密码">
          <el-input v-model="newUser.password" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="newUser.displayName" placeholder="可选" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="creatingUser" @click="submitNewUser">创建账号</el-button>
        </el-form-item>
      </el-form>
      <p class="form-tip">新成员与当前账号同属一组织，共享全部会话；密码至少 8 位。</p>
    </el-card>

    <el-card v-if="!isEnterpriseBuild" class="settings-card">
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
import { reactive, ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useSettingsStore } from '@/stores/settings'
import { useAuthStore } from '@/stores/auth'
import { apiUrl, isEnterpriseBuild } from '@/services/enterpriseApi'
import { chatCompletion } from '@/services/llm'
import {
  catalogMatchingApiUrl,
  PROVIDER_DEFAULT_API,
  inferDefaultApiFromLlmHost,
  type ModelProvider,
} from '@/services/modelCatalog'

const settingsStore = useSettingsStore()
const authStore = useAuthStore()
const testing = ref(false)
const creatingUser = ref(false)

const form = reactive({ ...settingsStore.settings })

const newUser = reactive({
  email: '',
  password: '',
  displayName: '',
})

const catalogSourceUrl = computed(() => {
  const u = form.apiUrl?.trim()
  if (u) return u
  if (isEnterpriseBuild && authStore.publicLlm?.host) {
    return inferDefaultApiFromLlmHost(authStore.publicLlm.host)
  }
  return ''
})

const catalogMatches = computed(() => catalogMatchingApiUrl(catalogSourceUrl.value))

watch(
  () => authStore.publicLlm?.model,
  (m) => {
    if (!isEnterpriseBuild || !m || form.model?.trim()) return
    form.model = m
  },
  { immediate: true },
)

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
  if (!isEnterpriseBuild && !form.apiKey) {
    ElMessage.warning('请先填写 API Key')
    return
  }
  if (isEnterpriseBuild && !settingsStore.isConfigured()) {
    ElMessage.warning('服务端未配置模型网关')
    return
  }
  testing.value = true
  try {
    const reply = await chatCompletion(
      [{ role: 'user', content: '你好，请用一句话回复确认连接成功。' }],
      { ...form },
    )
    ElMessage.success(`连接成功！回复: ${reply.slice(0, 60)}`)
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    ElMessage.error(`连接失败: ${msg}`)
  } finally {
    testing.value = false
  }
}

async function submitNewUser() {
  const email = newUser.email.trim().toLowerCase()
  if (!email || !newUser.password || newUser.password.length < 8) {
    ElMessage.warning('请填写邮箱与至少 8 位密码')
    return
  }
  creatingUser.value = true
  try {
    const r = await fetch(apiUrl('/admin/users'), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email,
        password: newUser.password,
        displayName: newUser.displayName.trim() || undefined,
        role: 'member',
      }),
    })
    const data = await r.json().catch(() => ({}))
    if (!r.ok) {
      throw new Error(typeof data.error === 'string' ? data.error : '创建失败')
    }
    ElMessage.success(`已创建 ${email}`)
    newUser.email = ''
    newUser.password = ''
    newUser.displayName = ''
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '创建失败')
  } finally {
    creatingUser.value = false
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
