<script setup lang="ts">
/**
 * Codebase Lab — UI for the semantic codebase index.
 *
 * Two-pane layout:
 *   ▸ Left: list of indexed projects (project_id) with quick stats and
 *           a "Reindex" / "Drop" action per row, plus a "+ 新建索引" button.
 *   ▸ Right: search box + ranked hits (file path + line range + score +
 *           preview snippet, click to expand to full chunk text).
 *
 * Project list is reconstructed from localStorage because the backend
 * doesn't yet expose a "list all projects" endpoint — keeps the UI
 * additive without a new API. Each successful reindex/search remembers
 * the project_id so the dropdown stays useful across sessions.
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Delete, Plus } from '@element-plus/icons-vue'
import {
  dropProject,
  getStats,
  reindexProject,
  searchCodebase,
  type CodebaseStats,
  type SearchHit,
} from '@/services/codebaseApi'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const STORAGE_KEY = 'agent-hub:codebase-projects'

interface ProjectEntry {
  project_id: string
  project_dir: string
  last_reindex_ms?: number
  chunks?: number
  files?: number
  embedding_model?: string
}

const projects = ref<ProjectEntry[]>([])
const selected = ref<string>('')
const stats = ref<CodebaseStats | null>(null)

const query = ref('')
const topK = ref(5)
const searching = ref(false)
const hits = ref<SearchHit[]>([])
const lastSearchInfo = ref<{ scanned?: number; elapsed?: number; reason?: string } | null>(null)
const expandedHit = ref<number | null>(null)

const reindexDialog = ref(false)
const reindexForm = ref<{ project_dir: string; project_id: string; max_files?: number; drop_first: boolean }>({
  project_dir: '',
  project_id: '',
  drop_first: false,
})
const reindexing = ref(false)

const selectedEntry = computed(() =>
  projects.value.find((p) => p.project_id === selected.value) || null,
)

function loadProjects() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) projects.value = parsed
  } catch {
    /* ignore */
  }
}

function persistProjects() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(projects.value))
  } catch {
    /* ignore */
  }
}

function rememberProject(entry: ProjectEntry) {
  const idx = projects.value.findIndex((p) => p.project_id === entry.project_id)
  if (idx >= 0) {
    projects.value[idx] = { ...projects.value[idx], ...entry }
  } else {
    projects.value.unshift(entry)
  }
  persistProjects()
}

async function selectProject(pid: string) {
  selected.value = pid
  hits.value = []
  expandedHit.value = null
  lastSearchInfo.value = null
  if (!pid) {
    stats.value = null
    return
  }
  try {
    const s = await getStats(pid)
    stats.value = s
    rememberProject({
      project_id: pid,
      project_dir: selectedEntry.value?.project_dir || pid,
      chunks: s.chunks,
      files: s.files,
      embedding_model: s.embedding_model,
    })
  } catch (e) {
    ElMessage.warning(`无法获取项目统计：${(e as Error).message}`)
  }
}

function openReindexDialog(prefill?: ProjectEntry) {
  reindexForm.value = {
    project_dir: prefill?.project_dir || '',
    project_id: prefill?.project_id || '',
    max_files: undefined,
    drop_first: false,
  }
  reindexDialog.value = true
}

async function doReindex() {
  if (!reindexForm.value.project_dir.trim()) {
    ElMessage.warning(t('codebaseLab.elMessage_1'))
    return
  }
  reindexing.value = true
  try {
    const res = await reindexProject({
      project_dir: reindexForm.value.project_dir.trim(),
      project_id: reindexForm.value.project_id.trim() || undefined,
      max_files: reindexForm.value.max_files || undefined,
      drop_first: reindexForm.value.drop_first,
    })
    ElMessage.success(
      `索引完成：扫描 ${res.files_scanned} 文件，新增 ${res.chunks_new} 个 chunk` +
        (res.tokens_used ? `，耗 ${res.tokens_used} tokens` : ''),
    )
    rememberProject({
      project_id: res.project_id,
      project_dir: reindexForm.value.project_dir.trim(),
      last_reindex_ms: res.elapsed_ms,
      embedding_model: res.embedding_model,
    })
    reindexDialog.value = false
    await selectProject(res.project_id)
  } catch (e) {
    ElMessage.error(`索引失败：${(e as Error).message}`)
  } finally {
    reindexing.value = false
  }
}

