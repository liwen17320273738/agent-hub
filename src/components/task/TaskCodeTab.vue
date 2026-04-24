<template>
  <div class="coze-file-browser" :class="{ fullscreen: isFullscreen }">
    <!-- Top bar: tabs + search + storage info -->
    <div class="browser-topbar">
      <div class="topbar-tabs">
        <button
          v-for="tab in FILE_TABS"
          :key="tab.key"
          class="topbar-tab"
          :class="{ active: activeFileTab === tab.key }"
          @click="activeFileTab = tab.key"
        >
          {{ tab.label }}
          <span v-if="tab.count > 0" class="tab-count">{{ tab.count }}</span>
        </button>
      </div>
      <div class="topbar-right">
        <div class="search-box">
          <svg class="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
          </svg>
          <input
            v-model="searchQuery"
            class="search-input"
            placeholder="搜索文件..."
            type="text"
          />
        </div>
        <span class="storage-info">{{ totalSizeStr }}</span>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="browser-loading">
      <div class="loading-spinner"></div>
      <span>加载工作目录...</span>
    </div>

    <!-- Empty state -->
    <div v-else-if="!hasFiles" class="browser-empty">
      <div class="empty-illustration">
        <svg width="80" height="80" viewBox="0 0 80 80" fill="none">
          <rect x="12" y="18" width="56" height="48" rx="6" stroke="#3a3d47" stroke-width="1.5" fill="none"/>
          <path d="M12 30h56" stroke="#3a3d47" stroke-width="1.5"/>
          <rect x="20" y="24" width="6" height="3" rx="1.5" fill="#4a4d57"/>
          <rect x="28" y="24" width="6" height="3" rx="1.5" fill="#4a4d57"/>
          <rect x="36" y="24" width="6" height="3" rx="1.5" fill="#4a4d57"/>
          <rect x="24" y="40" width="20" height="2" rx="1" fill="#2c2f38"/>
          <rect x="24" y="46" width="32" height="2" rx="1" fill="#2c2f38"/>
          <rect x="24" y="52" width="14" height="2" rx="1" fill="#2c2f38"/>
        </svg>
      </div>
      <p class="empty-title">代码工件尚未生成</p>
      <p class="empty-desc">开发阶段完成后，Agent 提取的代码文件将自动显示在此处</p>
    </div>

    <!-- Main three-panel layout -->
    <div v-else class="browser-body">
      <!-- Left panel: File tree -->
      <div class="panel-tree" :style="{ width: treePanelWidth + 'px' }">
        <div class="tree-content">
          <!-- Source files group -->
          <div v-if="filteredGroupedSrc.length" class="file-group">
            <div class="group-header" @click="srcExpanded = !srcExpanded">
              <svg class="group-chevron" :class="{ open: srcExpanded }" width="12" height="12" viewBox="0 0 12 12">
                <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
              </svg>
              <svg class="group-icon folder-icon" width="16" height="16" viewBox="0 0 16 16">
                <path d="M1.5 3.5A1.5 1.5 0 013 2h3l1.5 1.5H13A1.5 1.5 0 0114.5 5v7a1.5 1.5 0 01-1.5 1.5H3A1.5 1.5 0 011.5 12V3.5z" fill="currentColor"/>
              </svg>
              <span class="group-name">源代码</span>
              <span class="group-badge">{{ filteredGroupedSrc.length }}</span>
            </div>
            <div v-show="srcExpanded" class="group-body">
              <template v-for="node in srcTreeNodes" :key="node.key">
                <!-- Directory node -->
                <div v-if="node.type === 'dir'" class="tree-dir">
                  <div class="tree-row dir-row" @click="toggleDir(node.key)">
                    <svg class="row-chevron" :class="{ open: expandedDirs[node.key] }" width="10" height="10" viewBox="0 0 12 12">
                      <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                    </svg>
                    <span class="row-icon">📂</span>
                    <span class="row-name">{{ node.label }}</span>
                    <span class="row-count">{{ node.children?.length }}</span>
                  </div>
                  <div v-show="expandedDirs[node.key]" class="dir-children">
                    <div
                      v-for="child in node.children"
                      :key="child.file!.path"
                      class="tree-row file-row"
                      :class="{ selected: selectedFile?.path === child.file!.path }"
                      @click="selectFile(child.file!)"
                    >
                      <span class="row-icon">{{ langIcon(child.file!.name) }}</span>
                      <span class="row-name" :title="child.file!.path">{{ child.file!.name }}</span>
                    </div>
                  </div>
                </div>
                <!-- File node -->
                <div
                  v-else
                  class="tree-row file-row"
                  :class="{ selected: selectedFile?.path === node.file!.path }"
                  @click="selectFile(node.file!)"
                >
                  <span class="row-icon">{{ langIcon(node.file!.name) }}</span>
                  <span class="row-name" :title="node.file!.path">{{ node.file!.name }}</span>
                </div>
              </template>
            </div>
          </div>

          <!-- Documents group -->
          <div class="file-group">
            <div class="group-header" @click="docsExpanded = !docsExpanded">
              <svg class="group-chevron" :class="{ open: docsExpanded }" width="12" height="12" viewBox="0 0 12 12">
                <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
              </svg>
              <svg class="group-icon doc-icon" width="16" height="16" viewBox="0 0 16 16">
                <path d="M4 1.5A1.5 1.5 0 015.5 0h5A1.5 1.5 0 0112 1.5V2h.5A1.5 1.5 0 0114 3.5v11A1.5 1.5 0 0112.5 16h-9A1.5 1.5 0 012 14.5v-11A1.5 1.5 0 013.5 2H4V1.5z" fill="currentColor"/>
              </svg>
              <span class="group-name">交付文档</span>
              <span class="group-badge docs-badge">{{ completedDocs }}/{{ totalDocs }}</span>
            </div>
            <div v-show="docsExpanded" class="group-body">
                <div
                  v-for="d in docsStatus"
                  :key="d.name"
                  class="tree-row file-row"
                  :class="{
                    selected: selectedDoc === d.name,
                    dimmed: !d.has_content,
                  }"
                  @click="selectDoc(d)"
                >
                  <span class="row-icon">{{ d.has_content ? '📝' : '📄' }}</span>
                  <span class="row-name">{{ d.title }}</span>
                  <span v-if="!d.has_content" class="row-pending">待生成</span>
                </div>
            </div>
          </div>

          <!-- Config / Root files group -->
          <div class="file-group" v-if="rootFiles.length">
            <div class="group-header" @click="rootExpanded = !rootExpanded">
              <svg class="group-chevron" :class="{ open: rootExpanded }" width="12" height="12" viewBox="0 0 12 12">
                <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
              </svg>
              <span class="row-icon" style="font-size:14px">⚙️</span>
              <span class="group-name">配置文件</span>
              <span class="group-badge">{{ rootFiles.length }}</span>
            </div>
            <div v-show="rootExpanded" class="group-body">
                <div
                  v-for="f in rootFiles"
                  :key="f.path"
                  class="tree-row file-row"
                  :class="{ selected: selectedFile?.path === f.path }"
                  @click="selectFile(f)"
                >
                  <span class="row-icon">{{ langIcon(f.name) }}</span>
                  <span class="row-name">{{ f.name }}</span>
                </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Resize handle -->
      <div class="resize-handle" @mousedown="startResize"></div>

      <!-- Middle panel: File list table -->
      <div class="panel-list">
        <table class="file-table">
          <thead>
            <tr>
              <th class="th-name">文件名称</th>
              <th class="th-time">创建时间</th>
              <th class="th-size">文件大小</th>
              <th class="th-actions"></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="f in filteredTableFiles"
              :key="f.path"
              class="table-row"
              :class="{ active: selectedFile?.path === f.path || selectedDoc === f.name }"
              @click="handleTableRowClick(f)"
            >
              <td class="td-name">
                <span class="td-icon">{{ langIcon(f.name) }}</span>
                <span class="td-filename">{{ f.name }}</span>
              </td>
              <td class="td-time">{{ f.time || '—' }}</td>
              <td class="td-size">{{ fmtSize(f.size) }}</td>
              <td class="td-actions">
                <button class="action-dot" title="更多操作" @click.stop="openContextMenu($event, f)">
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                    <circle cx="8" cy="3" r="1.5"/><circle cx="8" cy="8" r="1.5"/><circle cx="8" cy="13" r="1.5"/>
                  </svg>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="!filteredTableFiles.length" class="table-empty">
          <span>暂无匹配文件</span>
        </div>
      </div>

      <!-- Right panel: Code preview -->
      <div class="panel-preview" :class="{ 'no-file': !hasSelection }">
        <template v-if="hasSelection">
          <!-- Preview toolbar (Coze-style) -->
          <div class="preview-header">
            <div class="preview-title">
              <span class="preview-filename">{{ previewFileName }}</span>
            </div>
            <div class="preview-actions">
              <button class="action-btn" title="复制代码" @click="copyContent">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
                </svg>
              </button>
              <button class="action-btn" title="下载文件" @click="downloadFile">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
              </button>
              <button class="action-btn" title="全屏" @click="toggleFullscreen">
                <svg v-if="!isFullscreen" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>
                </svg>
                <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/>
                </svg>
              </button>
              <button class="action-btn close-btn" title="关闭预览" @click="clearSelection">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            </div>
          </div>

          <!-- Meta bar -->
          <div class="preview-meta">
            <span class="meta-path">{{ previewPath }}</span>
            <span v-if="previewLang" class="meta-lang">{{ previewLang }}</span>
            <span v-if="previewSizeStr" class="meta-size">{{ previewSizeStr }}</span>
          </div>

          <!-- Loading -->
          <div v-if="fileLoading" class="preview-loading">
            <div class="loading-spinner small"></div>
            <span>加载中...</span>
          </div>

          <!-- Code content with syntax highlight -->
          <div v-else-if="previewContent" class="preview-code-area" ref="codeAreaRef">
            <div class="line-gutter" aria-hidden="true">
              <span v-for="n in lineCount" :key="n" class="gutter-num">{{ n }}</span>
            </div>
            <div class="code-body" v-html="highlightedCode"></div>
          </div>

          <!-- Empty content -->
          <div v-else class="preview-no-content">
            <p>此文件暂无内容</p>
          </div>
        </template>

        <!-- No selection hint -->
        <div v-else class="preview-hint">
          <svg width="56" height="56" viewBox="0 0 56 56" fill="none">
            <rect x="8" y="12" width="40" height="32" rx="4" stroke="#3a3d47" stroke-width="1.5" fill="none"/>
            <path d="M8 20h40" stroke="#3a3d47" stroke-width="1.5"/>
            <circle cx="14" cy="16" r="2" fill="#ef4444" opacity="0.6"/>
            <circle cx="20" cy="16" r="2" fill="#f59e0b" opacity="0.6"/>
            <circle cx="26" cy="16" r="2" fill="#22c55e" opacity="0.6"/>
            <rect x="16" y="26" width="16" height="2" rx="1" fill="#2a2d36"/>
            <rect x="16" y="32" width="24" height="2" rx="1" fill="#2a2d36"/>
            <rect x="16" y="38" width="12" height="2" rx="1" fill="#2a2d36"/>
          </svg>
          <p class="hint-title">选择文件进行预览</p>
          <p class="hint-sub">支持语法高亮、行号、代码复制</p>
        </div>
      </div>
    </div>

    <!-- Copy toast -->
    <div v-if="showCopyToast" class="copy-toast">已复制到剪贴板</div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted, watch, nextTick } from 'vue'
