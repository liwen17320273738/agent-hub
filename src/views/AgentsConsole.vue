<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  listRuntimeRoles,
  listRuntimeTools,
  runAgentByRole,
  runAgentStream,
  type AgentRunResponse,
  type AgentStreamEvent,
  type RuntimeRole,
  type RuntimeTool,
} from '@/services/agentApi'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

interface ProgressEntry {
  id: number
  kind: 'started' | 'tool-call' | 'tool-result' | 'phase' | 'completed' | 'error'
  label: string
  detail?: string
  ts: number
}

const roles = ref<RuntimeRole[]>([])
const tools = ref<RuntimeTool[]>([])
const loadingMeta = ref(false)

const selectedRole = ref<string>('')
const taskInput = ref<string>('')
const maxSteps = ref<number>(5)
const temperature = ref<number>(0.5)
const modelOverride = ref<string>('')
const useStream = ref<boolean>(true)

const isRunning = ref(false)
const progress = ref<ProgressEntry[]>([])
const finalResult = ref<AgentRunResponse | null>(null)
const finalError = ref<string>('')

const abortCtrl = ref<AbortController | null>(null)
let progressId = 0

const primaryRoles = computed(() => roles.value.filter((r) => r.is_primary))
const aliasRoles = computed(() => roles.value.filter((r) => !r.is_primary))
const selectedRoleMeta = computed(() =>
  roles.value.find((r) => r.role === selectedRole.value),
)

async function loadMeta() {
  loadingMeta.value = true
  try {
    const [r, t] = await Promise.all([listRuntimeRoles(), listRuntimeTools()])
    roles.value = r.roles || []
    tools.value = t.tools || []
    if (!selectedRole.value && primaryRoles.value.length > 0) {
      selectedRole.value = primaryRoles.value[0].role
    }
  } catch (e) {
    ElMessage.error(`加载元数据失败：${(e as Error).message}`)
  } finally {
    loadingMeta.value = false
  }
}

function pushProgress(entry: Omit<ProgressEntry, 'id' | 'ts'>) {
  progress.value.push({ ...entry, id: ++progressId, ts: Date.now() })
}

function resetRun() {
  progress.value = []
  finalResult.value = null
  finalError.value = ''
}

async function runOnce() {
  if (!selectedRole.value) {
    ElMessage.warning(t('agentsConsole.elMessage_1'))
    return
  }
  if (!taskInput.value.trim()) {
    ElMessage.warning(t('agentsConsole.elMessage_2'))
    return
  }
  resetRun()
  isRunning.value = true

  const body = {
    task: taskInput.value.trim(),
    max_steps: maxSteps.value,
    temperature: temperature.value,
    ...(modelOverride.value.trim() ? { model_override: modelOverride.value.trim() } : {}),
  }

  try {
    if (!useStream.value) {
      pushProgress({ kind: 'started', label: `调用 ${selectedRole.value}` })
      const res = await runAgentByRole(selectedRole.value, body)
      finalResult.value = res
      pushProgress({
        kind: 'completed',
        label: res.ok ? '执行完成' : `失败：${res.error || ''}`,
        detail: `${res.steps} 步 / ${res.elapsed_ms}ms / ${res.model}`,
      })
    } else {
      const ctrl = new AbortController()
      abortCtrl.value = ctrl
      const stream = runAgentStream(selectedRole.value, body, ctrl.signal)
      for await (const evt of stream as AsyncIterable<AgentStreamEvent>) {
        handleStreamEvent(evt)
      }
    }
  } catch (e) {
    finalError.value = (e as Error).message
    pushProgress({ kind: 'error', label: '请求失败', detail: finalError.value })
  } finally {
    isRunning.value = false
    abortCtrl.value = null
  }
}

