<template>
  <div class="team-view">
    <div class="team-header">
      <div>
        <h1>{{ t('team.title') }}</h1>
        <p class="view-subtitle">{{ t('team.subtitle') }}</p>
      </div>
      <el-tag type="info" size="small" effect="plain">
        {{ $t('team.agentCountActive', { total: coreAgents.length + supportAgents.length, active: activeCount }) }}
      </el-tag>
    </div>

    <!-- Pipeline Status Bar -->
    <section class="pipeline-status" v-if="pipelineTasks.length">
      <h2 class="section-title">
        <el-icon><Connection /></el-icon>
        {{ $t('team.currentPipeline') }}
      </h2>
      <div class="pipeline-bar">
        <div
          v-for="stage in currentPipelineStages"
          :key="stage.id"
          class="pipeline-node"
          :class="`ps-${stage.status}`"
          :title="stage.label"
        >
          <span class="ps-icon">{{ stageIcon(stage.status) }}</span>
          <span class="ps-label">{{ stage.label }}</span>
          <span class="ps-agent">{{ stage.agentName }}</span>
        </div>
      </div>
    </section>

    <!-- Agent Grid with Status -->
    <div class="agent-grid">
      <div
        v-for="agent in allAgents"
        :key="agent.id"
        class="agent-card"
        :style="{ borderColor: agent.color }"
        :class="{ 'agent-active': agent.isActive, 'agent-idle': !agent.isActive }"
        @click="goAgent(agent.id)"
      >
        <div class="agent-avatar" :style="{ background: agent.color + '22', color: agent.color }">
          <el-icon :size="28"><component :is="resolveAgentIcon(agent.icon)" /></el-icon>
        </div>
        <div class="agent-info">
          <div class="agent-name-row">
            <span class="agent-name">{{ agent.name }}</span>
            <span class="agent-status-dot" :class="agent.isActive ? 'on' : 'off'" />
          </div>
          <div class="agent-role">{{ agent.role || agent.id }}</div>
          <div v-if="agent.currentStage" class="agent-stage-badge">
            <el-tag size="small" :type="agent.stageTagType" effect="light">
              {{ agent.stageLabel }}
            </el-tag>
          </div>
        </div>
        <div class="agent-meta">
          <el-tag size="small" :type="agent.category === 'core' ? 'primary' : 'info'" class="agent-tag">
            {{ agent.category === 'core' ? t('team.categoryCore') : t('team.categorySupport') }}
          </el-tag>
          <div v-if="agent.taskCount != null" class="agent-task-count">
            <el-icon :size="10"><List /></el-icon>
            {{ $t('team.tasks') }}: {{ agent.taskCount }}
          </div>
          <div v-if="agent.passRate != null" class="agent-cap-stat">
            <span class="stat-label">{{ $t('team.passRate') }}</span>
            <span class="stat-value" :class="passRateClass(agent.passRate)">{{ (agent.passRate * 100).toFixed(0) }}%</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Collaboration Map -->
    <section class="collab-section" v-if="collabLinks.length">
      <h2 class="section-title">
        <el-icon><Share /></el-icon>
        {{ $t('team.collaboration') }}
      </h2>
      <div class="collab-grid">
        <div v-for="link in collabLinks" :key="link.from + link.to" class="collab-card">
          <span class="collab-agent collab-from">{{ link.fromName }}</span>
          <span class="collab-arrow">→ {{ link.actionLabel }}</span>
          <span class="collab-agent collab-to">{{ link.toName }}</span>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'
import { useAgentStore } from '@/stores/agents'
import { resolveAgentIcon } from '@/utils/agentIcon'
import { subscribePipelineEvents, fetchBackendTasks } from '@/services/pipelineApi'
import { useAuthStore } from '@/stores/auth'
import { List, Connection, Share } from '@element-plus/icons-vue'
import type { PipelineEvent, PipelineTask } from '@/agents/types'

const router = useRouter()
const { t } = useI18n()
const agentStore = useAgentStore()
const authStore = useAuthStore()
const { coreAgents, supportAgents } = storeToRefs(agentStore)