import { getAuthToken } from '@/services/api'
import hljs from 'highlight.js'

interface WFile {
  path: string
  name: string
  size: number
  is_text: boolean
  hash: string
  time?: string
}

interface DocItem {
  name: string
  title: string
  exists: boolean
  has_content: boolean
  size: number
}

interface TreeNode {
  key: string
  label: string
  type: 'file' | 'dir'
  file?: WFile
  children?: TreeNode[]
}

interface TableFile {
  path: string
  name: string
  size: number
  is_text: boolean
  hash: string
  time: string
  isDoc?: boolean
  docItem?: DocItem
}

const props = defineProps<{ taskId: string }>()

const loading = ref(false)
const fileLoading = ref(false)
const allFiles = ref<WFile[]>([])
const docsStatus = ref<DocItem[]>([])
const selectedFile = ref<WFile | null>(null)
const selectedDoc = ref<string>('')
const previewContent = ref('')
const searchQuery = ref('')
const isFullscreen = ref(false)
const showCopyToast = ref(false)
const codeAreaRef = ref<HTMLElement | null>(null)

const activeFileTab = ref<'all' | 'src' | 'docs'>('all')
const srcExpanded = ref(true)
const docsExpanded = ref(true)
const rootExpanded = ref(false)
const expandedDirs = reactive<Record<string, boolean>>({})
const treePanelWidth = ref(200)

