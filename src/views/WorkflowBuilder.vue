<template>
  <!--
    Workflow Builder MVP (D1 + D2 of the 2-week plan).

    Scope today:
      ✅  Vue Flow canvas with custom AgentStageNode
      ✅  Hydrate from any backend template (`/api/pipeline/templates`)
      ✅  Add / delete / connect stages
      ✅  Live cycle + duplicate-stage-id detection (red border + banner)
      ✅  Side drawer for editing one stage at a time
      ✅  Persist to localStorage on every change
      ✅  Export / Import JSON
      ✅  Convert to backend DAGStage shape (preview JSON in dialog)

    D3 + D5 (this commit):
      ✅  "Run" button → POST /pipeline/tasks (template="custom",
          custom_stages=…) → POST /pipeline/tasks/{id}/dag-run
      ✅  Live SSE overlay: nodes turn idle → running → done / failed /
          rejected based on stage:* and pipeline:dag-* events
      ✅  Server CRUD on saved workflows (Save / Open / Delete)
      ✅  Left-rail palette: drag a role onto the canvas to add
  -->
  <div class="workflow-builder">
    <header class="wb-header">
      <div class="left">
        <h1>Workflow Builder</h1>
        <span class="subtitle">
          拖拽编排 AI 军团 DAG · 每次改动自动存本地
        </span>
      </div>
      <div class="right">
        <el-select
          v-model="selectedTemplate"
          placeholder="加载模板"
          size="small"
          style="width: 180px"
          :disabled="loadingTemplates"
          @change="onTemplateSelect"
        >
          <el-option
            v-for="(t, key) in templates"
            :key="key"
            :label="`${t.icon}  ${t.label}`"
            :value="key"
          />
        </el-select>
        <el-button size="small" @click="addStage">
          <el-icon><Plus /></el-icon>
          新增阶段
        </el-button>
        <el-button size="small" @click="autoLayout">自动布局</el-button>
        <el-button size="small" @click="openSaveDialog">
          <el-icon><Folder /></el-icon>
          {{ currentSavedId ? '保存' : '保存到服务器' }}
        </el-button>
        <el-button size="small" @click="openLoadDialog">打开</el-button>
        <el-button size="small" @click="showJsonPreview = true">
          <el-icon><DocumentCopy /></el-icon>
          查看 JSON
        </el-button>
        <el-button size="small" @click="exportJson">导出</el-button>
        <el-upload
          accept=".json,application/json"
          :show-file-list="false"
          :auto-upload="false"
          :on-change="onImportFile"
        >
          <el-button size="small">导入</el-button>
        </el-upload>
        <el-button size="small" type="danger" plain @click="resetCanvas">
          清空
        </el-button>
        <el-divider direction="vertical" />
        <el-button
          size="small"
          type="primary"
          :disabled="!!topology.warning || nodes.length === 0 || isRunning"
          :loading="isRunning"
          @click="openRunDialog"
        >
          <el-icon><VideoPlay /></el-icon>
          {{ isRunning ? '执行中…' : 'Run' }}
        </el-button>
        <el-tag
          v-if="sseStatus !== 'disconnected' || isRunning"
          :type="sseStatus === 'connected' ? 'success' : 'info'"
          size="small"
          effect="dark"
        >
          SSE: {{ sseStatusLabel }}
        </el-tag>
      </div>
    </header>

    <el-alert
      v-if="topology.warning"
      :title="topology.warning"
      type="error"
      show-icon
      :closable="false"
      class="topo-banner"
    />

    <div class="builder-body">
      <StagePalette />
      <div
        ref="canvasWrap"
        class="canvas-wrap"
        @dragover.prevent="onCanvasDragOver"
        @drop="onCanvasDrop"
      >
        <VueFlow
          v-model:nodes="nodes"
          v-model:edges="edges"
          :default-edge-options="defaultEdgeOptions"
          :node-types="nodeTypes"
          :min-zoom="0.3"
          :max-zoom="1.6"
          fit-view-on-init
          @node-click="onNodeClick"
        >
          <Background pattern-color="#1e293b" :gap="20" />
          <MiniMap pannable zoomable />
          <Controls />
        </VueFlow>
      </div>
    </div>

    <StageConfigDrawer
      v-model:visible="drawerOpen"
      :node-id="selectedNodeId"
      :data="selectedNodeData"
      :depends-on="selectedDeps"
      :other-stage-ids="otherStageIds"
      @delete="deleteStage"
    />

    <el-dialog
      v-model="showSaveDialog"
      :title="currentSavedId ? '更新已保存的 Workflow' : '保存到服务器'"
      width="480px"
    >
      <el-form label-width="80px" label-position="left">
        <el-form-item label="名称" required>
          <el-input
            v-model="saveForm.name"
            placeholder="例如：Web App 标准 SDLC"
            maxlength="100"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="saveForm.description"
            type="textarea"
            :rows="3"
            placeholder="（可选）这套 workflow 的目标 / 适用场景"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSaveDialog = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="!saveForm.name.trim()"
          :loading="savingWorkflow"
          @click="submitSave"
        >
          {{ currentSavedId ? '更新' : '保存' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="showLoadDialog"
      title="打开已保存的 Workflow"
      width="640px"
    >
      <div v-if="loadingWorkflows" class="wf-empty">加载中…</div>
      <div v-else-if="!savedWorkflows.length" class="wf-empty">
        还没有保存的 workflow — 先在画布上画一套，然后点"保存到服务器"。
      </div>
      <ul v-else class="wf-list">
        <li
          v-for="w in savedWorkflows"
          :key="w.id"
          class="wf-row"
          :class="{ active: w.id === currentSavedId }"
        >
          <div class="wf-meta">
            <div class="wf-name">{{ w.name }}</div>
            <div class="wf-desc">{{ w.description || '— 无描述 —' }}</div>
            <div class="wf-extra">
              {{ stageCountOf(w) }} 个阶段 · 更新于 {{ formatDate(w.updatedAt) }}
            </div>
          </div>
          <div class="wf-actions">
            <el-button size="small" type="primary" @click="loadFromServer(w)">
              打开
            </el-button>
            <el-button
              size="small"
              type="danger"
              plain
              @click="confirmDeleteSaved(w)"
            >
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </li>
      </ul>
      <template #footer>
        <el-button @click="showLoadDialog = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="showRunDialog"
      title="运行 Workflow"
      width="520px"
    >
      <el-form label-width="100px" label-position="left">
        <el-form-item label="任务标题" required>
          <el-input
            v-model="runForm.title"
            placeholder="例如：实现用户登录"
            maxlength="200"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="任务描述">
          <el-input
            v-model="runForm.description"
            type="textarea"
            :rows="4"
            placeholder="（可选）补充上下文 / 验收标准 / 链接"
          />
        </el-form-item>
        <el-form-item label="项目路径">
          <el-input
            v-model="runForm.projectPath"
            placeholder="（可选）/path/to/repo 或留空"
          />
        </el-form-item>
        <el-alert
          type="info"
          :closable="false"
          show-icon
          :title="`将以 custom 模板提交 ${nodes.length} 个阶段`"
          description="提交后画布会切换到执行视图，节点状态实时更新；任务详情可在 AI 军团流水线里查看。"
        />
      </el-form>
      <template #footer>
        <el-button @click="showRunDialog = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="!runForm.title.trim()"
          :loading="submittingRun"
          @click="submitRun"
        >
          创建并运行
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="showJsonPreview"
      title="后端 DAG JSON 预览"
      width="640px"
    >
      <div v-if="conversionError" class="conv-error">
        <el-alert
          :title="conversionError.message"
          type="error"
          show-icon
          :closable="false"
        />
      </div>
      <pre v-else class="json-preview">{{ backendJsonPretty }}</pre>
      <template #footer>
        <el-button @click="showJsonPreview = false">关闭</el-button>
        <el-button
          v-if="!conversionError"
          type="primary"
          @click="copyBackendJson"
        >
          <el-icon><DocumentCopy /></el-icon>
          复制 JSON
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, markRaw, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, DocumentCopy, Folder, Plus, VideoPlay } from '@element-plus/icons-vue'
import { useVueFlow, VueFlow, type Edge, type Node } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'

import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

import AgentStageNode from '@/components/builder/AgentStageNode.vue'
import StageConfigDrawer from '@/components/builder/StageConfigDrawer.vue'
import StagePalette from '@/components/builder/StagePalette.vue'
import {
  builderToStages,
  checkTopology,
  exportDocAsJson,
  importDocFromJson,
  loadDocLocal,
  saveDocLocal,
  stagesToCustomApiPayload,
  templateToBuilder,
  type BuilderEdge,
  type BuilderNode,
  type WorkflowDoc,
} from '@/services/workflowBuilder'
import {
  createTask,
  fetchTemplates,
  runDagPipeline,
  subscribePipelineEvents,
  type SSEStatus,
} from '@/services/pipelineApi'
import {
  createWorkflow,
  deleteWorkflow,
  listWorkflows,
  updateWorkflow,
  type SavedWorkflow,
} from '@/services/workflowsApi'
import type { PipelineEvent } from '@/agents/types'

// ───────────────────────────────────────────────────────────────────
// Vue Flow needs node-types to be NON-reactive (markRaw) — otherwise
// it'll complain about "components should not be reactive". This is
// the most common gotcha when wiring custom nodes; do not remove.
// ───────────────────────────────────────────────────────────────────
const nodeTypes = { agentStage: markRaw(AgentStageNode) }

const defaultEdgeOptions = {
  type: 'smoothstep',
  animated: true,
  style: { stroke: '#475569', strokeWidth: 1.5 },
}

// ── Vue Flow's own state, mirrored from BuilderNode/BuilderEdge ──
// We keep `nodes`/`edges` as Vue Flow's `Node[]` / `Edge[]` (which
// just adds a `type` field); the rest of our code talks to
// `BuilderNode` shape-compatible objects via `n.data`.
const nodes = ref<Node[]>([])
const edges = ref<Edge[]>([])

// ── Selection / drawer ──────────────────────────────────────────
const drawerOpen = ref(false)
const selectedNodeId = ref<string | null>(null)
const selectedNodeData = computed(() => {
  if (!selectedNodeId.value) return null
  const n = nodes.value.find((x) => x.id === selectedNodeId.value)
  return (n?.data as BuilderNode['data']) || null
})
const selectedDeps = computed<string[]>(() => {
  if (!selectedNodeId.value) return []
  const idToStage = new Map<string, string>()
  for (const n of nodes.value) idToStage.set(n.id, (n.data as any).stageId)
  return edges.value
    .filter((e) => e.target === selectedNodeId.value)
    .map((e) => idToStage.get(e.source) || '')
    .filter(Boolean)
})
const otherStageIds = computed(() =>
  nodes.value
    .filter((n) => n.id !== selectedNodeId.value)
    .map((n) => (n.data as any).stageId as string),
)

function onNodeClick({ node }: { node: Node }) {
  selectedNodeId.value = node.id
  drawerOpen.value = true
}

// ── Templates ───────────────────────────────────────────────────
const templates = ref<Awaited<ReturnType<typeof fetchTemplates>>>({})
const loadingTemplates = ref(false)
const selectedTemplate = ref<string | null>(null)

async function loadTemplates() {
  loadingTemplates.value = true
  try {
    templates.value = await fetchTemplates()
  } catch (err: any) {
    // Auth required / backend down: don't block the builder, just
    // show a hint on the dropdown so the user can still draw from
    // scratch or import a JSON.
    ElMessage.warning(`加载模板失败：${err?.message || err}`)
  } finally {
    loadingTemplates.value = false
  }
}

function onTemplateSelect(name: string) {
  const t = templates.value[name]
  if (!t) return
  const { nodes: ns, edges: es } = templateToBuilder(t)
  applyDoc({
    version: 1,
    name: `template:${name}`,
    nodes: ns,
    edges: es,
    baseTemplate: name,
    updatedAt: Date.now(),
  })
  ElMessage.success(`已加载模板：${t.label}`)
}

// ── Doc apply / persistence ─────────────────────────────────────
function asNodes(bnodes: BuilderNode[]): Node[] {
  return bnodes.map((n) => ({
    id: n.id,
    type: 'agentStage',
    position: n.position,
    data: { ...n.data },
  }))
}
function asEdges(be: BuilderEdge[]): Edge[] {
  return be.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    type: 'smoothstep',
    animated: true,
  }))
}