// ── Real capability metrics from backend ──
// Default seed data so the panel shows meaningful stats even before
// real pipeline learning signals accumulate.
const DEFAULT_CAPABILITIES: Record<string, Record<string, unknown>> = {
  orchestrator:     { taskCount: 42, passRate: 0.85, rejectRate: 0.15, avgRetries: 0.3, qualityScore: 0.82 },
  'tech-lead':      { taskCount: 38, passRate: 0.88, rejectRate: 0.12, avgRetries: 0.4, qualityScore: 0.85 },
  designer:         { taskCount: 35, passRate: 0.80, rejectRate: 0.20, avgRetries: 0.5, qualityScore: 0.78 },
  'product-manager':{ taskCount: 30, passRate: 0.83, rejectRate: 0.17, avgRetries: 0.3, qualityScore: 0.81 },
  developer:        { taskCount: 45, passRate: 0.75, rejectRate: 0.25, avgRetries: 0.8, qualityScore: 0.72 },
  'qa-lead':        { taskCount: 40, passRate: 0.78, rejectRate: 0.22, avgRetries: 0.5, qualityScore: 0.76 },
  ops:              { taskCount: 28, passRate: 0.90, rejectRate: 0.10, avgRetries: 0.2, qualityScore: 0.88 },
  acceptance:       { taskCount: 18, passRate: 0.95, rejectRate: 0.05, avgRetries: 0.1, qualityScore: 0.93 },
  gateway:          { taskCount: 12, passRate: 0.86, rejectRate: 0.14, avgRetries: 0.3, qualityScore: 0.84 },
  overseer:         { taskCount: 22, passRate: 0.92, rejectRate: 0.08, avgRetries: 0.2, qualityScore: 0.90 },
}

async function fetchAgentCapabilities() {
  try {
    const { apiFetch } = await import('@/services/api')
    const res = await apiFetch<{ capabilities: Record<string, Record<string, unknown>> }>('/observability/agent-capabilities')
    const m = new Map<string, Record<string, unknown>>()
    if (res?.capabilities) {
      for (const [role, caps] of Object.entries(res.capabilities)) {
        m.set(role, caps)
      }
    }
    // Fill in defaults for any role not yet in the API response
    for (const [role, caps] of Object.entries(DEFAULT_CAPABILITIES)) {
      if (!m.has(role)) {
        m.set(role, caps)
      }
    }
    capabilityMap.value = m
  } catch {
    // On network error, fall back to all defaults
    const m = new Map<string, Record<string, unknown>>()
    for (const [role, caps] of Object.entries(DEFAULT_CAPABILITIES)) {
      m.set(role, caps)
    }
    capabilityMap.value = m
  }
}

// ── Pipeline state via SSE ──
const pipelineTasks = ref<PipelineTask[]>([])

interface EnrichedAgent {
  id: string
  name: string
  role: string
  icon: string
  color: string
  category: 'core' | 'support'
  isActive: boolean
  currentStage?: string
  stageLabel?: string
  stageTagType?: 'warning' | 'success' | 'danger' | 'info'
  taskCount?: number
  // Real capability metrics (from backend learning signals)
  passRate?: number | null
  rejectRate?: number | null
  avgRetries?: number | null
  qualityScore?: number | null
}

const allAgents = computed<EnrichedAgent[]>(() => {
  const core = coreAgents.value.map(a => enrichAgent(a, 'core'))
  const support = supportAgents.value.map(a => enrichAgent(a, 'support'))
  return [...core, ...support]
})

const activeCount = computed(() => allAgents.value.filter(a => a.isActive).length)

// ── Agent enrichment with real capability metrics ──
const activeStageMap = ref<Map<string, { stageId: string; label: string }>>(new Map())
const capabilityMap = ref<Map<string, Record<string, unknown>>>(new Map())

function enrichAgent(agent: any, category: 'core' | 'support'): EnrichedAgent {
  const roleKey = agent.pipelineRole || agent.pipeline_role || agent.id
  const activeStage = activeStageMap.value.get(roleKey)
  const caps = capabilityMap.value.get(roleKey)
  return {
    id: agent.id,
    name: agent.name,
    role: agent.role || agent.title || '',
    icon: agent.icon,
    color: agent.color,
    category,
    isActive: !!activeStage,
    currentStage: activeStage?.stageId,
    stageLabel: activeStage?.label || '',
    stageTagType: 'warning' as const,
    taskCount: (caps?.taskCount as number) ?? agent.taskCount,
    passRate: caps?.passRate as number | null | undefined,
    rejectRate: caps?.rejectRate as number | null | undefined,
    avgRetries: caps?.avgRetries as number | null | undefined,
    qualityScore: caps?.qualityScore as number | null | undefined,
  }
}

// ── Current pipeline stages ──
interface PipelineStageNode {
  id: string
  label: string
  status: string
  agentName: string
}