function handleStreamEvent(evt: AgentStreamEvent) {
  if (evt.event === 'started') {
    pushProgress({ kind: 'started', label: `调用 ${evt.agent_id}`, detail: evt.task })
    return
  }
  if (evt.event === 'progress') {
    const phase = evt.phase
    const data = evt.data || {}
    if (phase === 'agent:tool-call') {
      pushProgress({
        kind: 'tool-call',
        label: `工具：${(data as { tool?: string }).tool || '?'}`,
        detail: JSON.stringify((data as { input?: unknown }).input || {}, null, 0).slice(0, 200),
      })
    } else if (phase === 'agent:execute-start') {
      pushProgress({ kind: 'phase', label: '思考中…' })
    } else if (phase === 'agent:execute-complete') {
      pushProgress({
        kind: 'phase',
        label: '总结中…',
        detail: `${(data as { steps?: number }).steps ?? 0} 步`,
      })
    } else {
      pushProgress({ kind: 'phase', label: phase, detail: JSON.stringify(data).slice(0, 200) })
    }
    return
  }
  if (evt.event === 'completed') {
    finalResult.value = {
      ok: evt.ok,
      agent_id: evt.agent_id,
      content: evt.content,
      steps: evt.steps,
      observations: [],
      model: evt.model,
      verification: evt.verification ?? null,
      error: evt.error ?? null,
      elapsed_ms: evt.elapsed_ms,
      mcp_tools_loaded: evt.mcp_tools_loaded ?? [],
    }
    pushProgress({
      kind: 'completed',
      label: evt.ok ? '完成' : `失败：${evt.error || ''}`,
      detail: `${evt.steps} 步 / ${evt.elapsed_ms}ms`,
    })
    return
  }
  if (evt.event === 'error') {
    finalError.value = evt.error
    pushProgress({ kind: 'error', label: '错误', detail: evt.error })
  }
}

function abort() {
  abortCtrl.value?.abort()
  isRunning.value = false
  pushProgress({ kind: 'error', label: '已中止' })
}

function pickQuickPrompt(p: string) {
  taskInput.value = p
}

const QUICK_PROMPTS: Record<string, string[]> = {
  developer: ['给现有 backend/app/api/auth.py 写一份 pytest 测试', '把 README 翻译为英文'],
  security: ['审一下 backend/app/api/auth.py 的 JWT 处理流程，找潜在安全风险'],
  qa: ['为登录流程设计 5 条端到端测试用例（含异常场景）'],
  architect: ['对当前后端给一份 3 层架构图说明（mermaid）'],
  product: ['基于"AI 一句话生成 PPT"的需求，输出 PRD 大纲'],
  designer: ['为一个极简 Todo 应用，给出色板 + 主页布局描述'],
}

const quickList = computed(() => QUICK_PROMPTS[selectedRole.value] || [])

onMounted(loadMeta)
</script>

