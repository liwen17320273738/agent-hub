<template>
  <div class="task-code-tab">
    <div v-if="loading" class="code-loading">
      <el-icon class="spin-icon" :size="20"><Loading /></el-icon>
      <span>加载中...</span>
    </div>

    <template v-else-if="hasCode">
      <div class="code-info-grid">
        <div class="info-card" v-if="codeData.storage_path">
          <span class="info-label">代码路径</span>
          <code class="info-value path">{{ codeData.storage_path }}</code>
        </div>
        <div class="info-card" v-if="codeMeta.branch">
          <span class="info-label">分支</span>
          <code class="info-value">{{ codeMeta.branch }}</code>
        </div>
        <div class="info-card" v-if="codeMeta.commit">
          <span class="info-label">最新 Commit</span>
          <code class="info-value mono">{{ codeMeta.commit.slice(0, 8) }}</code>
        </div>
        <div class="info-card" v-if="codeMeta.test_status">
          <span class="info-label">测试状态</span>
          <el-tag :type="codeMeta.test_status === 'pass' ? 'success' : 'danger'" size="small">
            {{ codeMeta.test_status === 'pass' ? '通过' : '失败' }}
          </el-tag>
        </div>
      </div>

      <div v-if="codeMeta.changed_files?.length" class="changed-files">
        <h4>变更文件 ({{ codeMeta.changed_files.length }})</h4>
        <div class="file-list">
          <div v-for="f in codeMeta.changed_files" :key="f" class="file-item">
            <el-icon :size="12"><Document /></el-icon>
            <code>{{ f }}</code>
          </div>
        </div>
      </div>

      <div v-if="codeMeta.recent_commits?.length" class="recent-commits">
        <h4>最近提交</h4>
        <div class="commit-list">
          <div v-for="c in codeMeta.recent_commits" :key="c.hash" class="commit-item">
            <code class="commit-hash">{{ c.hash?.slice(0, 7) }}</code>
            <span class="commit-msg">{{ c.message }}</span>
          </div>
        </div>
      </div>
    </template>

    <div v-else class="code-empty">
      <span class="empty-icon">📦</span>
      <p>代码工件尚未关联</p>
      <p class="empty-hint">开发阶段完成后，代码路径、分支、测试状态将自动显示在此处</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { Loading, Document } from '@element-plus/icons-vue'
import { getAuthToken } from '@/services/api'

const props = defineProps<{
  taskId: string
}>()

const loading = ref(false)
const codeData = ref<any>(null)
const hasCode = computed(() => !!codeData.value)
const codeMeta = computed(() => codeData.value?.metadata || {})

async function fetchCode() {
  loading.value = true
  try {
    const baseUrl = import.meta.env.VITE_API_BASE || '/api'
    const token = getAuthToken()
    const res = await fetch(
      `${baseUrl}/tasks/${props.taskId}/artifacts/code_link`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    )
    if (res.status === 404) {
      codeData.value = null
      return
    }
    if (!res.ok) throw new Error(`${res.status}`)
    codeData.value = await res.json()
  } catch {
    codeData.value = null
  } finally {
    loading.value = false
  }
}

onMounted(() => fetchCode())
watch(() => props.taskId, () => fetchCode())
</script>

<style scoped>
.task-code-tab { padding: 16px 0; }

.code-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: center;
  padding: 40px;
  color: var(--text-muted);
}

.code-info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}

.info-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px 14px;
}

.info-label {
  display: block;
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 6px;
  text-transform: uppercase;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.info-value {
  font-size: 13px;
  color: var(--text-primary);
  word-break: break-all;
}
.info-value.path { font-size: 12px; }
.info-value.mono { font-family: ui-monospace, monospace; }

.changed-files,
.recent-commits { margin-bottom: 16px; }

.changed-files h4,
.recent-commits h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 10px;
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 200px;
  overflow-y: auto;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 4px 8px;
  background: var(--bg-secondary);
  border-radius: 4px;
  color: var(--text-secondary);
}
.file-item code { font-size: 12px; font-family: ui-monospace, monospace; }

.commit-list { display: flex; flex-direction: column; gap: 6px; }

.commit-item {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 6px 10px;
  background: var(--bg-secondary);
  border-radius: 6px;
  font-size: 12px;
}

.commit-hash {
  font-family: ui-monospace, monospace;
  color: var(--accent);
  flex-shrink: 0;
}

.commit-msg {
  color: var(--text-secondary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.code-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 20px;
  color: var(--text-muted);
}
.empty-icon { font-size: 36px; margin-bottom: 12px; opacity: 0.5; }
.empty-hint { font-size: 12px; margin-top: 6px; }

.spin-icon { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