function applyDoc(doc: WorkflowDoc) {
  nodes.value = asNodes(doc.nodes)
  edges.value = asEdges(doc.edges)
  selectedNodeId.value = null
  drawerOpen.value = false
}

function currentDoc(): WorkflowDoc {
  return {
    version: 1,
    name: 'workflow',
    nodes: nodes.value.map((n) => ({
      id: n.id,
      position: n.position,
      data: { ...(n.data as BuilderNode['data']) },
    })),
    edges: edges.value.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
    })),
    baseTemplate: selectedTemplate.value,
    updatedAt: Date.now(),
  }
}

// Debounced persistence — every meaningful change ⇒ save. The 250ms
// gap means dragging a node doesn't write 60 times/second.
let persistTimer: ReturnType<typeof setTimeout> | null = null
function schedulePersist() {
  if (persistTimer) clearTimeout(persistTimer)
  persistTimer = setTimeout(() => {
    saveDocLocal(currentDoc())
  }, 250)
}
watch([nodes, edges], schedulePersist, { deep: true })

// ── Topology check (live) ───────────────────────────────────────
const topology = computed(() => {
  if (nodes.value.length === 0) return { warning: '' }
  const bn = nodes.value.map((n) => ({
    id: n.id,
    position: n.position,
    data: { ...(n.data as BuilderNode['data']) },
  }))
  const be = edges.value.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
  }))
  // Duplicate stage_ids first — we want the more specific message.
  const seen = new Set<string>()
  const dups: string[] = []
  for (const n of bn) {
    if (seen.has(n.data.stageId)) dups.push(n.data.stageId)
    seen.add(n.data.stageId)
  }
  if (dups.length) {
    return { warning: `阶段 ID 重复：${[...new Set(dups)].join(', ')}` }
  }
  const r = checkTopology(bn, be)
  if (!r.ok) {
    return { warning: `检测到环依赖：${r.cycleNodes.join(' ↔ ')}` }
  }
  return { warning: '' }
})

