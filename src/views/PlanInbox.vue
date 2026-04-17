<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  approvePlan,
  getPlan,
  listPlans,
  rejectPlan,
  revisePlan,
  type PlanDetail,
  type PlanSummary,
} from '@/services/planApi'

const router = useRouter()

const plans = ref<PlanSummary[]>([])
const loading = ref(false)
const focusedKey = ref<string>('')
const focusedDetail = ref<PlanDetail | null>(null)
const detailLoading = ref(false)

const acting = ref(false)
const reviseOpen = ref(false)
const reviseFeedback = ref('')

const focused = computed(() =>
  plans.value.find((p) => `${p.source}:${p.user_id}` === focusedKey.value),
)

async function refresh() {
  loading.value = true
  try {
    const r = await listPlans()
    plans.value = r.items
    if (focusedKey.value && !plans.value.find((p) => `${p.source}:${p.user_id}` === focusedKey.value)) {
      focusedKey.value = ''
      focusedDetail.value = null
    }
    if (!focusedKey.value && plans.value.length > 0) {
      const first = plans.value[0]
      await openDetail(first)
    }
  } catch (e) {
    ElMessage.error(`加载失败：${(e as Error).message}`)
  } finally {
    loading.value = false
  }
}

async function openDetail(p: PlanSummary) {
  focusedKey.value = `${p.source}:${p.user_id}`
  focusedDetail.value = null
  detailLoading.value = true
  try {
    focusedDetail.value = await getPlan(p.source, p.user_id)
  } catch (e) {
    ElMessage.error(`加载详情失败：${(e as Error).message}`)
  } finally {
    detailLoading.value = false
  }
}

async function approve(p: PlanSummary) {
  await ElMessageBox.confirm(
    `确认 approve "${p.title}"？将立即创建 pipeline 任务并启动 codegen → build → deploy。`,
    '确认',
    { type: 'warning', confirmButtonText: '开干', cancelButtonText: '取消' },
  )
  acting.value = true
  try {
    const r = await approvePlan(p.source, p.user_id)
    ElMessage.success('已启动')
    if (r.taskId) {
      ElMessageBox.confirm(`任务 ${r.taskId} 已启动，跳转到详情页？`, '已开干', {
        confirmButtonText: '去看看',
        cancelButtonText: '留在这',
      })
        .then(() => router.push(`/pipeline/${r.taskId}`))
        .catch(() => {
          /* stay */
        })
    }
    await refresh()
  } catch (e) {
    ElMessage.error(`approve 失败：${(e as Error).message}`)
  } finally {
    acting.value = false
  }
}

async function reject(p: PlanSummary) {
  await ElMessageBox.confirm(`确认拒绝 / 取消 "${p.title}"？`, '确认', {
    type: 'warning',
  })
  acting.value = true
  try {
    await rejectPlan(p.source, p.user_id)
    ElMessage.success('已取消')
    await refresh()
  } catch (e) {
    ElMessage.error(`取消失败：${(e as Error).message}`)
  } finally {
    acting.value = false
  }
}

function openRevise() {
  reviseFeedback.value = ''
  reviseOpen.value = true
}

async function submitRevise() {
  if (!focused.value || !reviseFeedback.value.trim()) {
    ElMessage.warning('请填写要怎么改')
    return
  }
  acting.value = true
  try {
    const r = await revisePlan(focused.value.source, focused.value.user_id, reviseFeedback.value.trim())
    ElMessage.success(`已重新生成（第 ${r.rotation_count} 次修改）`)
    reviseOpen.value = false
    if (focused.value) {
      await openDetail(focused.value)
    }
    await refresh()
  } catch (e) {
    ElMessage.error(`修改失败：${(e as Error).message}`)
  } finally {
    acting.value = false
  }
}

function fmtTime(epoch: number | null): string {
  if (!epoch) return ''
  const d = new Date(epoch * 1000)
  return d.toLocaleString('zh-CN', { hour12: false })
}

function elapsed(epoch: number | null): string {
  if (!epoch) return ''
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - epoch))
  if (sec < 60) return `${sec}秒前`
  if (sec < 3600) return `${Math.floor(sec / 60)}分钟前`
  return `${Math.floor(sec / 3600)}小时前`
}

let pollHandle: ReturnType<typeof setInterval> | null = null
function startPolling() {
  pollHandle = setInterval(refresh, 10000)
}
onMounted(async () => {
  await refresh()
  startPolling()
})
onBeforeUnmount(() => {
  if (pollHandle) clearInterval(pollHandle)
})
</script>