function toggleDir(key: string) {
  expandedDirs[key] = !expandedDirs[key]
}

const srcFiles = computed(() =>
  allFiles.value.filter(f => f.path.startsWith('src/') && f.is_text)
)

const filteredGroupedSrc = computed(() => {
  if (!searchQuery.value) return srcFiles.value
  const q = searchQuery.value.toLowerCase()
  return srcFiles.value.filter(f => f.path.toLowerCase().includes(q) || f.name.toLowerCase().includes(q))
})

const rootFiles = computed(() =>
  allFiles.value.filter(f => !f.path.startsWith('src/') && !f.path.startsWith('docs/') && f.is_text)
)

const srcTreeNodes = computed<TreeNode[]>(() => {
  return buildTree(filteredGroupedSrc.value, 'src/')
})

function buildTree(files: WFile[], prefix: string): TreeNode[] {
  const dirs: Record<string, WFile[]> = {}
  const loose: WFile[] = []

  for (const f of files) {
    const rel = f.path.slice(prefix.length)
    const slashIdx = rel.indexOf('/')
    if (slashIdx > 0) {
      const dirName = rel.slice(0, slashIdx)
      ;(dirs[dirName] ??= []).push(f)
    } else {
      loose.push(f)
    }
  }

  const nodes: TreeNode[] = []
  for (const [dirName, subFiles] of Object.entries(dirs).sort(([a], [b]) => a.localeCompare(b))) {
    const dirKey = `${prefix}${dirName}`
    if (!(dirKey in expandedDirs)) expandedDirs[dirKey] = true
    nodes.push({
      key: dirKey,
      label: dirName,
      type: 'dir',
      children: buildTree(subFiles, dirKey + '/'),
    })
  }
  for (const f of loose) {
    nodes.push({ key: f.path, label: f.name, type: 'file', file: f })
  }
  return nodes
}

