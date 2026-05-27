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
            :placeholder="t('taskCodeTab.placeholder_1')"
            type="text"
          />
        </div>
        <span class="storage-info">{{ totalSizeStr }}</span>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="browser-loading">
      <div class="loading-spinner"></div>
      <span>{{ t('taskCodeTab.text_1') }}</span>
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
      <p class="empty-title">{{ t('taskCodeTab.text_2') }}</p>
      <p class="empty-desc">{{ t('taskCodeTab.text_3') }}</p>
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
              <span class="group-name">{{ t('taskCodeTab.text_4') }}</span>
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
                    <template v-for="child in node.children" :key="child.key">
                      <!-- 子目录 -->
                      <div v-if="child.type === 'dir'" class="tree-dir">
                        <div class="tree-row dir-row" @click="toggleDir(child.key)">
                          <svg class="row-chevron" :class="{ open: expandedDirs[child.key] }" width="10" height="10" viewBox="0 0 12 12">
                            <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                          </svg>
                          <span class="row-icon">📂</span>
                          <span class="row-name">{{ child.label }}</span>
                          <span class="row-count">{{ child.children?.length }}</span>
                        </div>
                        <div v-show="expandedDirs[child.key]" class="dir-children">
                          <div
                            v-for="sub in child.children"
                            :key="sub.key"
                            class="tree-row file-row"
                            :class="{ selected: selectedFile?.path === sub.file?.path }"
                            @click="sub.file && selectFile(sub.file)"
                          >
                            <span class="row-icon">{{ sub.file ? langIcon(sub.file.name) : '' }}</span>
                            <span class="row-name" :title="sub.file?.path">{{ sub.file?.name }}</span>
                          </div>
                        </div>
                      </div>
                      <!-- 文件 -->
                      <div
                        v-else
                        class="tree-row file-row"
                        :class="{ selected: selectedFile?.path === child.file?.path }"
                        @click="selectFile(child.file)"
                      >
                        <span class="row-icon">{{ langIcon(child.file?.name) }}</span>
                        <span class="row-name" :title="child.file?.path">{{ child.file?.name }}</span>
                      </div>
                    </template>
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
              <span class="group-name">{{ $t('taskCodeTab.deliveryDocs') }}</span>
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
                  <span v-if="!d.has_content" class="row-pending">{{ $t('taskCodeTab.pending') }}</span>
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
              <span class="group-name">{{ $t('taskCodeTab.configFiles') }}</span>
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

          <!-- Phase 4.5: Build summary group -->
          <div class="file-group">
            <div class="group-header" @click="buildExpanded = !buildExpanded">
              <svg class="group-chevron" :class="{ open: buildExpanded }" width="12" height="12" viewBox="0 0 12 12">
                <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
              </svg>
              <span class="row-icon" style="font-size:14px">🛠️</span>
              <span class="group-name">{{ t('taskCodeTab.manifestSection') }}</span>
              <span v-if="sourceManifestData" class="group-badge" :class="{ 'build-ok-badge': buildOk, 'build-fail-badge': !buildOk }">
                {{ buildOk ? t('taskCodeTab.buildPassed') : t('taskCodeTab.buildFailed') }}
              </span>
            </div>
            <div v-show="buildExpanded" class="group-body build-summary-body">
              <template v-if="sourceManifestData">
                <div class="build-summary-row">
                  <span class="build-label">{{ t('taskCodeTab.buildCommand') }}:</span>
                  <code class="build-value">{{ sourceManifestData.build_command || '—' }}</code>
                </div>
                <div class="build-summary-row">
                  <span class="build-label">{{ t('taskCodeTab.runCommand') }}:</span>
                  <code class="build-value">{{ sourceManifestData.run_command || '—' }}</code>
                </div>
                <div class="build-summary-row">
                  <span class="build-label">{{ t('taskCodeTab.testCommand') }}:</span>
                  <code class="build-value">{{ sourceManifestData.test_command || '—' }}</code>
                </div>
                <div class="build-summary-row">
                  <span class="build-label">{{ t('taskCodeTab.createdFiles') }}:</span>
                  <span class="build-value">{{ sourceManifestData.created_files?.length || 0 }}</span>
                </div>
                <div v-if="sourceManifestData.created_files?.length" class="build-file-list">
                  <div v-for="fp in sourceManifestData.created_files.slice(0, 30)" :key="fp" class="build-file-item">
                    <span class="build-file-icon">+</span>
                    <span class="build-file-path">{{ fp }}</span>
                  </div>
                  <div v-if="sourceManifestData.created_files.length > 30" class="build-file-item dimmed">
                    … {{ sourceManifestData.created_files.length - 30 }} more
                  </div>
                </div>
                <div class="build-status-row" :class="{ 'build-ok': buildOk, 'build-fail': !buildOk }">
                  {{ buildOk ? ('✅ ' + t('taskCodeTab.buildPassed')) : ('❌ ' + t('taskCodeTab.buildFailed')) }}
                </div>
              </template>
              <div v-else class="build-no-data">
                {{ t('taskCodeTab.noManifest') }}
              </div>

              <div v-if="buildLogContent" class="build-log-section">
                <div class="build-log-header" @click="buildLogExpanded = !buildLogExpanded">
                  <svg class="group-chevron" :class="{ open: buildLogExpanded }" width="12" height="12" viewBox="0 0 12 12">
                    <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                  </svg>
                  <span>{{ t('taskCodeTab.buildLog') }}</span>
                  <span v-if="!buildOk" class="build-log-error-icon">⚠️</span>
                </div>
                <div v-show="buildLogExpanded" class="build-log-body">
                  <pre :class="{ 'build-log-error': !buildOk }">{{ buildLogContent }}</pre>
                </div>
              </div>
              <div v-else class="build-no-data">
                {{ t('taskCodeTab.noBuildLog') }}
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
              <th class="th-name">{{ $t('taskCodeTab.fileName') }}</th>
              <th class="th-time">{{ $t('taskCodeTab.createTime') }}</th>
              <th class="th-size">{{ $t('taskCodeTab.fileSize') }}</th>
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
                <button class="action-dot" :title="t('taskCodeTab.moreActions')" @click.stop="openContextMenu($event, f)">
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                    <circle cx="8" cy="3" r="1.5"/><circle cx="8" cy="8" r="1.5"/><circle cx="8" cy="13" r="1.5"/>
                  </svg>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="!filteredTableFiles.length" class="table-empty">
          <span>{{ t('taskCodeTab.noMatchingFiles') }}</span>
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
              <button class="action-btn" :title="$t('taskCodeTab.copyCode')" @click="copyContent">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
                </svg>
              </button>
              <button class="action-btn" :title="$t('taskCodeTab.downloadFile')" @click="downloadFile">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
              </button>
              <button class="action-btn" :title="$t('taskCodeTab.fullscreen')" @click="toggleFullscreen">
                <svg v-if="!isFullscreen" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>
                </svg>
                <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/>
                </svg>
              </button>
              <button class="action-btn close-btn" :title="t('taskCodeTab.closePreview')" @click="clearSelection">
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
            <span>{{ t('taskCodeTab.loading') }}</span>
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
            <p>{{ t('taskCodeTab.noFileContent') }}</p>
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
          <p class="hint-title">{{ t('taskCodeTab.selectFileHint') }}</p>
          <p class="hint-sub">{{ t('taskCodeTab.selectFileSub') }}</p>
        </div>
      </div>
    </div>

    <!-- Copy toast -->
    <div v-if="showCopyToast" class="copy-toast">{{ t('taskCodeTab.copied') }}</div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted, watch, nextTick } from 'vue'