// Sync `data.warning` so the node re-styles itself.
watch(topology, (t) => {
  if (!t.warning) {
    for (const n of nodes.value) (n.data as any).warning = ''
    return
  }
  const cycleSet = new Set(
    t.warning.startsWith('检测到环依赖')
      ? t.warning.replace('检测到环依赖：', '').split(' ↔ ')
      : [],
  )
  for (const n of nodes.value) {
    const sid = (n.data as any).stageId
    ;(n.data as any).warning = cycleSet.has(sid) ? '在环中' : ''
  }
})

// ── Stage CRUD ──────────────────────────────────────────────────
function uniqueStageId(seed: string): string {
  const taken = new Set(nodes.value.map((n) => (n.data as any).stageId as string))
  if (!taken.has(seed)) return seed
  let i = 2
  while (taken.has(`${seed}-${i}`)) i++
  return `${seed}-${i}`
}

function insertStage(opts: {
  position: { x: number; y: number }
  stageId: string
  label: string
  role: string
}) {
  const id = `n_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`
  nodes.value.push({
    id,
    type: 'agentStage',
    position: opts.position,
    data: {
      stageId: uniqueStageId(opts.stageId),
      label: opts.label,
      role: opts.role,
      rejectAction: 'self-heal',
      onFailure: 'halt',
    },
  })
  selectedNodeId.value = id
  drawerOpen.value = true
}