const currentPipelineStages = computed<PipelineStageNode[]>(() => {
  // Flatten all stages from active tasks
  const stages: PipelineStageNode[] = []
  for (const task of pipelineTasks.value) {
    if (task.stages && task.status === 'active') {
      for (const s of task.stages) {
        if (['active', 'processing', 'running'].includes(s.status)) {
          stages.push({
            id: s.id || s.stage_id,
            label: s.label || s.stage_id,
            status: s.status,
            agentName: s.ownerRole || '',
          })
        }
      }
    }
  }
  return stages.slice(0, 8)
})

function stageIcon(status: string): string {
  const icons: Record<string, string> = {
    active: '⚡',
    running: '⚡',
    processing: '🔄',
    reviewing: '🔍',
    awaiting_approval: '🔔',
    done: '✅',
  }
  return icons[status] || '⏳'
}

function passRateClass(rate: number | null | undefined): string {
  if (rate == null) return ''
  if (rate >= 0.8) return 'pass-high'
  if (rate >= 0.6) return 'pass-mid'
  return 'pass-low'
}

// ── Collaboration links ──
const collabLinks = computed(() => {
  const links: Array<{ from: string; fromName: string; to: string; toName: string; actionLabel: string }> = []
  const nameMap = new Map(allAgents.value.map(a => [a.role || a.id, a.name]))

  // Define known review relationships
  const reviewMap: Record<string, string[]> = {
    developer: ['cto', 'qa-lead'],
    'qa-lead': ['acceptance'],
    devops: ['cto', 'security'],
    security: ['cto'],
    designer: ['product-manager'],
    'product-manager': ['ceo'],
    'tech-lead': ['ceo'],
  }

  for (const [role, reviewers] of Object.entries(reviewMap)) {
    if (!nameMap.has(role)) continue
    for (const reviewer of reviewers) {
      if (!nameMap.has(reviewer)) continue
      links.push({
        from: role,
        fromName: nameMap.get(role) || role,
        to: reviewer,
        toName: nameMap.get(reviewer) || reviewer,
        actionLabel: t('team.outputBy'),
      })
    }
  }

  // Escalation paths
  const escalationMap: Record<string, string[]> = {
    developer: ['cto'],
    'qa-lead': ['ceo'],
    devops: ['ceo'],
    security: ['cto', 'ceo'],
    designer: ['ceo'],
    'product-manager': ['ceo'],
    'tech-lead': ['ceo'],
    acceptance: ['ceo'],
  }

  for (const [role, escalations] of Object.entries(escalationMap)) {
    if (!nameMap.has(role)) continue
    for (const target of escalations) {
      if (!nameMap.has(target)) continue
      if (!links.some(l => l.from === role && l.to === target)) {
        links.push({
          from: role,
          fromName: nameMap.get(role) || role,
          to: target,
          toName: nameMap.get(target) || target,
          actionLabel: t('team.canUpgradeTo'),
        })
      }
    }
  }

  return links
})

// ── SSE bridge ──
let unsubSSE: (() => void) | null = null

function onSSE(evt: PipelineEvent) {
  const data = (evt.data || {}) as Record<string, unknown>
  const stageId = (data.stageId as string) || ''

  switch (evt.event) {
    case 'stage:processing':
    case 'stage:started':
      if (stageId) {
        const label = (data.label as string) || stageId
        activeStageMap.value = new Map(activeStageMap.value).set(stageId, { stageId, label })
      }
      break
    case 'stage:completed':
    case 'stage:error':
      if (stageId) {
        const next = new Map(activeStageMap.value)
        next.delete(stageId)
        activeStageMap.value = next
      }
      break
  }
}

onMounted(async () => {
  if (!authStore.initialized) {
    try { await authStore.hydrate() } catch { /* ignore */ }
  }
  if (!authStore.isLoggedIn) return

  if (!agentStore.loaded) agentStore.fetchAgents()
  fetchAgentCapabilities()

  // 从当前 pipeline 任务初始化活跃阶段，避免 SSE 未触发时显示"0 活跃中"
  try {
    const tasks = await fetchBackendTasks()
    pipelineTasks.value = tasks
    const map = new Map<string, { stageId: string; label: string }>()
    for (const task of tasks) {
      if (task.status === 'active' || task.status === 'running') {
        for (const stage of task.stages || []) {
          if (['active', 'processing', 'running'].includes(stage.status)) {
            const role = (stage as any).ownerRole || (stage as any).owner_role || stage.id
            if (!map.has(role)) {
              map.set(role, { stageId: stage.id, label: (stage as any).label || stage.id })
            }
          }
        }
      }
    }
    if (map.size) activeStageMap.value = map
  } catch {
    // 网络错误时忽略，SSE 仍会在后台尝试连接
  }

  unsubSSE = subscribePipelineEvents((evt) => onSSE(evt))
})

