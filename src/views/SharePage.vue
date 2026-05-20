<template>
  <div class="share-page">
    <div v-if="loading" class="share-loading">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p>{{ t('sharePage.text_1') }}</p>
    </div>

    <div v-else-if="error" class="share-error">
      <el-result icon="warning" :title="error" sub-title="请检查分享链接是否正确或已过期">
        <template #extra>
          <el-button @click="$router.push('/login')">{{ t('sharePage.text_2') }}</el-button>
        </template>
      </el-result>
    </div>

    <template v-else-if="task">
      <header class="share-header">
        <div class="share-brand">Agent Hub · 任务分享</div>
        <h1>{{ task.title }}</h1>
        <p v-if="task.description" class="share-desc">{{ task.description }}</p>
        <div class="share-meta">
          <el-tag :type="statusType(task.status)" size="large">{{ statusLabel(task.status) }}</el-tag>
          <span v-if="task.created_at" class="meta-date">{{ formatDate(task.created_at) }}</span>
        </div>
      </header>

      <section class="share-stages">
        <div
          v-for="s in task.stages"
          :key="s.stage_id"
          class="stage-chip"
          :class="s.status"
        >
          <span class="stage-dot"></span>
          {{ s.label }}
        </div>
      </section>

      <section v-if="task" class="share-contract">
        <ArtifactContractPanel :share-token="token" compact />
      </section>

      <!-- Phase 5: visual preview — UI mockup + architecture diagram on share page -->
      <section v-if="task" class="share-visuals">
        <div class="visuals-grid">
          <div class="visual-card">
            <h3 class="visual-title">🎨 UI 设计稿</h3>
            <UiMockupCard :task-id="task.task_id" compact />
          </div>
          <div class="visual-card">
            <h3 class="visual-title">📐 架构图</h3>
            <TaskArchDiagram :task-id="task.task_id" compact />
          </div>
        </div>
      </section>

      <!-- Phase 6: QA evidence on share page -->
      <section v-if="task" class="share-qa">
        <TaskQATab :task-id="task.task_id" />
      </section>

      <!-- Phase 7: Deploy preview on share page -->
      <section v-if="task" class="share-deploy">
        <DeployPreviewCard :task-id="task.task_id" :share-token="token" />
      </section>

      <section class="share-docs">
        <div class="share-docs-header">
          <el-button type="primary" @click="downloadZip">
            <el-icon><Download /></el-icon> 下载完整交付包
          </el-button>
        </div>
        <DeliverableCards :task-id="task.task_id" :share-token="token" />
      </section>

      <section v-if="task.status === 'awaiting_final_acceptance'" class="share-acceptance">
        <h2>验收确认</h2>
        <p>请查看上方交付文档后做出决定：</p>
        <div class="acceptance-actions">
          <el-button type="success" size="large" :loading="accepting" @click="handleAccept">
            ✅ 我同意验收
          </el-button>
          <el-button type="danger" size="large" :loading="rejecting" @click="showRejectDialog = true">
            ↩ 打回重做
          </el-button>
        </div>
      </section>

      <section v-if="task.final_acceptance_status === 'accepted'" class="share-done">
        <el-result icon="success" title="已验收通过" sub-title="该任务已通过客户验收" />
      </section>
    </template>

    <el-dialog v-model="showRejectDialog" title="打回原因" width="460px">
      <el-input v-model="rejectReason" type="textarea" :rows="4" placeholder="请说明打回原因…" />
      <template #footer>
        <el-button @click="showRejectDialog = false">取消</el-button>
        <el-button type="danger" :loading="rejecting" @click="handleReject">确认打回</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { Loading, Download } from '@element-plus/icons-vue'
import DeliverableCards from '@/components/task/DeliverableCards.vue'
import ArtifactContractPanel from '@/components/task/ArtifactContractPanel.vue'
import UiMockupCard from '@/components/design/UiMockupCard.vue'
import TaskArchDiagram from '@/components/task/TaskArchDiagram.vue'
import TaskQATab from '@/components/task/TaskQATab.vue'
import DeployPreviewCard from '@/components/task/DeployPreviewCard.vue'
import { useI18n } from 'vue-i18n'
import { appLocaleToBcp47 } from '@/i18n'

const { t, locale } = useI18n()

const route = useRoute()
const token = computed(() => route.params.token as string)