<template>
  <div class="plan-page">
    <div class="page-header">
      <div>
        <h1>计划审批收件箱</h1>
        <p class="page-subtitle">
          IM 投递的待确认计划都在这里。批准后立即创建 pipeline 任务，与用户回复"开干"等价。
        </p>
      </div>
      <div class="actions">
        <el-button :loading="loading" plain @click="refresh">刷新</el-button>
      </div>
    </div>

    <div v-if="!loading && !plans.length" class="empty">
      <p>当前没有待确认的计划。</p>
      <p class="empty-sub">从 IM (Slack/Lark) 发起新需求后，澄清完会落到这里。</p>
    </div>

    <div v-else class="layout">
      <aside class="sidebar">
        <div class="section-title">PENDING ({{ plans.length }})</div>
        <div
          v-for="p in plans"
          :key="`${p.source}:${p.user_id}`"
          class="inbox-row"
          :class="{ active: focusedKey === `${p.source}:${p.user_id}` }"
          @click="openDetail(p)"
        >
          <div class="row-title">{{ p.title || '(untitled)' }}</div>
          <div class="row-meta">
            <el-tag size="small" effect="plain">{{ p.source }}</el-tag>
            <el-tag size="small" effect="plain" type="info">{{ p.step_count }} 步</el-tag>
            <el-tag
              v-if="p.rotation_count > 0"
              size="small"
              effect="plain"
              type="warning"
            >
              已改 {{ p.rotation_count }}/{{ p.max_rotations }}
            </el-tag>
          </div>
          <div class="row-time">{{ elapsed(p.started_at) }}</div>
        </div>
      </aside>

      <section class="main">
        <div v-if="detailLoading" class="loading-pane">加载详情中…</div>
        <div v-else-if="focusedDetail" class="plan-detail">
          <div class="detail-header card">
            <div>
              <h2>{{ focusedDetail.title }}</h2>
              <div class="detail-meta">
                <el-tag size="small">{{ focusedDetail.source }}</el-tag>
                <el-tag size="small" type="info">用户：{{ focusedDetail.user_id }}</el-tag>
                <el-tag
                  v-if="focusedDetail.rotation_count > 0"
                  size="small"
                  type="warning"
                >
                  第 {{ focusedDetail.rotation_count }}/{{ focusedDetail.max_rotations }} 轮调整
                </el-tag>
                <span class="detail-time">提交于 {{ fmtTime(focusedDetail.started_at) }}</span>
              </div>
            </div>
            <div class="detail-actions">
              <el-button
                type="primary"
                size="large"
                :loading="acting"
                @click="focused && approve(focused)"
              >
                ▶ 开干
              </el-button>
              <el-button
                size="large"
                :loading="acting"
                :disabled="focusedDetail.rotation_count >= focusedDetail.max_rotations"
                @click="openRevise"
              >
                ✎ 修改
              </el-button>
              <el-button
                size="large"
                type="danger"
                plain
                :loading="acting"
                @click="focused && reject(focused)"
              >
                ✕ 取消
              </el-button>
            </div>
          </div>

          <div class="card">
            <div class="section-h">原始需求</div>
            <pre class="desc">{{ focusedDetail.description || '(无)' }}</pre>
          </div>

          <div class="card">
            <div class="section-h">
              执行计划
              <span class="meta-inline">
                · 共 {{ focusedDetail.plan.steps?.length || 0 }} 步
                <span v-if="focusedDetail.plan.estimate_min_total">
                  · 预估 {{ focusedDetail.plan.estimate_min_total }} 分钟
                </span>
                <span v-if="focusedDetail.plan.confidence">
                  · 信心 {{ focusedDetail.plan.confidence }}
                </span>
                <span v-if="focusedDetail.plan.deploy_target">
                  · 部署 {{ focusedDetail.plan.deploy_target }}
                </span>
              </span>
            </div>
            <p v-if="focusedDetail.plan.summary" class="plan-summary">
              {{ focusedDetail.plan.summary }}
            </p>
            <div class="step-list">
              <div
                v-for="step in focusedDetail.plan.steps || []"
                :key="step.no"
                class="step-card"
              >
                <div class="step-no">{{ step.no }}</div>
                <div class="step-body">
                  <div class="step-title">{{ step.title }}</div>
                  <div v-if="step.detail" class="step-detail">{{ step.detail }}</div>
                  <div class="step-meta">
                    <el-tag v-if="step.role" size="small" type="info" effect="plain">
                      {{ step.role }}
                    </el-tag>
                    <span v-if="step.estimate_min" class="step-est">
                      ⏱ {{ step.estimate_min }} 分钟
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-if="(focusedDetail.plan.risks || []).length" class="card risks">
            <div class="section-h">⚠ 风险</div>
            <ul>
              <li v-for="(r, i) in focusedDetail.plan.risks" :key="i">{{ r }}</li>
            </ul>
          </div>
        </div>
        <div v-else class="empty-main">
          <p>左侧选一个 plan 开始</p>
        </div>
      </section>
    </div>

    <el-dialog v-model="reviseOpen" title="修改计划" width="540px">
      <el-form>
        <el-form-item label="说说怎么改">
          <el-input
            v-model="reviseFeedback"
            type="textarea"
            :rows="4"
            placeholder="例：把 Vue 换成 React；先做后端，前端等等..."
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviseOpen = false">取消</el-button>
        <el-button type="primary" :loading="acting" @click="submitRevise">重新生成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.plan-page {
  max-width: 1400px;
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
.empty {
  text-align: center;
  padding: 80px 0;
  color: var(--text-secondary, #909399);
}
.empty-sub {
  font-size: 12px;
  margin-top: 6px;
}
.layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 18px;
}
.sidebar {
  background: var(--bg-secondary, #fafafa);
  border: 1px solid var(--border-color, #ebeef5);
  border-radius: 8px;
  padding: 14px;
  height: fit-content;
  position: sticky;
  top: 20px;
  max-height: calc(100vh - 80px);
  overflow: auto;
}
.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary, #909399);
  margin-bottom: 8px;
  text-transform: uppercase;
}
.inbox-row {
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 6px;
  border: 1px solid transparent;
  transition: background 0.15s;
}
.inbox-row:hover {
  background: var(--bg-tertiary, #f0f2f5);
}
.inbox-row.active {
  background: var(--primary-bg, #ecf5ff);
  border-color: var(--el-color-primary, #409eff);
}
.row-title {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.row-meta {
  display: flex;
  gap: 4px;
  margin-top: 6px;
  flex-wrap: wrap;
}
.row-time {
  font-size: 11px;
  color: var(--text-secondary, #909399);
  margin-top: 4px;
}
.main {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}
.loading-pane,
.empty-main {
  text-align: center;
  padding: 80px 0;
  color: var(--text-secondary, #909399);
}
.card {
  background: #fff;
  border: 1px solid var(--border-color, #ebeef5);
  border-radius: 10px;
  padding: 16px;
}
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}
.detail-header h2 {
  margin: 0;
  font-size: 18px;
}
.detail-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.detail-time {
  font-size: 12px;
  color: var(--text-secondary, #909399);
}
.detail-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.section-h {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #303133);
  margin-bottom: 8px;
}
.meta-inline {
  font-size: 12px;
  color: var(--text-secondary, #909399);
  font-weight: normal;
}
.desc {
  margin: 0;
  padding: 12px;
  background: var(--bg-secondary, #fafafa);
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  font-family: inherit;
  max-height: 240px;
  overflow: auto;
}
.plan-summary {
  margin: 0 0 14px 0;
  padding: 10px 12px;
  background: var(--primary-bg, #ecf5ff);
  border-left: 3px solid var(--el-color-primary, #409eff);
  font-size: 13px;
  border-radius: 4px;
}
.step-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.step-card {
  display: flex;
  gap: 12px;
  padding: 10px 12px;
  background: var(--bg-secondary, #fafafa);
  border-radius: 6px;
  border: 1px solid var(--border-color, #ebeef5);
}
.step-no {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--el-color-primary, #409eff);
  color: white;
  text-align: center;
  line-height: 28px;
  font-weight: 600;
  flex-shrink: 0;
  font-size: 13px;
}
.step-body {
  flex: 1;
  min-width: 0;
}
.step-title {
  font-weight: 600;
  font-size: 13px;
}
.step-detail {
  font-size: 12px;
  color: var(--text-secondary, #606266);
  margin-top: 4px;
  line-height: 1.5;
}
.step-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 6px;
}
.step-est {
  font-size: 11px;
  color: var(--text-secondary, #909399);
}
.risks ul {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: var(--el-color-warning, #e6a23c);
}
.risks li {
  margin-bottom: 4px;
}
.actions {
  display: flex;
  gap: 8px;
}
</style>