function addStage() {
  // Position: just to the right of the rightmost existing node.
  const maxX = nodes.value.length
    ? Math.max(...nodes.value.map((n) => n.position.x))
    : 60
  insertStage({
    position: { x: maxX + 240, y: 200 },
    stageId: 'stage',
    label: '新阶段',
    role: 'developer',
  })
}

// ── Drag-and-drop from StagePalette ─────────────────────────────
const canvasWrap = ref<HTMLElement | null>(null)
const PALETTE_MIME = 'application/x-agenthub-stage'

// `useVueFlow().project()` converts client-pixel coordinates to the
// canvas's transformed coordinate space (taking pan + zoom into
// account). Without it, dropping while zoomed-out drops the new node
// at the wrong place.
const { project } = useVueFlow()

function onCanvasDragOver(e: DragEvent) {
  if (!e.dataTransfer) return
  e.dataTransfer.dropEffect = 'move'
}

function onCanvasDrop(e: DragEvent) {
  if (!e.dataTransfer) return
  const raw =
    e.dataTransfer.getData(PALETTE_MIME) ||
    e.dataTransfer.getData('text/plain')
  if (!raw) return

  let payload: { role: string; label: string; stageId: string } | null = null
  try {
    payload = JSON.parse(raw)
  } catch {
    return
  }
  if (!payload || !payload.role) return

  e.preventDefault()

  const bounds = canvasWrap.value?.getBoundingClientRect()
  const px = bounds ? e.clientX - bounds.left : e.clientX
  const py = bounds ? e.clientY - bounds.top : e.clientY
  // Center the new node under the cursor (node is 220x100ish).
  const pos = project({ x: px - 110, y: py - 50 })

  insertStage({
    position: pos,
    stageId: payload.stageId || 'stage',
    label: payload.label || '新阶段',
    role: payload.role,
  })
}

