<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchAgents, type AgentConfig } from '@/services/api'
import {
  callTool,
  createMcp,
  deleteMcp,
  listMcps,
  probeAnonymous,
  refreshTools,
  type McpRecord,
  type McpToolSpec,
  type ProbeResult,
} from '@/services/mcpApi'
import {
  MCP_PRESETS,
  getMcpPreset,
  findPresetByServerUrl,
  type McpPreset,
} from '@/data/mcpPresets'
import { getAgentMcpUrlSuggestions } from '@/data/agentMcpUrlSuggestions'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

interface McpUrlPickOption {
  value: string
  label: string
  nameHint: string
}

const agents = ref<AgentConfig[]>([])
const mcps = ref<McpRecord[]>([])
const loading = ref(false)

const filterAgent = ref<string>('')

const filteredMcps = computed(() =>
  filterAgent.value ? mcps.value.filter((m) => m.agent_id === filterAgent.value) : mcps.value,
)

async function refresh() {
  loading.value = true
  try {
    const [a, m] = await Promise.all([fetchAgents(), listMcps()])
    agents.value = a
    mcps.value = m
  } catch (e) {
    ElMessage.error(`加载失败：${(e as Error).message}`)
  } finally {
    loading.value = false
  }
}

const agentName = (id: string) => agents.value.find((a) => a.id === id)?.name || id

// ───── Add dialog ────────────────────────────────────────────────
const addOpen = ref(false)
const addForm = reactive({
  agent_id: '',
  name: '',
  server_url: '',
  api_key: '',
  auth_header: 'Authorization',
  auth_scheme: 'Bearer',
  enabled: true,
  auto_refresh: true,
})
const probing = ref(false)
const probeResult = ref<ProbeResult | null>(null)
const submitting = ref(false)
/** 添加对话框：选中的 MCP 预设 */
const selectedPresetId = ref<string>('custom')
/** 预设自带的 config（如 headers），与 API Key 合并后提交 */
const presetConfigExtras = ref<Record<string, unknown>>({})

function applyPreset(p: McpPreset) {
  addForm.name = p.name
  addForm.server_url = p.serverUrl
  presetConfigExtras.value = p.configExtras ? { ...p.configExtras } : {}
  probeResult.value = null
}

function onPresetChange(id: string) {
  const p = getMcpPreset(id)
  if (p) applyPreset(p)
}

function openAdd() {
  Object.assign(addForm, {
    agent_id: '',
    name: '',
    server_url: '',
    api_key: '',
    auth_header: 'Authorization',
    auth_scheme: 'Bearer',
    enabled: true,
    auto_refresh: true,
  })
  probeResult.value = null
  selectedPresetId.value = 'custom'
  presetConfigExtras.value = {}
  mcpUrlOptions.value = []
  addOpen.value = true
}

const selectedPresetHint = computed(() => {
  const p = getMcpPreset(selectedPresetId.value)
  return p?.description ?? ''
})

const selectedPresetDocUrl = computed(() => getMcpPreset(selectedPresetId.value)?.docUrl ?? '')

/** 选择 agent 后加载：推荐 + 预设 + 系统已有 MCP 地址 */
const mcpUrlOptions = ref<McpUrlPickOption[]>([])
const loadingUrlOptions = ref(false)

async function loadMcpUrlOptionsForAgent(agentId: string) {
  loadingUrlOptions.value = true
  try {
    const list: McpUrlPickOption[] = []
    const seen = new Set<string>()
    const push = (label: string, value: string, nameHint: string) => {
      const v = value.trim()
      if (!v || seen.has(v)) return
      seen.add(v)
      list.push({ label, value: v, nameHint })
    }

    const an = agentName(agentId)

    // 1) 当前 agent 已在库中绑定的 MCP（最相关）
    try {
      const mine = await listMcps(agentId)
      for (const m of mine) {
        if (!m.server_url?.trim()) continue
        push(`[${an} · 已有] ${m.name}`, m.server_url, m.name)
      }
    } catch {
      /* 忽略 */
    }

    // 2) 按角色配置的推荐占位（可编辑 src/data/agentMcpUrlSuggestions.ts）
    for (const s of getAgentMcpUrlSuggestions(agentId)) {
      push(`[推荐] ${s.label}`, s.serverUrl, s.nameHint)
    }

    // 3) 全局预设（官方远程 / 本地）
    for (const p of MCP_PRESETS) {
      if (p.id === 'custom' || !p.serverUrl.trim()) continue
      const tag = p.kind === 'official' ? '官方' : p.kind === 'local' ? '本地' : '预设'
      push(`[${tag}] ${p.label}`, p.serverUrl, p.name.trim() || 'mcp')
    }

    mcpUrlOptions.value = list
  } finally {
    loadingUrlOptions.value = false
  }
}