import { getAuthToken } from '@/services/api'
// Import only highlight.js core + common languages to reduce bundle from ~940KB to ~200KB
import hljs from 'highlight.js/lib/core'
import python from 'highlight.js/lib/languages/python'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import json from 'highlight.js/lib/languages/json'
import yaml from 'highlight.js/lib/languages/yaml'
import markdown from 'highlight.js/lib/languages/markdown'
import sql from 'highlight.js/lib/languages/sql'
import bash from 'highlight.js/lib/languages/bash'
import go from 'highlight.js/lib/languages/go'
import rust from 'highlight.js/lib/languages/rust'
import java from 'highlight.js/lib/languages/java'
import ini from 'highlight.js/lib/languages/ini'
import dockerfile from 'highlight.js/lib/languages/dockerfile'

// Register only the languages we actually use
hljs.registerLanguage('python', python)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('css', css)
hljs.registerLanguage('json', json)
hljs.registerLanguage('yaml', yaml)
hljs.registerLanguage('markdown', markdown)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('go', go)
hljs.registerLanguage('rust', rust)
hljs.registerLanguage('java', java)
hljs.registerLanguage('ini', ini)
hljs.registerLanguage('dockerfile', dockerfile)
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

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

interface SourceManifest {
  project_name?: string
  framework?: string
  build_command?: string
  run_command?: string
  test_command?: string
  created_files?: string[]
  build_success?: boolean
  [key: string]: unknown
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
const buildExpanded = ref(true)
const buildLogExpanded = ref(false)
const expandedDirs = reactive<Record<string, boolean>>({})
const treePanelWidth = ref(200)

// Phase 4.5: Build summary state
const sourceManifestData = ref<SourceManifest | null>(null)
const buildLogContent = ref<string>('')
const buildOk = computed(() => {
  if (!sourceManifestData.value) return false
  return sourceManifestData.value.build_success !== false
})

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
  { key: 'all' as const, label: t('taskCodeTab.allFiles'), count: allFiles.value.length },
  { key: 'src' as const, label: t('taskCodeTab.sourceCode'), count: srcFiles.value.length },
  { key: 'docs' as const, label: t('taskCodeTab.docs'), count: completedDocs.value },
])