function deleteStage(id: string) {
  nodes.value = nodes.value.filter((n) => n.id !== id)
  edges.value = edges.value.filter((e) => e.source !== id && e.target !== id)
  if (selectedNodeId.value === id) {
    selectedNodeId.value = null
    drawerOpen.value = false
  }
}

function resetCanvas() {
  nodes.value = []
  edges.value = []
  selectedNodeId.value = null
  drawerOpen.value = false
}

// ── Auto-layout (re-run depth bucketing without changing graph) ─
function autoLayout() {
  if (nodes.value.length === 0) return
  // Re-use templateToBuilder by going stages → builder.
  const conv = builderToStages(
    nodes.value.map((n) => ({
      id: n.id,
      position: n.position,
      data: { ...(n.data as BuilderNode['data']) },
    })),
    edges.value.map((e) => ({ id: e.id, source: e.source, target: e.target })),
  )
  if (!conv.ok) {
    ElMessage.warning('图未通过校验，无法重排')
    return
  }
  const fauxTemplate = {
    stages: conv.stages.map((s) => ({
      id: s.stageId,
      label: s.label,
      role: s.role,
      dependsOn: s.dependsOn,
    })),
  }
  const { nodes: ns } = templateToBuilder(fauxTemplate)
  // Map old data → new positions by stageId.
  const posByStage = new Map(ns.map((n) => [n.data.stageId, n.position]))
  for (const n of nodes.value) {
    const p = posByStage.get((n.data as any).stageId)
    if (p) n.position = { ...p }
  }
}