const filteredTableFiles = computed<TableFile[]>(() => {
  let files: TableFile[] = []
  const q = searchQuery.value.toLowerCase()

  if (activeFileTab.value === 'all' || activeFileTab.value === 'src') {
    files.push(
      ...allFiles.value
        .filter(f => f.is_text && !f.path.startsWith('docs/'))
        .map(f => ({ ...f, time: '', isDoc: false }))
    )
  }

  if (activeFileTab.value === 'all' || activeFileTab.value === 'docs') {
    for (const d of docsStatus.value) {
      if (d.has_content) {
        files.push({
          path: `docs/${d.name}`,
          name: d.name,
          size: d.size,
          is_text: true,
          hash: '',
          time: '',
          isDoc: true,
          docItem: d,
        })
      }
    }
  }

  if (q) {
    files = files.filter(f => f.path.toLowerCase().includes(q) || f.name.toLowerCase().includes(q))
  }

  return files
})

const FILE_TABS = computed(() => [
  { key: 'all' as const, label: '全部文件', count: allFiles.value.length },
  { key: 'src' as const, label: '源代码', count: srcFiles.value.length },
  { key: 'docs' as const, label: '文档', count: completedDocs.value },
])

const hasFiles = computed(() => allFiles.value.length > 0 || docsStatus.value.some(d => d.has_content))
const hasSelection = computed(() => !!selectedFile.value || !!selectedDoc.value)
const completedDocs = computed(() => docsStatus.value.filter(d => d.has_content).length)
const totalDocs = computed(() => docsStatus.value.length)
const totalSizeStr = computed(() => {
  const total = allFiles.value.reduce((s, f) => s + f.size, 0)
  return `已用 ${fmtSize(total)}`
})
const lineCount = computed(() => previewContent.value.split('\n').length)

const previewFileName = computed(() => {
  if (selectedFile.value) return selectedFile.value.name
  if (selectedDoc.value) {
    const d = docsStatus.value.find(x => x.name === selectedDoc.value)
    return d?.title || selectedDoc.value
  }
  return ''
})

const previewPath = computed(() =>
  selectedFile.value?.path || (selectedDoc.value ? `docs/${selectedDoc.value}` : '')
)

const previewSizeStr = computed(() => {
  if (selectedFile.value) return fmtSize(selectedFile.value.size)
  const d = docsStatus.value.find(x => x.name === selectedDoc.value)
  return d ? fmtSize(d.size) : ''
})

const previewLang = computed(() => {
  const name = selectedFile.value?.name || selectedDoc.value || ''
  return detectLang(name)
})

const highlightedCode = computed(() => {
  if (!previewContent.value) return ''
  const lang = previewLang.value?.toLowerCase() || ''
  const hljsLang = LANG_TO_HLJS[lang] || lang
  try {
    if (hljsLang && hljs.getLanguage(hljsLang)) {
      const result = hljs.highlight(previewContent.value, { language: hljsLang })
      return result.value
    }
  } catch { /* fallback */ }
  return escapeHtml(previewContent.value)
})