function onServerUrlChange(val: string) {
  const opt = mcpUrlOptions.value.find((o) => o.value === val)
  if (opt && !addForm.name.trim()) {
    addForm.name = opt.nameHint
  }
  const byUrl = findPresetByServerUrl(typeof val === 'string' ? val : '')
  if (byUrl) {
    presetConfigExtras.value = byUrl.configExtras ? { ...byUrl.configExtras } : {}
    selectedPresetId.value = byUrl.id
  }
  probeResult.value = null
}

watch(
  () => addForm.agent_id,
  async (id, prevId) => {
    if (!addOpen.value) return
    if (id && id !== prevId) {
      addForm.server_url = ''
      addForm.name = ''
      selectedPresetId.value = 'custom'
      presetConfigExtras.value = {}
      probeResult.value = null
    }
    if (id) {
      await loadMcpUrlOptionsForAgent(id)
    } else {
      mcpUrlOptions.value = []
    }
  },
)

function buildConfig(): Record<string, unknown> {
  const base: Record<string, unknown> = { ...presetConfigExtras.value }
  if (!addForm.api_key.trim()) return base
  return {
    ...base,
    api_key: addForm.api_key.trim(),
    auth_header: addForm.auth_header || 'Authorization',
    auth_scheme: addForm.auth_scheme || 'Bearer',
  }
}

/** 探测失败时解释：发往 MCP 上游的 Bearer 来自「API Key」，与浏览器请求本站 API 的 JWT 无关 */
const probeFailureHint = computed(() => {
  if (!probeResult.value || probeResult.value.ok) return ''
  const errRaw = probeResult.value.error || ''
  const err = errRaw.toLowerCase()
  const url = addForm.server_url.trim().toLowerCase()
  const hasKey = !!addForm.api_key.trim()
  const looks401 =
    err.includes('401') ||
    err.includes('authorization') ||
    err.includes('unauthorized') ||
    err.includes('invalid_token')
  // 已填令牌但仍 invalid / 未激活：换 token 或重走 OAuth
  if (
    hasKey &&
    (err.includes('not active') || err.includes('invalid_token') || err.includes('expired'))
  ) {
    if (
      (url.includes('127.0.0.1:3232') || url.includes('localhost:3232')) &&
      url.includes('/mcp')
    ) {
      return '「Token is not active」表示当前填入的不是有效的 OAuth access_token，或已过期/被撤销（example-remote-server 重启后内存会话也会失效）。请在 MCP Inspector 里用 Streamable HTTP 连接 http://localhost:3232/mcp 重新完成授权，复制新的 access_token（一般为 eyJ 开头的 JWT），不要填授权码、refresh_token 或随机十六进制串。'
    }
    return '上游拒绝了当前 Bearer：令牌可能过期、已撤销或格式不对。请重新获取 OAuth access_token 或 PAT 后再试。'
  }
  const noKey = !hasKey
  if (!noKey || !looks401) return ''
  if (url.includes('githubcopilot.com')) {
    return 'GitHub 远程 MCP 要求上游请求带 Authorization。请在上面的「API Key」中填写 GitHub PAT 或 OAuth access token（会作为 Bearer 发给 api.githubcopilot.com）。浏览器里访问本站接口的 JWT 不会自动转给 GitHub。'
  }
  const isExample3232 =
    (url.includes('127.0.0.1:3232') || url.includes('localhost:3232')) && url.includes('/mcp')
  if (isExample3232) {
    return '本机 example-remote-server 对 MCP 启用 OAuth，必须先取得 access_token 并填入「API Key」（后端会以 Bearer 发给该地址）。请运行 npx -y @modelcontextprotocol/inspector 连接 http://localhost:3232/mcp 完成授权，或在其仓库运行 node examples/client.js；空 API Key 探测必然 401。'
  }
  return '若远端需要认证，请在「API Key」中填写令牌；探测请求体里的 config 为空时，后端不会代你添加 Authorization。'
})