// ── Import / Export ─────────────────────────────────────────────
function exportJson() {
  const json = exportDocAsJson(currentDoc())
  const blob = new Blob([json], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `workflow-${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function onImportFile(file: any) {
  const f: File = file.raw || file
  const reader = new FileReader()
  reader.onload = () => {
    const doc = importDocFromJson(String(reader.result || ''))
    if (!doc) {
      ElMessage.error('JSON 格式无效（需 version: 1 的 WorkflowDoc）')
      return
    }
    applyDoc(doc)
    ElMessage.success('已导入')
  }
  reader.readAsText(f)
}

// ── Backend JSON preview ─────────────────────────────────────────
const showJsonPreview = ref(false)
const conversionResult = computed(() =>
  builderToStages(
    nodes.value.map((n) => ({
      id: n.id,
      position: n.position,
      data: { ...(n.data as BuilderNode['data']) },
    })),
    edges.value.map((e) => ({ id: e.id, source: e.source, target: e.target })),
  ),
)
const conversionError = computed(() =>
  conversionResult.value.ok ? null : conversionResult.value.error,
)
const backendJsonPretty = computed(() => {
  if (!conversionResult.value.ok) return ''
  return JSON.stringify(
    {
      template: 'custom',
      stages: conversionResult.value.stages,
    },
    null,
    2,
  )
})

async function copyBackendJson() {
  try {
    await navigator.clipboard.writeText(backendJsonPretty.value)
    ElMessage.success('已复制 JSON 到剪贴板')
  } catch {
    ElMessage.warning('剪贴板写入失败，请手动复制')
  }
}

// ── Saved workflows (server CRUD) ────────────────────────────────
const showSaveDialog = ref(false)
const showLoadDialog = ref(false)
const savingWorkflow = ref(false)
const loadingWorkflows = ref(false)
const savedWorkflows = ref<SavedWorkflow[]>([])
const currentSavedId = ref<string | null>(null)
const saveForm = ref({ name: '', description: '' })

function openSaveDialog() {
  if (nodes.value.length === 0) {
    ElMessage.warning('画布是空的，没有内容可保存')
    return
  }
  // Pre-fill from "current saved" if we're editing one already.
  if (currentSavedId.value) {
    const existing = savedWorkflows.value.find((w) => w.id === currentSavedId.value)
    if (existing) {
      saveForm.value.name = existing.name
      saveForm.value.description = existing.description
    }
  } else if (!saveForm.value.name) {
    saveForm.value.name = selectedTemplate.value
      ? `Workflow: ${selectedTemplate.value}`
      : `Workflow ${new Date().toLocaleString()}`
  }
  showSaveDialog.value = true
}

async function submitSave() {
  savingWorkflow.value = true
  try {
    const doc = currentDoc()
    doc.name = saveForm.value.name.trim() || doc.name
    if (currentSavedId.value) {
      const w = await updateWorkflow(currentSavedId.value, {
        name: saveForm.value.name.trim(),
        description: saveForm.value.description,
        doc,
      })
      ElMessage.success(`已更新「${w.name}」`)
    } else {
      const w = await createWorkflow({
        name: saveForm.value.name.trim(),
        description: saveForm.value.description,
        doc,
      })
      currentSavedId.value = w.id
      ElMessage.success(`已保存「${w.name}」`)
    }
    showSaveDialog.value = false
    await refreshSaved()
  } catch (err: any) {
    ElMessage.error(err?.message || '保存失败')
  } finally {
    savingWorkflow.value = false
  }
}

async function refreshSaved() {
  loadingWorkflows.value = true
  try {
    savedWorkflows.value = await listWorkflows()
  } catch (err: any) {
    ElMessage.warning(`无法加载已保存列表：${err?.message || err}`)
  } finally {
    loadingWorkflows.value = false
  }
}

async function openLoadDialog() {
  showLoadDialog.value = true
  await refreshSaved()
}

function loadFromServer(w: SavedWorkflow) {
  if (!w.doc || !Array.isArray(w.doc.nodes)) {
    ElMessage.error('该 workflow 的 doc 格式无效')
    return
  }
  applyDoc(w.doc)
  currentSavedId.value = w.id
  selectedTemplate.value = w.doc.baseTemplate || null
  showLoadDialog.value = false
  ElMessage.success(`已加载「${w.name}」`)
}

async function confirmDeleteSaved(w: SavedWorkflow) {
  try {
    await ElMessageBox.confirm(
      `确认删除 workflow「${w.name}」？此操作不可撤销。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteWorkflow(w.id)
    ElMessage.success(`已删除「${w.name}」`)
    if (currentSavedId.value === w.id) currentSavedId.value = null
    await refreshSaved()
  } catch (err: any) {
    ElMessage.error(err?.message || '删除失败')
  }
}