const loading = ref(true)
const error = ref('')
const task = ref<any>(null)

const accepting = ref(false)
const rejecting = ref(false)
const showRejectDialog = ref(false)
const rejectReason = ref('')

function getBaseUrl(): string {
  return import.meta.env.VITE_API_BASE || '/api'
}

async function shareFetch(path: string, options?: Parameters<typeof fetch>[1]) {
  const res = await fetch(`${getBaseUrl()}${path}`, options)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

onMounted(async () => {
  try {
    task.value = await shareFetch(`/share/${token.value}`)
  } catch (e: any) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
})

async function handleAccept() {
  accepting.value = true
  try {
    await shareFetch(`/share/${token.value}/accept`, { method: 'POST' })
    task.value.status = 'done'
    task.value.final_acceptance_status = 'accepted'
  } catch (e: any) {
    error.value = e.message
  } finally {
    accepting.value = false
  }
}

async function handleReject() {
  rejecting.value = true
  try {
    await shareFetch(`/share/${token.value}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: rejectReason.value }),
    })
    task.value.status = 'paused'
    task.value.final_acceptance_status = 'rejected'
    showRejectDialog.value = false
  } catch (e: any) {
    error.value = e.message
  } finally {
    rejecting.value = false
  }
}

function statusType(s: string) {
  if (s === 'done' || s === 'accepted') return 'success'
  if (s === 'failed' || s === 'rejected') return 'danger'
  if (s === 'awaiting_final_acceptance' || s === 'plan_pending') return 'warning'
  return 'primary'
}

function statusLabel(s: string) {
  const m: Record<string, string> = {
    plan_pending: '待审批', awaiting_final_acceptance: '待验收',
    active: '执行中', running: '执行中', done: '已完成', accepted: '已验收',
    failed: '失败', rejected: '已拒绝', paused: '已暂停',
  }
  return m[s] || s
}

function downloadZip() {
  const baseUrl = getBaseUrl()
  window.open(`${baseUrl}/share/${token.value}/deliverables.zip`, '_blank')
}

function formatDate(iso: string) {
  if (!iso) return ''
  return new Date(iso).toLocaleString(appLocaleToBcp47(locale.value), {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<style scoped>
.share-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 40px 24px;
  min-height: 100vh;
  background: var(--el-bg-color-page, #f5f7fa);
}

.share-loading {
  text-align: center;
  padding: 100px 0;
  color: var(--el-text-color-secondary);
}

.share-error {
  padding: 60px 0;
}

.share-header {
  margin-bottom: 32px;
}

.share-brand {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 12px;
  letter-spacing: 1px;
  text-transform: uppercase;
}

.share-header h1 {
  font-size: 28px;
  font-weight: 800;
  margin-bottom: 8px;
  color: var(--el-text-color-primary);
}

.share-desc {
  color: var(--el-text-color-regular);
  line-height: 1.6;
  margin-bottom: 16px;
}

.share-meta {
  display: flex;
  align-items: center;
  gap: 16px;
}

.meta-date {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.share-stages {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 32px;
}

.stage-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 13px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
}

.stage-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--el-text-color-placeholder);
}

.stage-chip.done .stage-dot,
.stage-chip.completed .stage-dot { background: #67c23a; }
.stage-chip.active .stage-dot,
.stage-chip.running .stage-dot { background: #409eff; }
.stage-chip.failed .stage-dot { background: #f56c6c; }

.share-contract {
  margin-bottom: 28px;
}

.share-visuals {
  margin-bottom: 28px;
}

.visuals-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

@media (max-width: 768px) {
  .visuals-grid {
    grid-template-columns: 1fr;
  }
}

.visual-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  padding: 16px;
}

.visual-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.share-docs {
  margin-bottom: 40px;
}

.share-docs-header {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 16px;
}

.share-acceptance {
  padding: 32px;
  border-radius: 16px;
  background: var(--el-bg-color);
  border: 2px solid var(--el-border-color);
  text-align: center;
  margin-bottom: 40px;
}

.share-acceptance h2 {
  font-size: 20px;
  margin-bottom: 8px;
}

.acceptance-actions {
  display: flex;
  justify-content: center;
  gap: 24px;
  margin-top: 20px;
}

.share-done {
  margin-bottom: 40px;
}
</style>