async function probe() {
  if (!addForm.server_url.trim()) {
    ElMessage.warning(t('mcpServers.elMessage_1'))
    return
  }
  probing.value = true
  try {
    probeResult.value = await probeAnonymous(addForm.server_url.trim(), buildConfig())
    if (!probeResult.value.ok) {
      ElMessage.error(`探测失败：${probeResult.value.error}`)
    } else {
      ElMessage.success(`发现 ${probeResult.value.tools?.length || 0} 个工具`)
    }
  } catch (e) {
    ElMessage.error(`探测异常：${(e as Error).message}`)
    probeResult.value = null
  } finally {
    probing.value = false
  }
}

async function submitAdd() {
  if (!addForm.agent_id) {
    ElMessage.warning(t('mcpServers.elMessage_2'))
    return
  }
  if (!addForm.name.trim() || !addForm.server_url.trim()) {
    ElMessage.warning(t('mcpServers.elMessage_3'))
    return
  }
  submitting.value = true
  try {
    await createMcp({
      agent_id: addForm.agent_id,
      name: addForm.name.trim(),
      server_url: addForm.server_url.trim(),
      config: buildConfig(),
      enabled: addForm.enabled,
      auto_refresh: addForm.auto_refresh,
    })
    ElMessage.success(t('mcpServers.elMessage_4'))
    addOpen.value = false
    await refresh()
  } catch (e) {
    ElMessage.error(`保存失败：${(e as Error).message}`)
  } finally {
    submitting.value = false
  }
}

// ───── Per-row actions ───────────────────────────────────────────

const refreshing = ref<Record<string, boolean>>({})
async function refreshOne(rec: McpRecord) {
  refreshing.value[rec.id] = true
  try {
    const r = await refreshTools(rec.id)
    ElMessage.success(`已刷新，共 ${r.tool_count} 个工具`)
    await refresh()
  } catch (e) {
    ElMessage.error(`刷新失败：${(e as Error).message}`)
  } finally {
    refreshing.value[rec.id] = false
  }
}

async function removeOne(rec: McpRecord) {
  await ElMessageBox.confirm(
    `确认删除 MCP 绑定 "${rec.name}"（agent ${rec.agent_id}）？`,
    '确认',
    { type: 'warning' },
  )
  try {
    await deleteMcp(rec.id)
    ElMessage.success(t('mcpServers.elMessage_5'))
    await refresh()
  } catch (e) {
    ElMessage.error(`删除失败：${(e as Error).message}`)
  }
}

// ───── Tool drawer ───────────────────────────────────────────────

const toolDrawer = ref(false)
const focusedMcp = ref<McpRecord | null>(null)
const focusedTool = ref<McpToolSpec | null>(null)
const toolArgs = ref('{}')
const callRunning = ref(false)
const callResult = ref<unknown>(null)

function openToolDrawer(rec: McpRecord) {
  focusedMcp.value = rec
  focusedTool.value = null
  toolArgs.value = '{}'
  callResult.value = null
  toolDrawer.value = true
}

function pickTool(t: McpToolSpec) {
  focusedTool.value = t
  callResult.value = null
  const props = ((t.inputSchema as Record<string, unknown>)?.properties as Record<string, unknown>) || {}
  const sample: Record<string, unknown> = {}
  for (const key of Object.keys(props)) sample[key] = ''
  toolArgs.value = JSON.stringify(sample, null, 2)
}