const LANG_TO_HLJS: Record<string, string> = {
  python: 'python', typescript: 'typescript', tsx: 'typescript', javascript: 'javascript',
  vue: 'xml', html: 'xml', css: 'css', json: 'json', yaml: 'yaml',
  markdown: 'markdown', sql: 'sql', shell: 'bash', go: 'go', rust: 'rust',
  java: 'java', toml: 'ini', docker: 'dockerfile',
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function detectLang(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() || ''
  const map: Record<string, string> = {
    py: 'Python', ts: 'TypeScript', tsx: 'TSX', js: 'JavaScript',
    vue: 'Vue', html: 'HTML', css: 'CSS', json: 'JSON',
    yaml: 'YAML', yml: 'YAML', md: 'Markdown', sql: 'SQL',
    sh: 'Shell', go: 'Go', rs: 'Rust', java: 'Java',
    toml: 'TOML', dockerfile: 'Docker', txt: 'Text',
  }
  if (name.toLowerCase() === 'dockerfile') return 'Docker'
  return map[ext] || ''
}

function langIcon(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() || ''
  const map: Record<string, string> = {
    py: '🐍', ts: '🔷', tsx: '🔷', js: '🟡', jsx: '🟡', vue: '💚',
    html: '🌐', css: '🎨', scss: '🎨', json: '📋', yaml: '📄',
    yml: '📄', md: '📝', sql: '🗃️', sh: '⚡', toml: '⚙️',
    go: '🔵', rs: '🦀', java: '☕', dockerfile: '🐳', txt: '📄',
  }
  if (name.toLowerCase() === 'dockerfile') return '🐳'
  return map[ext] || '📄'
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

async function fetchWorktree() {
  loading.value = true
  try {
    const base = import.meta.env.VITE_API_BASE || '/api'
    const token = getAuthToken()
    const res = await fetch(`${base}/tasks/${props.taskId}/worktree`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!res.ok) { allFiles.value = []; return }
    const data = await res.json()
    allFiles.value = data.files || []
    docsStatus.value = data.docs || []
  } catch {
    allFiles.value = []
  } finally {
    loading.value = false
  }
}

async function selectFile(f: WFile) {
  selectedFile.value = f
  selectedDoc.value = ''
  if (!f.is_text) { previewContent.value = ''; return }
  fileLoading.value = true
  try {
    const base = import.meta.env.VITE_API_BASE || '/api'
    const token = getAuthToken()
    const res = await fetch(`${base}/tasks/${props.taskId}/worktree/${f.path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!res.ok) { previewContent.value = ''; return }
    const data = await res.json()
    previewContent.value = data.content || ''
  } catch {
    previewContent.value = ''
  } finally {
    fileLoading.value = false
    nextTick(() => {
      if (codeAreaRef.value) codeAreaRef.value.scrollTop = 0
    })
  }
}

async function selectDoc(d: DocItem) {
  if (!d.has_content) return
  selectedFile.value = null
  selectedDoc.value = d.name
  fileLoading.value = true
  try {
    const base = import.meta.env.VITE_API_BASE || '/api'
    const token = getAuthToken()
    const res = await fetch(`${base}/tasks/${props.taskId}/worktree/docs/${d.name}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!res.ok) { previewContent.value = ''; return }
    const data = await res.json()
    previewContent.value = data.content || ''
  } catch {
    previewContent.value = ''
  } finally {
    fileLoading.value = false
    nextTick(() => {
      if (codeAreaRef.value) codeAreaRef.value.scrollTop = 0
    })
  }
}

function handleTableRowClick(f: TableFile) {
  if (f.isDoc && f.docItem) {
    selectDoc(f.docItem)
  } else {
    selectFile(f as WFile)
  }
}

function clearSelection() {
  selectedFile.value = null
  selectedDoc.value = ''
  previewContent.value = ''
}

async function copyContent() {
  if (!previewContent.value) return
  try {
    await navigator.clipboard.writeText(previewContent.value)
    showCopyToast.value = true
    setTimeout(() => { showCopyToast.value = false }, 2000)
  } catch { /* silent */ }
}

function downloadFile() {
  if (!previewContent.value) return
  const blob = new Blob([previewContent.value], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = previewFileName.value || 'file.txt'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
}

function openContextMenu(_event: MouseEvent, _file: TableFile) {
  // Placeholder for future context menu
}

let resizing = false
let startX = 0
let startW = 0
function startResize(e: MouseEvent) {
  resizing = true
  startX = e.clientX
  startW = treePanelWidth.value
  document.addEventListener('mousemove', onResize)
  document.addEventListener('mouseup', stopResize)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}
function onResize(e: MouseEvent) {
  if (!resizing) return
  const delta = e.clientX - startX
  treePanelWidth.value = Math.max(140, Math.min(400, startW + delta))
}
function stopResize() {
  resizing = false
  document.removeEventListener('mousemove', onResize)
  document.removeEventListener('mouseup', stopResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

onMounted(() => fetchWorktree())
watch(() => props.taskId, () => {
  selectedFile.value = null
  selectedDoc.value = ''
  previewContent.value = ''
  fetchWorktree()
})
</script>

<style scoped>
/* ═══════════════════════════════════════════════════════════════════
   Coze-style File Browser — inspired by 扣子文件管理 UI
   Three-panel: tree | list table | code preview (dark)
   ═══════════════════════════════════════════════════════════════════ */

.coze-file-browser {
  --tree-bg: #f8f9fc;
  --list-bg: #ffffff;
  --preview-bg: #1b1d24;
  --preview-toolbar: #22252e;
  --border: #e8eaef;
  --border-dark: #2c2f38;
  --text-1: #1a1c23;
  --text-2: #4e5362;
  --text-3: #8b8fa5;
  --accent: #3370ff;
  --accent-soft: rgba(51, 112, 255, 0.08);
  --green: #34c759;
  --radius: 12px;

  height: 620px;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--list-bg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
  position: relative;
}

.coze-file-browser.fullscreen {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 9999;
  height: 100vh;
  border-radius: 0;
  border: none;
}

/* ─── Top Bar ─── */
.browser-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  height: 48px;
  border-bottom: 1px solid var(--border);
  background: var(--list-bg);
  flex-shrink: 0;
}

.topbar-tabs {
  display: flex;
  gap: 2px;
}

.topbar-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-3);
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}
.topbar-tab:hover { color: var(--text-1); }
.topbar-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.tab-count {
  font-size: 11px;
  min-width: 18px;
  height: 18px;
  line-height: 18px;
  text-align: center;
  border-radius: 9px;
  background: var(--accent-soft);
  color: var(--accent);
  padding: 0 5px;
}
.topbar-tab.active .tab-count {
  background: var(--accent);
  color: #fff;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.search-box {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #f5f6f8;
  transition: border-color 0.2s, background 0.2s;
}
.search-box:focus-within {
  border-color: var(--accent);
  background: #fff;
}

.search-icon { color: var(--text-3); flex-shrink: 0; }

.search-input {
  border: none;
  background: none;
  outline: none;
  font-size: 12px;
  color: var(--text-1);
  width: 140px;
}
.search-input::placeholder { color: #b8bccb; }

.storage-info {
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
}

/* ─── Body layout ─── */
.browser-body {
  display: flex;
  flex: 1;
  min-height: 0;
}

/* ─── Tree panel ─── */
.panel-tree {
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  background: var(--tree-bg);
  overflow-y: auto;
  overflow-x: hidden;
}

.tree-content {
  padding: 4px 0;
}

.file-group {
  border-bottom: 1px solid #eef0f4;
}
.file-group:last-child { border-bottom: none; }

.group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 12px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}
.group-header:hover { background: #eef1f6; }

.group-chevron {
  color: var(--text-3);
  transition: transform 0.2s;
  flex-shrink: 0;
}
.group-chevron.open { transform: rotate(90deg); }

.group-icon {
  flex-shrink: 0;
}
.folder-icon { color: #f59e0b; }
.doc-icon { color: var(--accent); }

.group-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-1);
  flex: 1;
}

.group-badge {
  font-size: 10px;
  min-width: 20px;
  height: 18px;
  line-height: 18px;
  text-align: center;
  border-radius: 9px;
  background: var(--accent);
  color: #fff;
  padding: 0 6px;
  font-weight: 500;
}
.docs-badge { background: #9ca3af; }

.group-body { padding-bottom: 4px; }

/* Tree row */
.tree-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px 5px 28px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-2);
  transition: background 0.12s;
  user-select: none;
}
.tree-row:hover { background: #eef1f6; }
.tree-row.selected {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 500;
}
.tree-row.dimmed { opacity: 0.45; cursor: default; }
.dir-row { font-weight: 500; }
.dir-children .tree-row { padding-left: 42px; }

.row-chevron {
  color: var(--text-3);
  transition: transform 0.2s;
  flex-shrink: 0;
}
.row-chevron.open { transform: rotate(90deg); }

.row-icon { font-size: 13px; flex-shrink: 0; }
.row-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, "Cascadia Code", monospace;
  font-size: 12px;
}
.row-count { font-size: 10px; color: var(--text-3); }
.row-pending {
  font-size: 10px;
  color: var(--text-3);
  background: #f0f1f3;
  padding: 1px 6px;
  border-radius: 4px;
}

/* ─── Resize handle ─── */
.resize-handle {
  width: 4px;
  cursor: col-resize;
  background: transparent;
  flex-shrink: 0;
  transition: background 0.15s;
}
.resize-handle:hover { background: var(--accent); opacity: 0.3; }

/* ─── File list table panel ─── */
.panel-list {
  flex: 1;
  min-width: 240px;
  overflow-y: auto;
  overflow-x: hidden;
  border-right: 1px solid var(--border);
  background: var(--list-bg);
}

.file-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}

