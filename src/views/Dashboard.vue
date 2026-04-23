<template>
  <div class="dashboard">
    <!-- ── Hero CTA ── -->
    <section class="hero">
      <div class="hero-content">
        <h1>AI 交付平台</h1>
        <p class="hero-subtitle">一句话告诉 AI 团队你要做什么</p>
        <div class="hero-input-row">
          <el-input
            v-model="taskInput"
            placeholder="例：做一份 OpenAI 与 Anthropic 的竞品分析报告"
            size="large"
            clearable
            @keyup.enter="submitTask(true)"
          />
        </div>
        <div class="hero-actions">
          <el-button type="primary" size="large" :loading="submitting" @click="submitTask(true)">
            先给方案
          </el-button>
          <el-button size="large" :loading="submitting" @click="submitTask(false)">
            直接执行
          </el-button>
          <el-button size="large" @click="$router.push('/inbox')">
            收件箱
            <el-tag v-if="pendingCount" type="danger" size="small" round class="hero-badge">{{ pendingCount }}</el-tag>
          </el-button>
        </div>
        <div class="hero-templates">
          <button
            v-for="tpl in templates"
            :key="tpl.text"
            class="tpl-chip"
            @click="taskInput = tpl.text"
          >
            <span class="tpl-icon">{{ tpl.icon }}</span>
            {{ tpl.label }}
          </button>
        </div>
      </div>
      <div class="hero-stats">
        <button
          v-for="s in statCards"
          :key="s.label"
          type="button"
          class="stat"
          @click="goInbox(s.tab)"
          :title="`查看${s.label}任务`"
        >
          <span class="stat-num" :style="{ color: s.color }">{{ s.value }}</span>
          <span class="stat-label">{{ s.label }}</span>
        </button>
      </div>
    </section>

    <!-- ── Config warning ── -->
    <el-alert v-if="!settingsStore.isConfigured()" type="warning" :closable="false" show-icon class="config-warn">
      <template #title>
        <template v-if="isEnterpriseBuild">
          服务端尚未配置模型网关，请联系管理员部署环境变量后重启。
        </template>
        <template v-else>
          尚未配置 API Key，前往
          <router-link to="/settings" class="link-accent">设置</router-link>
          配置。
        </template>
      </template>
    </el-alert>

    <!-- ── To-do: pending tasks ── -->
    <section v-if="pendingTasks.length" class="section">
      <h2 class="section-title">
        <el-icon><Bell /></el-icon>
        待办任务
        <el-tag type="warning" size="small" round>{{ pendingTasks.length }}</el-tag>
      </h2>
      <div class="task-cards">
        <div
          v-for="task in pendingTasks"
          :key="task.id"
          class="task-card pending"
          @click="$router.push(`/pipeline/task/${task.id}`)"
        >
          <div class="task-card-header">
            <span class="task-title">{{ task.title }}</span>
            <el-tag type="warning" size="small">{{ statusLabel(task.status) }}</el-tag>
          </div>
          <div class="task-card-meta">
            <span>{{ task.source || '-' }}</span>
            <span>{{ formatDate(task.created_at) }}</span>
          </div>
          <ArtifactCompletionBar v-if="task.stages?.length" :stages="task.stages" />
        </div>
      </div>
    </section>

    <!-- ── Recent tasks ── -->
    <section class="section">
      <h2 class="section-title">
        <el-icon><Clock /></el-icon>
        最近任务
      </h2>
      <div v-if="recentTasks.length" class="task-cards">
        <div
          v-for="task in recentTasks"
          :key="task.id"
          class="task-card"
          :class="task.status"
          @click="$router.push(`/pipeline/task/${task.id}`)"
        >
          <div class="task-card-header">
            <span class="task-title">{{ task.title }}</span>
            <el-tag :type="statusType(task.status)" size="small">{{ statusLabel(task.status) }}</el-tag>
          </div>
          <div class="task-card-meta">
            <span>{{ task.source || '-' }}</span>
            <span>{{ task.current_stage || '-' }}</span>
            <span>{{ formatDate(task.updated_at || task.created_at) }}</span>
          </div>
          <ArtifactCompletionBar v-if="task.stages?.length" :stages="task.stages" />
        </div>
      </div>
      <el-empty v-else description="暂无任务，点击上方「新建任务」开始" />
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSettingsStore } from '@/stores/settings'
import { isEnterpriseBuild } from '@/services/enterpriseApi'
import { fetchTasks, createTask as createPipelineTask, smartRunPipeline } from '@/services/pipelineApi'
import type { PipelineTask } from '@/agents/types'
import ArtifactCompletionBar from '@/components/task/ArtifactCompletionBar.vue'
import { ElMessage } from 'element-plus'

const router = useRouter()
const settingsStore = useSettingsStore()
const tasks = ref<PipelineTask[]>([])
const taskInput = ref('')
const submitting = ref(false)

const templates = [
  { icon: '📊', label: '竞品调研', text: '对比分析 OpenAI 与 Anthropic 的最新产品能力、定价和生态' },
  { icon: '📝', label: '周报生成', text: '根据本周 git commit 和完成的任务生成研发周报' },
  { icon: '🛠', label: 'PRD→代码', text: '实现一个用户注册登录模块，包含前端页面和后端 API' },
  { icon: '💬', label: '客服问答', text: '基于产品文档搭建一个智能客服问答系统' },
  { icon: '📈', label: '数据分析', text: '分析过去30天的用户行为数据，输出增长建议报告' },
]

onMounted(async () => {
  try { tasks.value = await fetchTasks() } catch { /* empty */ }
})

