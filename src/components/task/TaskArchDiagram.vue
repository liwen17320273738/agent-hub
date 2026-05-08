<template>
  <div class="arch-diagram-view">
    <!-- Loading -->
    <div v-if="loading" class="arch-loading">
      <el-icon class="spin-icon" :size="20"><Loading /></el-icon>
      <span>加载架构图中...</span>
    </div>

    <!-- Diagram iframe (HTML with Mermaid.js) -->
    <div v-else-if="htmlPath" class="arch-diagram-frame-wrapper">
      <div class="frame-header">
        <span class="frame-icon">📐</span>
        <span>系统架构图</span>
        <div class="frame-actions">
          <a :href="htmlPath" target="_blank" class="open-link" title="在新窗口打开">
            <el-icon><FullScreen /></el-icon> 新窗口
          </a>
        </div>
      </div>
      <iframe
        :src="htmlPath"
        class="arch-diagram-frame"
        sandbox="allow-scripts allow-same-origin"
        loading="lazy"
      />
    </div>

    <!-- Mermaid code fallback -->
    <div v-else-if="mermaidCode" class="arch-fallback">
      <div class="fallback-header">
        <span class="frame-icon">📐</span>
        <span>架构图（Mermaid 源码）</span>
      </div>
      <pre class="mermaid-code">{{ mermaidCode }}</pre>
    </div>

    <!-- Empty state -->
    <div v-else class="arch-empty">
      <div class="empty-icon">📐</div>
      <p class="empty-title">暂无架构图</p>
      <p class="empty-desc">当前阶段还未生成架构图，Pipeline 执行 architecture 阶段后将自动生成</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Loading, FullScreen } from '@element-plus/icons-vue'
import { getAuthToken } from '@/services/api'

const props = defineProps<{
  taskId: string
}>()

const loading = ref(true)
const htmlPath = ref('')
const mermaidCode = ref('')

async function fetchArchDiagram() {
  loading.value = true
  try {
    const baseUrl = import.meta.env.VITE_API_BASE || '/api'
    const token = getAuthToken()
    const res = await fetch(
      `${baseUrl}/tasks/${props.taskId}/artifacts/architecture_diagram`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    )
    if (!res.ok) {
      loading.value = false
      return
    }
    const data = await res.json()
    if (data?.metadata?.filePath) {
      htmlPath.value = data.metadata.filePath
    } else if (data?.content) {
      mermaidCode.value = data.content
    }
  } catch {
    // silent
  } finally {
    loading.value = false
  }
}

onMounted(() => fetchArchDiagram())
</script>

<style scoped>
.arch-diagram-view {
  padding: 8px 0;
}

.arch-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: center;
  padding: 60px;
  color: var(--text-muted, #94a3b8);
}

.spin-icon {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.arch-diagram-frame-wrapper {
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  overflow: hidden;
  background: #0f0f1a;
}

.frame-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 20px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  font-size: 14px;
  font-weight: 500;
}

.frame-icon {
  font-size: 18px;
}

.frame-actions {
  margin-left: auto;
}

.open-link {
  color: #818cf8;
  text-decoration: none;
  font-size: 13px;
  font-weight: 400;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.open-link:hover {
  text-decoration: underline;
}

.arch-diagram-frame {
  width: 100%;
  height: 700px;
  border: none;
  display: block;
}

.arch-fallback {
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  overflow: hidden;
}

.fallback-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 20px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  font-size: 14px;
  font-weight: 500;
}

.mermaid-code {
  padding: 20px;
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: rgba(255,255,255,0.8);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 500px;
  overflow-y: auto;
  background: #1a1a2e;
}

.arch-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60px 20px;
  color: var(--text-muted, #94a3b8);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
  opacity: 0.5;
}

.empty-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 8px;
}

.empty-desc {
  font-size: 14px;
  color: var(--text-muted, #94a3b8);
  max-width: 400px;
  text-align: center;
}
</style>