.file-table thead { position: sticky; top: 0; z-index: 2; }

.file-table th {
  padding: 10px 12px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-3);
  text-align: left;
  background: #f8f9fc;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

.th-name { width: auto; }
.th-time { width: 100px; }
.th-size { width: 80px; }
.th-actions { width: 36px; }

.table-row {
  cursor: pointer;
  transition: background 0.12s;
}
.table-row:hover { background: #f5f7fa; }
.table-row.active { background: var(--accent-soft); }

.table-row td {
  padding: 9px 12px;
  font-size: 13px;
  color: var(--text-2);
  border-bottom: 1px solid #f0f1f4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.td-name {
  display: flex;
  align-items: center;
  gap: 8px;
}

.td-icon { font-size: 14px; flex-shrink: 0; }
.td-filename {
  font-weight: 500;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
}
.td-time { font-size: 12px; color: var(--text-3); }
.td-size { font-size: 12px; color: var(--text-3); }
.td-actions { text-align: center; }

.action-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  background: none;
  border-radius: 4px;
  cursor: pointer;
  color: var(--text-3);
  transition: all 0.15s;
}
.action-dot:hover { background: #eef1f6; color: var(--text-1); }

.table-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: var(--text-3);
  font-size: 13px;
}

/* ─── Preview panel ─── */
.panel-preview {
  flex: 1.2;
  min-width: 300px;
  display: flex;
  flex-direction: column;
  background: var(--preview-bg);
  overflow: hidden;
}
.panel-preview.no-file { flex: 0.8; }