async function doSearch() {
  if (!selected.value) {
    ElMessage.warning(t('codebaseLab.elMessage_2'))
    return
  }
  if (!query.value.trim()) return
  searching.value = true
  expandedHit.value = null
  try {
    const res = await searchCodebase({
      project_id: selected.value,
      query: query.value.trim(),
      top_k: topK.value,
    })
    hits.value = res.hits
    lastSearchInfo.value = {
      scanned: res.scanned_chunks,
      elapsed: res.elapsed_ms,
      reason: res.reason,
    }
    if (res.hits.length === 0) {
      ElMessage.info(res.reason || '未找到匹配结果')
    }
  } catch (e) {
    ElMessage.error(`搜索失败：${(e as Error).message}`)
  } finally {
    searching.value = false
  }
}

async function doDrop(entry: ProjectEntry) {
  try {
    await ElMessageBox.confirm(
      `确认删除项目 "${entry.project_id}" 的全部索引？此操作无法撤销。`,
      '危险操作',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const r = await dropProject(entry.project_id)
    ElMessage.success(`已删除 ${r.deleted} 个 chunk`)
    projects.value = projects.value.filter((p) => p.project_id !== entry.project_id)
    persistProjects()
    if (selected.value === entry.project_id) {
      selected.value = ''
      stats.value = null
      hits.value = []
    }
  } catch (e) {
    ElMessage.error(`删除失败：${(e as Error).message}`)
  }
}

function scoreColor(score: number): string {
  if (score >= 0.8) return '#67c23a'
  if (score >= 0.6) return '#409eff'
  if (score >= 0.4) return '#e6a23c'
  return '#909399'
}

onMounted(() => {
  loadProjects()
  if (projects.value.length > 0) {
    selectProject(projects.value[0].project_id)
  }
})
</script>

<template>
  <div class="codebase-lab">
    <aside class="sidebar">
      <header class="sidebar-header">
        <h2>{{ t('codebaseLab.text_1') }}</h2>
        <el-button :icon="Plus" type="primary" size="small" @click="openReindexDialog()">
          新建索引
        </el-button>
      </header>

      <ul class="project-list" v-if="projects.length > 0">
        <li
          v-for="p in projects"
          :key="p.project_id"
          :class="{ active: p.project_id === selected }"
          @click="selectProject(p.project_id)"
        >
          <div class="project-id">{{ p.project_id }}</div>
          <div class="project-meta">
            <span v-if="p.chunks !== undefined">{{ p.chunks }} chunks · {{ p.files }} files</span>
            <span v-else class="muted">{{ t('codebaseLab.text_2') }}</span>
          </div>
          <div class="row-actions">
            <el-button
              :icon="Refresh"
              size="small"
              link
              type="primary"
              @click.stop="openReindexDialog(p)"
            >
              重建
            </el-button>
            <el-button :icon="Delete" size="small" link type="danger" @click.stop="doDrop(p)">
              删除
            </el-button>
          </div>
        </li>
      </ul>
      <el-empty v-else :description="t('codebaseLab.description_1')" :image-size="80" />
    </aside>

    <main class="main">
      <div class="search-bar" v-if="selected">
        <el-input
          v-model="query"
          :placeholder="t('codebaseLab.placeholder_1')"
          size="large"
          clearable
          @keydown.enter="doSearch"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-input-number v-model="topK" :min="1" :max="20" controls-position="right" size="large" />
        <el-button type="primary" size="large" :loading="searching" @click="doSearch">
          搜索
        </el-button>
      </div>

      <div v-if="selected && stats" class="stats-bar">
        <el-tag>{{ stats.chunks }} chunks</el-tag>
        <el-tag type="info">{{ stats.files }} files</el-tag>
        <el-tag v-if="stats.embedding_model" type="success">
          {{ stats.embedding_model }} · {{ stats.embedding_dim }} dim
        </el-tag>
        <span class="muted" v-if="lastSearchInfo">
          扫描 {{ lastSearchInfo.scanned }} chunks · {{ lastSearchInfo.elapsed }}ms
        </span>
      </div>

      <div v-if="!selected" class="empty-state">
        <el-empty description="选择左侧项目，或点击 “新建索引” 开始" />
      </div>

      <div v-else-if="hits.length === 0 && !searching" class="empty-state">
        <el-empty :description="lastSearchInfo?.reason || '输入查询语句开始搜索'" />
      </div>

      <ul v-else class="hits">
        <li
          v-for="(hit, idx) in hits"
          :key="`${hit.rel_path}-${hit.start_line}`"
          class="hit"
          :class="{ expanded: expandedHit === idx }"
        >
          <header @click="expandedHit = expandedHit === idx ? null : idx">
            <span class="rank">#{{ idx + 1 }}</span>
            <code class="path">{{ hit.rel_path }}:{{ hit.start_line }}-{{ hit.end_line }}</code>
            <el-tag size="small" :style="{ backgroundColor: scoreColor(hit.score), color: '#fff', borderColor: 'transparent' }">
              {{ hit.score.toFixed(3) }}
            </el-tag>
            <el-tag v-if="hit.language" size="small" type="info">{{ hit.language }}</el-tag>
            <span v-if="hit.symbols.length > 0" class="symbols">
              <el-tag v-for="s in hit.symbols.slice(0, 3)" :key="s" size="small" effect="plain">
                {{ s }}
              </el-tag>
            </span>
          </header>
          <pre class="preview"><code>{{ expandedHit === idx ? hit.preview : hit.preview.slice(0, 240) + (hit.preview.length > 240 ? '…' : '') }}</code></pre>
        </li>
      </ul>
    </main>

    <el-dialog v-model="reindexDialog" title="新建 / 重建代码索引" width="540px">
      <el-form label-width="110px">
        <el-form-item label="项目目录" required>
          <el-input
            v-model="reindexForm.project_dir"
            placeholder="绝对路径，例如 /Users/you/repos/foo"
          />
        </el-form-item>
        <el-form-item label="project_id">
          <el-input
            v-model="reindexForm.project_id"
            placeholder="留空时默认使用 project_dir"
          />
        </el-form-item>
        <el-form-item label="最多文件数">
          <el-input-number v-model="reindexForm.max_files" :min="0" controls-position="right" />
          <div class="hint">留空使用配置默认</div>
        </el-form-item>
        <el-form-item label="先清空旧索引">
          <el-switch v-model="reindexForm.drop_first" />
          <div class="hint">勾选后会先 DELETE 该 project_id 的全部 chunks</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reindexDialog = false">取消</el-button>
        <el-button type="primary" :loading="reindexing" @click="doReindex">开始索引</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.codebase-lab {
  display: grid;
  grid-template-columns: 320px 1fr;
  height: 100%;
  min-height: calc(100vh - 64px);
  background: var(--el-bg-color-page);
}

.sidebar {
  border-right: 1px solid var(--el-border-color-light);
  padding: 16px;
  background: var(--el-bg-color);
  overflow-y: auto;
}
.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.sidebar-header h2 {
  margin: 0;
  font-size: 18px;
}

.project-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.project-list li {
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 4px;
  border: 1px solid transparent;
}
.project-list li:hover {
  background: var(--el-fill-color-light);
}
.project-list li.active {
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-5);
}
.project-id {
  font-family: monospace;
  font-size: 13px;
  word-break: break-all;
  margin-bottom: 4px;
}
.project-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.row-actions {
  margin-top: 6px;
  display: flex;
  gap: 8px;
}

.main {
  padding: 24px;
  overflow-y: auto;
}
.search-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}
.stats-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  align-items: center;
  flex-wrap: wrap;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.empty-state {
  padding: 80px 0;
}

.hits {
  list-style: none;
  padding: 0;
  margin: 0;
}
.hit {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
}
.hit header {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  flex-wrap: wrap;
}
.rank {
  font-weight: 600;
  color: var(--el-text-color-secondary);
}
.path {
  font-family: monospace;
  font-size: 13px;
  flex: 1;
}
.symbols {
  display: flex;
  gap: 4px;
}
.preview {
  margin: 10px 0 0 0;
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  overflow-x: auto;
  font-size: 12px;
  line-height: 1.5;
  max-height: 80px;
  transition: max-height 0.2s;
}
.hit.expanded .preview {
  max-height: 600px;
}
.preview code {
  white-space: pre;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}
</style>