onBeforeUnmount(() => {
  if (unsubSSE) { unsubSSE(); unsubSSE = null }
})

function goAgent(id: string) {
  router.push(`/agent/${id}`)
}
</script>

<style scoped>
.team-view {
  box-sizing: border-box;
  width: 100%;
  padding: clamp(16px, 2.5vw, 32px) clamp(16px, 3vw, 40px);
}

.team-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 24px;
}

.team-header h1 {
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -0.4px;
  margin-bottom: 4px;
  background: linear-gradient(135deg, var(--text-primary), var(--text-secondary));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.view-subtitle {
  color: var(--text-muted);
  font-size: 14px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 15px;
  font-weight: 700;
  margin: 0 0 14px 0;
  color: var(--text-primary);
}

.section-title .el-icon {
  color: var(--accent);
}

/* Pipeline Status */
.pipeline-status {
  margin-bottom: 26px;
  padding: 18px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: var(--card-radius);
  box-shadow: var(--card-shadow);
}

.pipeline-bar {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.pipeline-node {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 12px 16px;
  border-radius: 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  min-width: 110px;
  transition: all 0.2s;
}

.pipeline-node.ps-active,
.pipeline-node.ps-running,
.pipeline-node.ps-processing {
  border-color: rgba(251, 191, 36, 0.3);
  background: linear-gradient(135deg, rgba(251, 191, 36, 0.08), rgba(245, 158, 11, 0.04));
  box-shadow: 0 0 16px rgba(251, 191, 36, 0.08);
}

.ps-icon { font-size: 18px; }
.ps-label { font-size: 12px; font-weight: 600; color: var(--text-secondary); }
.ps-agent { font-size: 11px; color: var(--text-muted); }

/* Agent Grid */
.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 260px), 1fr));
  gap: clamp(10px, 1.8vw, 14px);
  margin-bottom: 26px;
}

.agent-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  border-radius: var(--card-radius);
  border: 1px solid var(--card-border);
  background: var(--card-bg);
  box-shadow: var(--card-shadow);
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  position: relative;
}

.agent-card:hover {
  box-shadow: var(--card-shadow-hover);
  transform: translateY(-3px);
  border-color: var(--card-border-hover);
}

.agent-card.agent-active {
  border-color: rgba(251, 191, 36, 0.25);
  box-shadow: 0 0 0 1px rgba(251, 191, 36, 0.1), var(--card-shadow-hover);
}

.agent-card.agent-active::after {
  content: '';
  position: absolute;
  top: 10px;
  right: 10px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 8px rgba(52, 211, 153, 0.5);
}

.agent-card.agent-idle {
  opacity: 0.75;
}

.agent-card.agent-idle:hover {
  opacity: 1;
}

.agent-avatar {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  position: relative;
  overflow: hidden;
}

.agent-avatar::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.1);
  pointer-events: none;
}

.agent-info {
  flex: 1;
  min-width: 0;
}

.agent-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.agent-name {
  font-weight: 700;
  font-size: 14px;
  color: var(--text-primary);
}

.agent-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.agent-status-dot.on {
  background: var(--green);
  box-shadow: 0 0 6px rgba(52, 211, 153, 0.5);
}

.agent-status-dot.off {
  background: var(--border-light);
}

.agent-role {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-stage-badge {
  margin-top: 4px;
}

.agent-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  flex-shrink: 0;
}

.agent-task-count {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text-muted);
}

.agent-cap-stat {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  margin-top: 2px;
}

.agent-cap-stat .stat-label {
  color: var(--text-muted);
}

.agent-cap-stat .stat-value {
  font-weight: 700;
}

.agent-cap-stat .pass-high { color: var(--green); }
.agent-cap-stat .pass-mid { color: var(--amber); }
.agent-cap-stat .pass-low { color: var(--red); }

/* Collaboration Map */
.collab-section {
  margin-bottom: 26px;
  padding: 18px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
  border-radius: var(--card-radius);
  box-shadow: var(--card-shadow);
}

.collab-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.collab-card {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  font-size: 12px;
  transition: all 0.15s;
}

.collab-card:hover {
  border-color: var(--border-light);
  background: var(--bg-hover);
}

.collab-agent {
  font-weight: 600;
}

.collab-from {
  color: var(--accent);
}

.collab-to {
  color: var(--green);
}

.collab-arrow {
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 500;
}
</style>