async function runTool() {
  if (!focusedMcp.value || !focusedTool.value) return
  let args: Record<string, unknown>
  try {
    args = JSON.parse(toolArgs.value || '{}')
  } catch (e) {
    ElMessage.error(`参数 JSON 解析失败：${(e as Error).message}`)
    return
  }
  callRunning.value = true
  callResult.value = null
  try {
    callResult.value = await callTool(focusedMcp.value.id, focusedTool.value.name, args)
  } catch (e) {
    callResult.value = { error: (e as Error).message }
  } finally {
    callRunning.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="mcp-page">
    <div class="page-header">
      <div>
        <h1>{{ t('mcpServers.text_1') }}</h1>
        <p class="page-subtitle">
          把外部工具（GitHub、Slack、文件系统、自建服务…）通过 MCP 协议接给某个 agent。
          挂上以后，agent 在 <router-link to="/agents-console">{{ t('mcpServers.text_2') }}</router-link> 与流水线里都能直接调用。
        </p>
      </div>
      <div class="actions">
        <el-button :loading="loading" plain @click="refresh">{{ t('mcpServers.text_3') }}</el-button>
        <el-button type="primary" @click="openAdd">{{ t('mcpServers.text_4') }}</el-button>
      </div>
    </div>

    <div class="filter-bar">
      <span class="filter-label">{{ t('mcpServers.text_5') }}</span>
      <el-select
        v-model="filterAgent"
        :placeholder="t('mcpServers.placeholder_1')"
        clearable
        size="small"
        style="width: 240px"
      >
        <el-option v-for="a in agents" :key="a.id" :label="`${a.name} (${a.id})`" :value="a.id" />
      </el-select>
      <span class="counter">共 {{ filteredMcps.length }} 个</span>
    </div>

    <div v-if="!loading && filteredMcps.length === 0" class="empty">
      <p>{{ t('mcpServers.text_6') }}</p>
    </div>

    <div class="mcp-grid">
      <div v-for="rec in filteredMcps" :key="rec.id" class="mcp-card">
        <div class="mcp-header">
          <div>
            <div class="mcp-name">{{ rec.name }}</div>
            <div class="mcp-url">{{ rec.server_url }}</div>
          </div>
          <el-tag :type="rec.enabled ? 'success' : 'info'" size="small">
            {{ rec.enabled ? '启用' : '停用' }}
          </el-tag>
        </div>
        <div class="mcp-meta">
          <el-tag size="small" effect="plain">绑定：{{ agentName(rec.agent_id) }}</el-tag>
          <el-tag size="small" effect="plain" type="warning">{{ rec.tool_count }} 个工具</el-tag>
        </div>
        <div v-if="rec.tools.length" class="tool-row">
          <el-tag
            v-for="t in rec.tools.slice(0, 5)"
            :key="t.name"
            size="small"
            type="warning"
            effect="plain"
            class="tool-tag"
          >
            {{ t.name }}
          </el-tag>
          <span v-if="rec.tools.length > 5" class="more-tag">+{{ rec.tools.length - 5 }}</span>
        </div>
        <div class="mcp-actions">
          <el-button size="small" :loading="!!refreshing[rec.id]" @click="refreshOne(rec)">
            刷新工具
          </el-button>
          <el-button size="small" type="primary" plain @click="openToolDrawer(rec)">
            调试工具
          </el-button>
          <el-button size="small" type="danger" plain @click="removeOne(rec)">{{ t('mcpServers.text_7') }}</el-button>
        </div>
      </div>
    </div>

    <!-- Add dialog -->
    <el-dialog v-model="addOpen" :title="t('mcpServers.title_1')" width="640px" :close-on-click-modal="false">
      <el-form label-width="120px" label-position="left">
        <el-form-item :label="t('mcpServers.label_1')">
          <el-select v-model="addForm.agent_id" :placeholder="t('mcpServers.placeholder_2')" filterable>
            <el-option
              v-for="a in agents"
              :key="a.id"
              :label="`${a.name} (${a.id})`"
              :value="a.id"
            />
          </el-select>
          <p class="preset-hint">
            选择后将自动检索：① 该 agent 已绑定的 MCP 地址 ② 该角色推荐占位 ③ 全局预设模板，并填入下方「Server URL」下拉框。
          </p>
        </el-form-item>
        <el-form-item :label="t('mcpServers.label_2')">
          <el-select
            v-model="selectedPresetId"
            :placeholder="t('mcpServers.placeholder_3')"
            filterable
            style="width: 100%"
            :disabled="!addForm.agent_id"
            @change="onPresetChange"
          >
            <el-option
              v-for="p in MCP_PRESETS"
              :key="p.id"
              :label="p.label"
              :value="p.id"
            />
          </el-select>
          <p v-if="selectedPresetHint" class="preset-hint">{{ selectedPresetHint }}</p>
          <a
            v-if="selectedPresetDocUrl"
            :href="selectedPresetDocUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="preset-doc-link"
          >{{ t('mcpServers.text_8') }}</a>
        </el-form-item>
        <el-form-item :label="t('mcpServers.label_3')">
          <el-input v-model="addForm.name" placeholder="github / slack / filesystem ..." />
        </el-form-item>
        <el-form-item label="Server URL">
          <el-select
            v-model="addForm.server_url"
            filterable
            allow-create
            default-first-option
            clearable
            :placeholder="t('mcpServers.placeholder_4')"
            style="width: 100%"
            :loading="loadingUrlOptions"
            :disabled="!addForm.agent_id"
            @change="onServerUrlChange"
          >
            <el-option
              v-for="(o, idx) in mcpUrlOptions"
              :key="`${idx}-${o.value}`"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
          <p v-if="!addForm.agent_id" class="preset-hint">{{ t('mcpServers.text_9') }}</p>
          <p v-else-if="!loadingUrlOptions && mcpUrlOptions.length === 0" class="preset-hint">
            暂无候选地址，可直接在输入框中填写 URL。
          </p>
        </el-form-item>
        <el-form-item :label="t('mcpServers.label_4')">
          <el-input v-model="addForm.api_key" type="password" show-password :placeholder="t('mcpServers.placeholder_5')" />
          <p class="preset-hint">
            GitHub 官方远程：填 PAT 或 OAuth token（由后端以 Bearer 发给 MCP 地址）。这与浏览器请求本站 /api 时带的登录 JWT 是两路认证；无令牌时 config 为空，探测会收到 401。
          </p>
        </el-form-item>
        <el-form-item v-if="addForm.api_key.trim()" :label="t('mcpServers.label_5')">
          <el-input v-model="addForm.auth_header" style="width: 200px" />
          <el-input v-model="addForm.auth_scheme" style="width: 120px; margin-left: 8px" placeholder="Bearer" />
        </el-form-item>
        <el-form-item :label="t('mcpServers.label_6')">
          <el-switch v-model="addForm.enabled" />
        </el-form-item>
        <el-form-item :label="t('mcpServers.label_7')">
          <el-switch v-model="addForm.auto_refresh" />
          <span class="hint">{{ t('mcpServers.text_10') }}</span>
        </el-form-item>
      </el-form>

      <div class="probe-row">
        <el-button :loading="probing" @click="probe">{{ t('mcpServers.text_11') }}</el-button>
        <span v-if="probeResult" :class="['probe-status', probeResult.ok ? 'ok' : 'fail']">
          {{ probeResult.ok ? `✓ 探测成功，${probeResult.tools?.length || 0} 个工具` : `✗ ${probeResult.error}` }}
          <span class="probe-elapsed">({{ probeResult.elapsed_ms }}ms)</span>
        </span>
      </div>
      <p v-if="probeFailureHint" class="preset-hint probe-failure-hint">{{ probeFailureHint }}</p>

      <div v-if="probeResult?.ok && probeResult.tools?.length" class="probe-tools">
        <el-tag
          v-for="t in probeResult.tools"
          :key="t.name"
          size="small"
          type="success"
          effect="plain"
          class="tool-tag"
        >
          {{ t.name }}
        </el-tag>
      </div>

      <template #footer>
        <el-button @click="addOpen = false">{{ t('mcpServers.text_12') }}</el-button>
        <el-button type="primary" :loading="submitting" @click="submitAdd">{{ t('mcpServers.text_13') }}</el-button>
      </template>
    </el-dialog>

    <!-- Tool drawer -->
    <el-drawer v-model="toolDrawer" :title="`调试 ${focusedMcp?.name || ''} 的工具`" size="640px">
      <div v-if="focusedMcp" class="drawer-body">
        <div class="drawer-section">
          <div class="section-title">工具列表</div>
          <div class="tool-pick">
            <div
              v-for="t in focusedMcp.tools"
              :key="t.name"
              :class="['tool-card', { active: focusedTool?.name === t.name }]"
              @click="pickTool(t)"
            >
              <div class="tool-card-name">{{ t.name }}</div>
              <div v-if="t.description" class="tool-card-desc">{{ t.description }}</div>
            </div>
          </div>
        </div>

        <div v-if="focusedTool" class="drawer-section">
          <div class="section-title">参数 (JSON)</div>
          <el-input v-model="toolArgs" type="textarea" :rows="8" />
          <div class="drawer-actions">
            <el-button type="primary" :loading="callRunning" @click="runTool">调用</el-button>
          </div>
        </div>

        <div v-if="callResult !== null" class="drawer-section">
          <div class="section-title">结果</div>
          <pre class="result-pre">{{ JSON.stringify(callResult, null, 2) }}</pre>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.mcp-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 18px;
  gap: 20px;
}
.page-header h1 {
  margin: 0;
  font-size: 22px;
}
.page-subtitle {
  margin-top: 6px;
  color: var(--text-secondary, #606266);
  font-size: 13px;
  max-width: 700px;
}
.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  padding: 10px 12px;
  background: var(--bg-secondary, #fafafa);
  border-radius: 6px;
}
.filter-label {
  font-size: 12px;
  color: var(--text-secondary, #909399);
}
.counter {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-secondary, #909399);
}
.empty {
  text-align: center;
  padding: 60px 0;
  color: var(--text-secondary, #909399);
}
.mcp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 14px;
}
.mcp-card {
  background: #fff;
  border: 1px solid var(--border-color, #ebeef5);
  border-radius: 10px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.mcp-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}
.mcp-name {
  font-weight: 600;
  font-size: 14px;
}
.mcp-url {
  font-size: 11px;
  color: var(--text-secondary, #909399);
  font-family: ui-monospace, SFMono-Regular, monospace;
  margin-top: 3px;
  word-break: break-all;
}
.mcp-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.tool-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}
.tool-tag {
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 11px;
}
.more-tag {
  font-size: 11px;
  color: var(--text-secondary, #909399);
}
.mcp-actions {
  display: flex;
  gap: 6px;
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px dashed var(--border-color, #ebeef5);
}
.hint {
  font-size: 11px;
  color: var(--text-secondary, #909399);
  margin-left: 8px;
}
.probe-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-color, #ebeef5);
  margin-top: 8px;
}
.probe-failure-hint {
  margin-top: 6px;
  line-height: 1.45;
}
.probe-status.ok {
  color: var(--el-color-success, #67c23a);
  font-size: 12px;
}
.probe-status.fail {
  color: var(--el-color-danger, #f56c6c);
  font-size: 12px;
}
.probe-elapsed {
  color: var(--text-secondary, #909399);
  margin-left: 6px;
}
.probe-tools {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.drawer-body {
  padding: 0 16px 24px;
}
.drawer-section + .drawer-section {
  margin-top: 18px;
}
.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary, #606266);
  margin-bottom: 8px;
  text-transform: uppercase;
}
.tool-pick {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.tool-card {
  padding: 10px 12px;
  border: 1px solid var(--border-color, #ebeef5);
  border-radius: 6px;
  cursor: pointer;
}
.tool-card:hover {
  background: var(--bg-tertiary, #f5f7fa);
}
.tool-card.active {
  background: var(--primary-bg, #ecf5ff);
  border-color: var(--el-color-primary, #409eff);
}
.tool-card-name {
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 13px;
  font-weight: 600;
}
.tool-card-desc {
  font-size: 11px;
  color: var(--text-secondary, #909399);
  margin-top: 3px;
}
.drawer-actions {
  margin-top: 8px;
}
.result-pre {
  margin: 0;
  padding: 12px;
  background: var(--bg-secondary, #f8f9fa);
  border-radius: 6px;
  max-height: 400px;
  overflow: auto;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
.actions {
  display: flex;
  gap: 8px;
}
.preset-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--text-secondary, #909399);
  line-height: 1.45;
}
.preset-doc-link {
  display: inline-block;
  margin-top: 6px;
  font-size: 12px;
}
</style>