const pendingTasks = computed(() =>
  tasks.value.filter(t => t.status === 'plan_pending' || t.status === 'awaiting_final_acceptance')
)
const runningTasks = computed(() =>
  tasks.value.filter(t => t.status === 'active' || t.status === 'running')
)
const doneTasks = computed(() =>
  tasks.value.filter(t => t.status === 'done' || t.status === 'accepted')
)
const failedTasks = computed(() =>
  tasks.value.filter(t => t.status === 'failed' || t.status === 'rejected')
)
const recentTasks = computed(() =>
  [...tasks.value]
    .sort((a, b) => new Date(b.updated_at || b.created_at).getTime() - new Date(a.updated_at || a.created_at).getTime())
    .slice(0, 10)
)
const pendingCount = computed(() => pendingTasks.value.length)

// `tab` matches the Inbox view's tab names so clicking a card jumps you
// straight to the right list. Without this the card was a dead pixel —
// users would see "失败 3" and have no way to reach those 3 tasks.
const statCards = computed(() => [
  { tab: 'pending', label: '待审批', value: pendingTasks.value.length, color: '#e6a23c' },
  { tab: 'running', label: '执行中', value: runningTasks.value.length, color: '#409eff' },
  { tab: 'done',    label: '已完成', value: doneTasks.value.length,    color: '#67c23a' },
  { tab: 'failed',  label: '失败',   value: failedTasks.value.length,  color: '#f56c6c' },
])

function goInbox(tab: string) {
  router.push({ path: '/inbox', query: { tab } })
}

function statusType(s: string) {
  if (s === 'done' || s === 'accepted') return 'success'
  if (s === 'failed' || s === 'rejected') return 'danger'
  if (s === 'plan_pending' || s === 'awaiting_final_acceptance') return 'warning'
  return 'primary'
}

function statusLabel(s: string) {
  const map: Record<string, string> = {
    plan_pending: '待审批', awaiting_final_acceptance: '待验收',
    active: '执行中', running: '执行中',
    done: '已完成', accepted: '已验收',
    failed: '失败', rejected: '已拒绝',
  }
  return map[s] || s
}

function formatDate(iso: string) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function submitTask(planMode: boolean) {
  const text = taskInput.value.trim()
  if (!text) {
    ElMessage.warning('请输入你的需求')
    return
  }
  submitting.value = true
  try {
    const task = await createPipelineTask({
      title: text.slice(0, 80),
      description: text,
      source: 'web',
    })
    taskInput.value = ''

    if (planMode) {
      ElMessage.success('任务已创建，请在详情页查看方案')
      router.push(`/pipeline/task/${task.id}`)
    } else {
      try {
        await smartRunPipeline(task.id)
        ElMessage.success('任务已创建并开始执行')
      } catch {
        ElMessage.success('任务已创建，自动执行启动中…')
      }
      router.push(`/pipeline/task/${task.id}`)
    }
  } catch (e: any) {
    ElMessage.error(e.message || '提交失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.dashboard {
  padding: 32px 40px;
  max-width: 1100px;
  margin: 0 auto;
}

/* ── Hero ── */
.hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 32px;
  margin-bottom: 32px;
  padding: 28px 32px;
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08), rgba(59, 130, 246, 0.06));
  border: 1px solid rgba(99, 102, 241, 0.15);
}

.hero h1 {
  font-size: 28px;
  font-weight: 800;
  background: linear-gradient(135deg, #6366f1, #3b82f6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 6px;
}

.hero-subtitle {
  color: var(--el-text-color-secondary);
  font-size: 14px;
  margin-bottom: 14px;
}

.hero-input-row {
  margin-bottom: 14px;
  max-width: 520px;
}

.hero-templates {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.tpl-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 12px;
  border-radius: 16px;
  font-size: 12px;
  background: rgba(99, 102, 241, 0.08);
  border: 1px solid rgba(99, 102, 241, 0.18);
  color: var(--el-text-color-regular);
  cursor: pointer;
  transition: all 0.15s;
}

.tpl-chip:hover {
  background: rgba(99, 102, 241, 0.15);
  border-color: rgba(99, 102, 241, 0.3);
}

.tpl-icon {
  font-size: 14px;
}

.hero-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.hero-badge {
  margin-left: 6px;
}

.hero-stats {
  display: flex;
  gap: 20px;
  flex-shrink: 0;
}

.stat {
  text-align: center;
  min-width: 64px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
  cursor: pointer;
  font: inherit;
  transition: background 0.15s, transform 0.12s, border-color 0.15s;
}
.stat:hover {
  background: rgba(99, 102, 241, 0.08);
  transform: translateY(-1px);
}
.stat:focus-visible {
  outline: none;
  border-color: rgba(99, 102, 241, 0.5);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15);
}

.stat-num {
  display: block;
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
}

.stat-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* ── Config ── */
.config-warn {
  margin-bottom: 24px;
}

.link-accent {
  color: var(--el-color-primary);
  font-weight: 600;
}

/* ── Section ── */
.section {
  margin-bottom: 32px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 16px;
}

/* ── Task Cards ── */
.task-cards {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-card {
  padding: 16px 20px;
  border-radius: 12px;
  border: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color);
  cursor: pointer;
  transition: all 0.2s;
}

.task-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  transform: translateY(-1px);
}

.task-card.pending {
  border-left: 3px solid #e6a23c;
}

.task-card.failed, .task-card.rejected {
  border-left: 3px solid #f56c6c;
}

.task-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.task-title {
  font-weight: 600;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  margin-right: 12px;
}

.task-card-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

@media (max-width: 768px) {
  .hero {
    flex-direction: column;
  }
  .hero-stats {
    width: 100%;
    justify-content: space-around;
  }
}
</style>