function stageCountOf(w: SavedWorkflow): number {
  return Array.isArray(w.doc?.nodes) ? w.doc.nodes.length : 0
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

// ── Run dialog + execute ─────────────────────────────────────────
const router = useRouter()

const showRunDialog = ref(false)
const submittingRun = ref(false)
const runForm = ref({ title: '', description: '', projectPath: '' })

// Live execution state. Cleared every time the user starts a new run.
const isRunning = ref(false)
const runningTaskId = ref<string | null>(null)
const sseStatus = ref<SSEStatus>('disconnected')
const sseStatusLabel = computed(() => {
  switch (sseStatus.value) {
    case 'connected': return '已连接'
    case 'connecting': return '连接中…'
    default: return '未连接'
  }
})

let unsubSSE: (() => void) | null = null

function openRunDialog() {
  if (topology.value.warning) {
    ElMessage.warning('画布有错误，无法运行')
    return
  }
  if (nodes.value.length === 0) {
    ElMessage.warning('请先添加至少一个阶段')
    return
  }
  // Default title to "based on" lineage so the user just hits Enter.
  if (!runForm.value.title) {
    const base = selectedTemplate.value || 'custom'
    runForm.value.title = `Workflow Builder: ${base}`
  }
  showRunDialog.value = true
}

async function submitRun() {
  // Re-check topology — guards against the user editing while the
  // dialog is open and dodges the "I clicked Run with a stale graph"
  // class of bug.
  const conv = builderToStages(
    nodes.value.map((n) => ({
      id: n.id,
      position: n.position,
      data: { ...(n.data as BuilderNode['data']) },
    })),
    edges.value.map((e) => ({ id: e.id, source: e.source, target: e.target })),
  )
  if (!conv.ok) {
    ElMessage.error(conv.error.message)
    return
  }

  submittingRun.value = true
  try {
    const customStages = stagesToCustomApiPayload(conv.stages)
    const task = await createTask({
      title: runForm.value.title.trim(),
      description: runForm.value.description.trim(),
      template: 'custom',
      project_path: runForm.value.projectPath.trim() || undefined,
      custom_stages: customStages,
    })

    // Reset visual state and jump straight into "executing" mode so
    // the user sees the SSE updates land on this canvas.
    runningTaskId.value = task.id
    isRunning.value = true
    initStageStatuses()
    startSSE()

    await runDagPipeline(task.id, { template: 'custom' })

    showRunDialog.value = false
    ElMessage.success(`任务 ${task.id.slice(0, 8)} 已提交，节点状态会实时更新`)
  } catch (err: any) {
    const detail =
      typeof err?.message === 'string' ? err.message : '运行失败，请检查后端日志'
    ElMessage.error(detail)
    isRunning.value = false
  } finally {
    submittingRun.value = false
  }
}

// ── Live execution overlay (SSE) ─────────────────────────────────
type RunStatus =
  | 'idle'
  | 'running'
  | 'done'
  | 'failed'
  | 'rejected'
  | 'awaiting'
  | 'skipped'

function setStageStatus(stageId: string, status: RunStatus, extra?: Record<string, unknown>) {
  for (const n of nodes.value) {
    if ((n.data as any).stageId !== stageId) continue
    n.data = { ...n.data, runStatus: status, ...(extra || {}) }
  }
}

function initStageStatuses() {
  for (const n of nodes.value) {
    n.data = { ...n.data, runStatus: 'idle' as RunStatus, lastError: '' }
  }
}

function startSSE() {
  if (unsubSSE) { unsubSSE(); unsubSSE = null }
  unsubSSE = subscribePipelineEvents(
    (evt: PipelineEvent) => onSSE(evt),
    (s) => { sseStatus.value = s },
  )
}

function stopSSE() {
  if (unsubSSE) { unsubSSE(); unsubSSE = null }
  sseStatus.value = 'disconnected'
}

function onSSE(evt: PipelineEvent) {
  const data = (evt.data || {}) as Record<string, unknown>
  // Filter by our currently-running task — the SSE channel is global.
  const eventTaskId = data.taskId as string | undefined
  if (runningTaskId.value && eventTaskId && eventTaskId !== runningTaskId.value) {
    return
  }

  const stageId = (data.stageId as string) || ''

  switch (evt.event) {
    case 'pipeline:dag-start':
      // Fresh run from the orchestrator — clear stale red badges.
      initStageStatuses()
      break

    case 'stage:processing':
      if (stageId) setStageStatus(stageId, 'running')
      break

    case 'stage:completed':
      if (stageId) setStageStatus(stageId, 'done')
      break

    case 'stage:retry':
      if (stageId) setStageStatus(stageId, 'running', { lastError: data.lastError || '' })
      break

    case 'stage:error':
      if (stageId) {
        setStageStatus(stageId, 'failed', { lastError: data.error || '执行失败' })
      }
      break

    case 'stage:awaiting-approval':
      if (stageId) setStageStatus(stageId, 'awaiting')
      break

    case 'stage:skipped':
      if (stageId) setStageStatus(stageId, 'skipped')
      break

    case 'pipeline:dag-branch':
      // Reviewer rejected → reset target stage back to running so the
      // user can see "we went back here for self-heal".
      {
        const target = data.to as string | undefined
        if (target) setStageStatus(target, 'rejected')
      }
      break

    case 'pipeline:rollback':
      if (stageId) setStageStatus(stageId, 'failed', { lastError: data.reason || '回滚' })
      break

    case 'pipeline:dag-completed':
      isRunning.value = false
      ElMessage.success('Workflow 执行完毕')
      break

    case 'pipeline:auto-paused':
      isRunning.value = false
      ElMessage.warning(`流水线暂停：${data.reason || '质量门未通过'}`)
      break
  }
}

async function openRunningTask() {
  if (!runningTaskId.value) return
  await router.push(`/pipeline/${runningTaskId.value}`)
}

// Expose for template — used by an "open task page" button if added.
void openRunningTask

// ── Boot ─────────────────────────────────────────────────────────
onMounted(async () => {
  await loadTemplates()

  // Try to restore the user's last canvas first; if there's nothing,
  // hydrate from the "full" template so first-paint is interesting.
  const saved = loadDocLocal()
  if (saved && saved.nodes.length) {
    applyDoc(saved)
    selectedTemplate.value = saved.baseTemplate || null
    return
  }
  if (templates.value['full']) {
    selectedTemplate.value = 'full'
    onTemplateSelect('full')
  }
})

onBeforeUnmount(() => {
  stopSSE()
})

// Suppress unused-import warnings in the rare case ElMessageBox isn't
// needed yet; keeps the import handy for follow-up "are you sure?"
// dialogs without re-flipping the import diff.
void ElMessageBox
</script>

<style scoped>
.workflow-builder {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 0px);
  background: #0f172a;
  color: #e2e8f0;
}

