<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
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
  addOpen.value = true
}

function buildConfig(): Record<string, unknown> {
  if (!addForm.api_key.trim()) return {}
  return {
    api_key: addForm.api_key.trim(),
    auth_header: addForm.auth_header || 'Authorization',
    auth_scheme: addForm.auth_scheme || 'Bearer',
  }
}

async function probe() {
  if (!addForm.server_url.trim()) {
    ElMessage.warning('请填写 server URL')
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
    ElMessage.warning('请选择要绑定的 agent')
    return
  }
  if (!addForm.name.trim() || !addForm.server_url.trim()) {
    ElMessage.warning('请填写 name 和 server URL')
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
    ElMessage.success('已添加')
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
    ElMessage.success('已删除')
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
        <h1>MCP 服务器</h1>
        <p class="page-subtitle">
          把外部工具（GitHub、Slack、文件系统、自建服务…）通过 MCP 协议接给某个 agent。
          挂上以后，agent 在 <router-link to="/agents-console">专家工作台</router-link> 与流水线里都能直接调用。
        </p>
      </div>
      <div class="actions">
        <el-button :loading="loading" plain @click="refresh">刷新</el-button>
        <el-button type="primary" @click="openAdd">+ 添加 MCP</el-button>
      </div>
    </div>

    <div class="filter-bar">
      <span class="filter-label">按 agent 过滤：</span>
      <el-select
        v-model="filterAgent"
        placeholder="全部"
        clearable
        size="small"
        style="width: 240px"
      >
        <el-option v-for="a in agents" :key="a.id" :label="`${a.name} (${a.id})`" :value="a.id" />
      </el-select>
      <span class="counter">共 {{ filteredMcps.length }} 个</span>
    </div>

    <div v-if="!loading && filteredMcps.length === 0" class="empty">
      <p>还没有 MCP 服务器。点右上角"+ 添加 MCP"开始。</p>
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
          <el-button size="small" type="danger" plain @click="removeOne(rec)">删除</el-button>
        </div>
      </div>
    </div>

    <!-- Add dialog -->
    <el-dialog v-model="addOpen" title="添加 MCP 服务器" width="640px" :close-on-click-modal="false">
      <el-form label-width="120px" label-position="left">
        <el-form-item label="绑定到 agent">
          <el-select v-model="addForm.agent_id" placeholder="选择 agent" filterable>
            <el-option
              v-for="a in agents"
              :key="a.id"
              :label="`${a.name} (${a.id})`"
              :value="a.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="addForm.name" placeholder="github / slack / filesystem ..." />
        </el-form-item>
        <el-form-item label="Server URL">
          <el-input v-model="addForm.server_url" placeholder="https://example.com/mcp" />
        </el-form-item>
        <el-form-item label="API Key（可选）">
          <el-input v-model="addForm.api_key" type="password" show-password placeholder="留空表示无认证" />
        </el-form-item>
        <el-form-item v-if="addForm.api_key.trim()" label="认证头">
          <el-input v-model="addForm.auth_header" style="width: 200px" />
          <el-input v-model="addForm.auth_scheme" style="width: 120px; margin-left: 8px" placeholder="Bearer" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="addForm.enabled" />
        </el-form-item>
        <el-form-item label="自动拉取工具">
          <el-switch v-model="addForm.auto_refresh" />
          <span class="hint">建议开启：保存时立即拉一次工具目录</span>
        </el-form-item>
      </el-form>

      <div class="probe-row">
        <el-button :loading="probing" @click="probe">先探测</el-button>
        <span v-if="probeResult" :class="['probe-status', probeResult.ok ? 'ok' : 'fail']">
          {{ probeResult.ok ? `✓ 探测成功，${probeResult.tools?.length || 0} 个工具` : `✗ ${probeResult.error}` }}
          <span class="probe-elapsed">({{ probeResult.elapsed_ms }}ms)</span>
        </span>
      </div>

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
        <el-button @click="addOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitAdd">保存</el-button>
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
</style>