const hasFiles = computed(() => allFiles.value.length > 0 || docsStatus.value.some(d => d.has_content))
const hasSelection = computed(() => !!selectedFile.value || !!selectedDoc.value)
const completedDocs = computed(() => docsStatus.value.filter(d => d.has_content).length)
const totalDocs = computed(() => docsStatus.value.length)
const totalSizeStr = computed(() => {
  const total = allFiles.value.reduce((s, f) => s + f.size, 0)
  return t('taskCodeTab.used', { size: fmtSize(total) })
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
    // Phase 4.5: Load source_manifest.json and build.log
    await fetchBuildArtifacts(base, token)
  } catch {
    allFiles.value = []
  } finally {
    loading.value = false
  }
}

async function fetchBuildArtifacts(base: string, token: string | null) {
  const headers = token ? { Authorization: `Bearer ${token}` } : {}
  try {
    const manifestRes = await fetch(`${base}/tasks/${props.taskId}/worktree/source_manifest.json`, {
      headers,
    })
    if (manifestRes.ok) {
      const manifestData = await manifestRes.json()
      const raw = manifestData.content || manifestData
      sourceManifestData.value = typeof raw === 'string' ? JSON.parse(raw) : raw
    }
  } catch {
    sourceManifestData.value = null
  }

  try {
    const logRes = await fetch(`${base}/tasks/${props.taskId}/worktree/build.log`, {
      headers,
    })
    if (logRes.ok) {
      const logData = await logRes.json()
      buildLogContent.value = logData.content || ''
    }
  } catch { /* silent */ }
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
  sourceManifestData.value = null
  buildLogContent.value = ''
  fetchWorktree()
})
</script>

<style scoped>
@import "./TaskCodeTab.css";
</style>