.wb-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid #1e293b;
  background: linear-gradient(180deg, #111827 0%, #0f172a 100%);
}
.wb-header .left h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #f1f5f9;
}
.wb-header .left .subtitle {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: #94a3b8;
}
.wb-header .right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.topo-banner {
  margin: 0;
  border-radius: 0;
}

.builder-body {
  flex: 1;
  display: flex;
  min-height: 0;
}
.canvas-wrap {
  flex: 1;
  min-height: 0;
  position: relative;
}

/* Vue Flow's default theme is light; force dark canvas. */
:deep(.vue-flow) {
  background: #0b1120;
}
:deep(.vue-flow__minimap) {
  background: #1f2937 !important;
  border: 1px solid #334155;
}
:deep(.vue-flow__controls) {
  background: #1f2937;
  border: 1px solid #334155;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}
:deep(.vue-flow__controls-button) {
  background: #1f2937;
  border-bottom: 1px solid #334155;
  color: #e2e8f0;
  fill: #e2e8f0;
}
:deep(.vue-flow__controls-button:hover) {
  background: #334155;
}
:deep(.vue-flow__edge-path) {
  stroke: #475569;
  stroke-width: 1.5;
}
:deep(.vue-flow__edge.selected .vue-flow__edge-path),
:deep(.vue-flow__edge:focus .vue-flow__edge-path) {
  stroke: #38bdf8;
  stroke-width: 2;
}
:deep(.vue-flow__connection-path) {
  stroke: #38bdf8;
}
:deep(.vue-flow__attribution) {
  display: none;
}

.wf-empty {
  padding: 32px 16px;
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
}
.wf-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 460px;
  overflow-y: auto;
}
.wf-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid #1e293b;
  border-radius: 8px;
  margin: 6px 0;
  background: #0f172a;
}
.wf-row.active {
  border-color: #38bdf8;
}
.wf-meta {
  flex: 1;
  min-width: 0;
}
.wf-name {
  font-size: 13px;
  font-weight: 600;
  color: #f1f5f9;
}
.wf-desc {
  margin-top: 2px;
  font-size: 12px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wf-extra {
  margin-top: 4px;
  font-size: 11px;
  color: #64748b;
}
.wf-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.json-preview {
  margin: 0;
  padding: 12px;
  background: #0f172a;
  color: #e2e8f0;
  border: 1px solid #1e293b;
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.5;
  max-height: 480px;
  overflow: auto;
}
.conv-error {
  padding: 6px 0;
}
</style>