<template>
  <div class="agents-console">
    <div class="page-header">
      <div>
        <h1>{{ t('agentsConsole.text_1') }}</h1>
        <p class="page-subtitle">
          直接召唤任意专家完成单次任务，无需走完整流水线。支持流式查看推理与工具调用。
        </p>
      </div>
      <el-button :loading="loadingMeta" plain @click="loadMeta">{{ t('agentsConsole.text_2') }}</el-button>
    </div>

    <div class="layout">
      <aside class="sidebar">
        <div class="sidebar-section">
          <div class="section-title">{{ t('agentsConsole.text_3') }}</div>
          <div class="role-grid">
            <div
              v-for="r in primaryRoles"
              :key="r.role"
              :class="['role-chip', { active: r.role === selectedRole }]"
              @click="selectedRole = r.role"
            >
              <div class="role-name">{{ r.role }}</div>
              <div class="role-seed">{{ r.seed_id }}</div>
            </div>
          </div>
        </div>
        <div class="sidebar-section">
          <div class="section-title">{{ t('agentsConsole.text_4') }}</div>
          <div class="alias-list">
            <el-tag
              v-for="r in aliasRoles"
              :key="r.role"
              :type="r.role === selectedRole ? 'primary' : 'info'"
              effect="plain"
              class="alias-tag"
              @click="selectedRole = r.role"
            >
              {{ r.role }}
            </el-tag>
          </div>
        </div>
      </aside>

      <section class="main">
        <div class="card">
          <div class="card-header">
            <div>
              <div class="card-title">
                {{ selectedRoleMeta?.role || '请选择专家' }}
              </div>
              <div class="card-subtitle">{{ selectedRoleMeta?.short_prompt || '' }}</div>
            </div>
            <div class="meta">
              <el-tag size="small" type="info">{{ tools.length }} 个工具可用</el-tag>
            </div>
          </div>

          <el-input
            v-model="taskInput"
            type="textarea"
            :rows="6"
            :placeholder="t('agentsConsole.placeholder_1')"
            :disabled="isRunning"
          />

          <div v-if="quickList.length" class="quick-prompts">
            <span class="qp-label">{{ t('agentsConsole.text_5') }}</span>
            <el-tag
              v-for="(p, i) in quickList"
              :key="i"
              type="success"
              effect="plain"
              class="qp-tag"
              @click="pickQuickPrompt(p)"
            >
              {{ p }}
            </el-tag>
          </div>

          <div class="config-row">
            <div class="config-item">
              <span class="config-label">{{ t('agentsConsole.text_6') }}</span>
              <el-input-number v-model="maxSteps" :min="1" :max="20" size="small" />
            </div>
            <div class="config-item">
              <span class="config-label">{{ t('agentsConsole.text_7') }}</span>
              <el-input-number
                v-model="temperature"
                :min="0"
                :max="2"
                :step="0.1"
                :precision="1"
                size="small"
              />
            </div>
            <div class="config-item">
              <span class="config-label">{{ t('agentsConsole.text_8') }}</span>
              <el-input
                v-model="modelOverride"
                size="small"
                :placeholder="t('agentsConsole.placeholder_2')"
                style="width: 200px"
              />
            </div>
            <div class="config-item">
              <el-switch v-model="useStream" active-text="流式" inactive-text="阻塞" />
            </div>
          </div>

          <div class="actions">
            <el-button
              type="primary"
              size="large"
              :loading="isRunning"
              :disabled="!selectedRole || !taskInput.trim()"
              @click="runOnce"
            >
              召唤
            </el-button>
            <el-button v-if="isRunning && useStream" size="large" @click="abort">{{ t('agentsConsole.text_9') }}</el-button>
          </div>
        </div>

        <div v-if="progress.length" class="card">
          <div class="card-title">{{ t('agentsConsole.text_10') }}</div>
          <div class="progress-list">
            <div v-for="p in progress" :key="p.id" :class="['p-item', `kind-${p.kind}`]">
              <div class="p-icon"></div>
              <div class="p-body">
                <div class="p-label">{{ p.label }}</div>
                <div v-if="p.detail" class="p-detail">{{ p.detail }}</div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="finalResult" class="card result-card">
          <div class="card-header">
            <div class="card-title">
              {{ finalResult.ok ? '✓ 执行结果' : '✗ 执行失败' }}
            </div>
            <div class="meta">
              <el-tag size="small" :type="finalResult.ok ? 'success' : 'danger'">
                {{ finalResult.steps }} 步 / {{ finalResult.elapsed_ms }}ms
              </el-tag>
              <el-tag v-if="finalResult.model" size="small" type="info" class="model-tag">
                {{ finalResult.model }}
              </el-tag>
              <el-tag
                v-if="finalResult.verification"
                size="small"
                :type="finalResult.verification === 'pass' ? 'success' : 'warning'"
                class="model-tag"
              >
                校验：{{ finalResult.verification }}
              </el-tag>
            </div>
          </div>
          <pre class="result-content">{{ finalResult.content || finalResult.error }}</pre>
          <div
            v-if="finalResult.mcp_tools_loaded && finalResult.mcp_tools_loaded.length"
            class="mcp-row"
          >
            <span class="mcp-label">{{ t('agentsConsole.text_11') }}</span>
            <el-tag
              v-for="t in finalResult.mcp_tools_loaded"
              :key="t"
              size="small"
              effect="plain"
              type="warning"
            >
              {{ t }}
            </el-tag>
          </div>
        </div>

        <div v-if="finalError && !finalResult" class="card error-card">
          <div class="card-title">{{ t('agentsConsole.text_12') }}</div>
          <pre class="result-content">{{ finalError }}</pre>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.agents-console {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px;
}
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 20px;
}
.page-header h1 {
  margin: 0;
  font-size: 22px;
}
.page-subtitle {
  margin-top: 6px;
  color: var(--text-secondary, #606266);
  font-size: 13px;
}
.layout {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: 20px;
}
.sidebar {
  background: var(--bg-secondary, #fafafa);
  border: 1px solid var(--border-color, #ebeef5);
  border-radius: 8px;
  padding: 16px;
  height: fit-content;
  position: sticky;
  top: 20px;
}
.sidebar-section + .sidebar-section {
  margin-top: 16px;
}
.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary, #909399);
  margin-bottom: 8px;
  text-transform: uppercase;
}
.role-grid {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.role-chip {
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.15s;
}
.role-chip:hover {
  background: var(--bg-tertiary, #f0f2f5);
}
.role-chip.active {
  background: var(--primary-bg, #ecf5ff);
  border-color: var(--el-color-primary, #409eff);
}
.role-name {
  font-weight: 500;
  font-size: 13px;
}
.role-seed {
  font-size: 11px;
  color: var(--text-secondary, #909399);
  margin-top: 2px;
}
.alias-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.alias-tag {
  cursor: pointer;
  font-size: 11px;
}
.main {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}
.card {
  background: #fff;
  border: 1px solid var(--border-color, #ebeef5);
  border-radius: 10px;
  padding: 18px;
}
.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 12px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 4px;
}
.card-subtitle {
  font-size: 12px;
  color: var(--text-secondary, #909399);
  line-height: 1.5;
  max-width: 600px;
}
.meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.model-tag {
  font-family: ui-monospace, SFMono-Regular, monospace;
}
.quick-prompts {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.qp-label {
  font-size: 12px;
  color: var(--text-secondary, #909399);
}
.qp-tag {
  cursor: pointer;
  font-size: 11px;
}
.config-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px dashed var(--border-color, #ebeef5);
}
.config-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.config-label {
  font-size: 12px;
  color: var(--text-secondary, #909399);
}
.actions {
  margin-top: 14px;
  display: flex;
  gap: 8px;
}
.progress-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.p-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 10px;
  border-left: 2px solid var(--border-color, #ebeef5);
  background: var(--bg-secondary, #fafafa);
  border-radius: 0 6px 6px 0;
}
.p-icon {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 6px;
  background: var(--el-color-info, #909399);
  flex-shrink: 0;
}
.kind-started .p-icon,
.kind-completed .p-icon {
  background: var(--el-color-success, #67c23a);
}
.kind-tool-call .p-icon {
  background: var(--el-color-warning, #e6a23c);
}
.kind-error .p-icon {
  background: var(--el-color-danger, #f56c6c);
}
.kind-error {
  border-left-color: var(--el-color-danger, #f56c6c);
}
.p-label {
  font-size: 13px;
  font-weight: 500;
}
.p-detail {
  font-size: 11px;
  color: var(--text-secondary, #909399);
  margin-top: 2px;
  word-break: break-all;
  font-family: ui-monospace, SFMono-Regular, monospace;
}
.result-content {
  margin: 0;
  padding: 14px;
  background: var(--bg-secondary, #f8f9fa);
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.6;
  max-height: 500px;
  overflow: auto;
}
.error-card {
  border-color: var(--el-color-danger, #f56c6c);
}
.error-card .card-title {
  color: var(--el-color-danger, #f56c6c);
}
.mcp-row {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.mcp-label {
  font-size: 12px;
  color: var(--text-secondary, #909399);
}
</style>