.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: var(--preview-toolbar);
  border-bottom: 1px solid var(--border-dark);
  flex-shrink: 0;
}

.preview-title { display: flex; align-items: center; gap: 8px; }
.preview-filename {
  font-size: 13px;
  font-weight: 600;
  color: #e2e4e8;
  font-family: ui-monospace, SFMono-Regular, monospace;
}

.preview-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: none;
  background: none;
  border-radius: 6px;
  cursor: pointer;
  color: #8b8fa5;
  transition: all 0.15s;
}
.action-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #e2e4e8;
}
.close-btn:hover { color: #ef4444; }

.preview-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid var(--border-dark);
  flex-shrink: 0;
}

.meta-path {
  font-size: 11px;
  color: #6b7085;
  font-family: ui-monospace, monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.meta-lang, .meta-size {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.05);
  flex-shrink: 0;
}
.meta-lang { color: var(--green); }
.meta-size { color: #6b7085; }

/* Code area */
.preview-code-area {
  display: flex;
  flex: 1;
  overflow: auto;
  min-height: 0;
}

.line-gutter {
  display: flex;
  flex-direction: column;
  padding: 14px 0;
  background: rgba(255, 255, 255, 0.015);
  border-right: 1px solid var(--border-dark);
  user-select: none;
  flex-shrink: 0;
  min-width: 48px;
  text-align: right;
}

.gutter-num {
  font-size: 12px;
  line-height: 1.7;
  color: #3a3d47;
  padding: 0 12px 0 8px;
  font-family: ui-monospace, SFMono-Regular, monospace;
}

.code-body {
  flex: 1;
  margin: 0;
  padding: 14px 16px;
  font-size: 12px;
  line-height: 1.7;
  color: #d4d4d4;
  font-family: ui-monospace, SFMono-Regular, "Cascadia Code", monospace;
  white-space: pre;
  overflow-x: auto;
  background: transparent;
  tab-size: 4;
}

/* highlight.js token colors (VS Code Dark+ inspired) */
.code-body :deep(.hljs-keyword) { color: #c586c0; }
.code-body :deep(.hljs-string) { color: #ce9178; }
.code-body :deep(.hljs-number) { color: #b5cea8; }
.code-body :deep(.hljs-comment) { color: #6a9955; font-style: italic; }
.code-body :deep(.hljs-function) { color: #dcdcaa; }
.code-body :deep(.hljs-title) { color: #dcdcaa; }
.code-body :deep(.hljs-class .hljs-title) { color: #4ec9b0; }
.code-body :deep(.hljs-built_in) { color: #4ec9b0; }
.code-body :deep(.hljs-params) { color: #9cdcfe; }
.code-body :deep(.hljs-attr) { color: #9cdcfe; }
.code-body :deep(.hljs-attribute) { color: #9cdcfe; }
.code-body :deep(.hljs-literal) { color: #569cd6; }
.code-body :deep(.hljs-type) { color: #4ec9b0; }
.code-body :deep(.hljs-meta) { color: #569cd6; }
.code-body :deep(.hljs-selector-tag) { color: #d7ba7d; }
.code-body :deep(.hljs-selector-class) { color: #d7ba7d; }
.code-body :deep(.hljs-tag) { color: #569cd6; }
.code-body :deep(.hljs-name) { color: #569cd6; }
.code-body :deep(.hljs-variable) { color: #9cdcfe; }
.code-body :deep(.hljs-regexp) { color: #d16969; }
.code-body :deep(.hljs-symbol) { color: #b5cea8; }
.code-body :deep(.hljs-property) { color: #9cdcfe; }
.code-body :deep(.hljs-operator) { color: #d4d4d4; }
.code-body :deep(.hljs-punctuation) { color: #d4d4d4; }
.code-body :deep(.hljs-section) { color: #dcdcaa; }
.code-body :deep(.hljs-bullet) { color: #569cd6; }
.code-body :deep(.hljs-link) { color: #569cd6; text-decoration: underline; }
.code-body :deep(.hljs-emphasis) { font-style: italic; }
.code-body :deep(.hljs-strong) { font-weight: bold; }

/* Loading states */
.preview-loading {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: center;
  padding: 60px;
  color: #6b7085;
  font-size: 13px;
}

.preview-no-content {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  color: #4a4d57;
  font-size: 13px;
}

.preview-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  gap: 14px;
}
.hint-title { font-size: 14px; color: #6b7085; font-weight: 500; margin: 0; }
.hint-sub { font-size: 12px; color: #4a4d57; margin: 0; }

/* ─── Loading / Empty states ─── */
.browser-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 300px;
  color: var(--text-3);
  font-size: 13px;
}

.browser-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 80px 20px;
}
.empty-illustration { opacity: 0.4; }
.empty-title { font-size: 15px; font-weight: 600; color: var(--text-2); margin: 0; }
.empty-desc { font-size: 13px; color: var(--text-3); margin: 0; }

.loading-spinner {
  width: 28px;
  height: 28px;
  border: 3px solid #e8eaef;
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
.loading-spinner.small { width: 18px; height: 18px; border-width: 2px; }

@keyframes spin { to { transform: rotate(360deg); } }

/* ─── Toast ─── */
.copy-toast {
  position: absolute;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  padding: 8px 20px;
  background: #22c55e;
  color: #fff;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  box-shadow: 0 4px 16px rgba(34, 197, 94, 0.3);
  z-index: 100;
  animation: toast-in 0.3s ease;
}
@keyframes toast-in {
  from { opacity: 0; transform: translateX(-50%) translateY(10px); }
  to { opacity: 1; transform: translateX(-50%) translateY(0); }
}

/* ─── Scrollbar ─── */
.panel-tree::-webkit-scrollbar,
.panel-list::-webkit-scrollbar,
.preview-code-area::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.panel-tree::-webkit-scrollbar-track,
.panel-list::-webkit-scrollbar-track {
  background: transparent;
}
.panel-tree::-webkit-scrollbar-thumb,
.panel-list::-webkit-scrollbar-thumb {
  background: #d0d3d9;
  border-radius: 3px;
}
.preview-code-area::-webkit-scrollbar-track { background: transparent; }
.preview-code-area::-webkit-scrollbar-thumb {
  background: #3a3d47;
  border-radius: 3px;
}
</style>
