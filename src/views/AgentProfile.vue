<template>
  <div v-if="!agent" class="profile-page empty">
    <p>{{ t('agentProfile.text_1') }}</p>
  </div>
  <div v-else class="profile-page">
    <!-- Hero -->
    <header class="profile-hero">
      <div class="hero-icon" :style="{ background: agent.color + '18', color: agent.color }">
        <el-icon :size="48"><component :is="resolveAgentIcon(agent.icon)" /></el-icon>
      </div>
      <div class="hero-info">
        <div class="hero-top">
          <h1>{{ agent.name }}</h1>
          <el-tag effect="plain" size="large">{{ agent.title }}</el-tag>
        </div>
        <p class="hero-seniority">{{ caps.seniority }}</p>
        <p class="hero-desc">{{ agent.description }}</p>
        <div class="hero-tags">
          <el-tag
            v-for="tag in domainTags"
            :key="tag"
            :color="agent.color + '20'"
            :style="{ color: agent.color, borderColor: agent.color + '40' }"
            effect="plain"
            size="small"
          >{{ tag }}</el-tag>
        </div>
        <div class="hero-stats">
          <div class="stat-item">
            <span class="stat-num">{{ agent.tools.length }}</span>
            <span class="stat-label">{{ t('agentProfile.text_2') }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-num">{{ agent.skills.length }}</span>
            <span class="stat-label">{{ t('agentProfile.text_3') }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-num">{{ deliverables.length }}</span>
            <span class="stat-label">{{ t('agentProfile.text_4') }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-num">{{ standardsCount }}</span>
            <span class="stat-label">{{ t('agentProfile.text_5') }}</span>
          </div>
        </div>
      </div>
      <div class="hero-actions">
        <el-button type="primary" @click="$router.push(`/agent/${agent.id}`)">
          <el-icon><ChatDotRound /></el-icon> 开始对话
        </el-button>
        <el-button @click="goBackFromProfile">
          <el-icon><Back /></el-icon> {{ t('agentProfile.back') }}
        </el-button>
      </div>
    </header>

    <div class="profile-body">
      <!-- Left Column: Radar + Collaboration -->
      <div class="profile-col-left">
        <!-- Radar Chart -->
        <section class="profile-card">
          <h2><el-icon><DataAnalysis /></el-icon>{{ t('agentProfile.text_6') }}</h2>
          <div class="radar-container">
            <svg viewBox="0 0 300 300" class="radar-svg">
              <!-- Grid -->
              <polygon v-for="level in [1, 0.75, 0.5, 0.25]" :key="level"
                :points="radarGridPoints(level)" class="radar-grid" />
              <!-- Axes -->
              <line v-for="(_, i) in radarLabels" :key="'ax'+i"
                x1="150" y1="150"
                :x2="radarPoint(i, 1).x" :y2="radarPoint(i, 1).y"
                class="radar-axis" />
              <!-- Data polygon -->
              <polygon :points="radarDataPoints" class="radar-data"
                :style="{ fill: agent.color + '30', stroke: agent.color }" />
              <!-- Data dots -->
              <circle v-for="(label, i) in radarLabels" :key="'dot'+i"
                :cx="radarPoint(i, radarValues[i] / 100).x"
                :cy="radarPoint(i, radarValues[i] / 100).y"
                r="4" :fill="agent.color" />
              <!-- Labels -->
              <text v-for="(label, i) in radarLabels" :key="'lb'+i"
                :x="radarLabelPos(i).x" :y="radarLabelPos(i).y"
                class="radar-label" text-anchor="middle" dominant-baseline="central">
                {{ label }} {{ radarValues[i] }}
              </text>
            </svg>
          </div>
        </section>

        <!-- Collaboration -->
        <section class="profile-card" v-if="collaboration">
          <h2><el-icon><Connection /></el-icon>{{ t('agentProfile.text_7') }}</h2>
          <div class="collab-section" v-if="collaboration.reviews_output_of?.length">
            <h4>{{ t('agentProfile.text_8') }}</h4>
            <div class="collab-agents">
              <el-tag v-for="aid in collaboration.reviews_output_of" :key="aid"
                effect="dark" type="success" size="small">
                {{ agentName(aid) }}
              </el-tag>
            </div>
          </div>
          <div class="collab-section" v-if="collaboration.output_reviewed_by?.length">
            <h4>{{ t('agentProfile.text_9') }}</h4>
            <div class="collab-agents">
              <el-tag v-for="aid in collaboration.output_reviewed_by" :key="aid"
                effect="dark" type="warning" size="small">
                {{ agentName(aid) }}
              </el-tag>
            </div>
          </div>
          <div class="collab-section" v-if="collaboration.can_escalate_to?.length">
            <h4>{{ t('agentProfile.text_10') }}</h4>
            <div class="collab-agents">
              <el-tag v-for="aid in collaboration.can_escalate_to" :key="aid"
                effect="dark" type="danger" size="small">
                {{ agentName(aid) }}
              </el-tag>
            </div>
          </div>
          <div v-if="!collaboration.reviews_output_of?.length && !collaboration.output_reviewed_by?.length && !collaboration.can_escalate_to?.length"
            class="empty-hint">{{ t('agentProfile.text_11') }}</div>
        </section>
      </div>

      <!-- Right Column: Tools + Skills + Deliverables + Standards -->
      <div class="profile-col-right">
        <!-- Tools -->
        <section class="profile-card">
          <h2><el-icon><SetUp /></el-icon> 可用工具 ({{ agent.tools.length }})</h2>
          <div class="tool-grid" v-if="agent.tools.length">
            <div v-for="tool in agent.tools" :key="tool.name" class="tool-item">
              <div class="tool-name">
                <el-icon :size="14" :style="{ color: agent.color }"><Operation /></el-icon>
                {{ tool.name }}
              </div>
              <p class="tool-desc">{{ tool.description }}</p>
            </div>
          </div>
          <div v-else class="empty-hint">{{ t('agentProfile.text_12') }}</div>
        </section>

        <!-- Skills -->
        <section class="profile-card">
          <h2><el-icon><MagicStick /></el-icon> 绑定技能 ({{ agent.skills.length }})</h2>
          <div class="skill-list" v-if="agent.skills.length">
            <div v-for="skill in agent.skills" :key="skill.skill_id" class="skill-item">
              <div class="skill-header">
                <span class="skill-name">{{ skill.skill_id }}</span>
                <el-tag :type="skill.enabled ? 'success' : 'info'" size="small" effect="plain">
                  {{ skill.enabled ? '已启用' : '未启用' }}
                </el-tag>
              </div>
            </div>
          </div>
          <div v-else class="empty-hint">{{ t('agentProfile.text_13') }}</div>
        </section>

        <!-- Deliverables -->
        <section class="profile-card" v-if="deliverables.length">
          <h2><el-icon><Document /></el-icon>{{ t('agentProfile.text_14') }}</h2>
          <div class="deliverables-list">
            <div v-for="(d, i) in deliverables" :key="i" class="deliverable-item">
              <el-icon :size="14" :style="{ color: agent.color }"><CircleCheck /></el-icon>
              <span>{{ d }}</span>
            </div>
          </div>
        </section>

        <!-- Boundary -->
        <section class="profile-card" v-if="boundary">
          <h2><el-icon><Guide /></el-icon>{{ t('agentProfile.text_15') }}</h2>
          <div class="boundary-section" v-if="boundary.handles?.length">
            <h4>{{ t('agentProfile.text_16') }}</h4>
            <div class="boundary-tags">
              <el-tag v-for="h in boundary.handles" :key="h" type="success" size="small" effect="plain">
                {{ h }}
              </el-tag>
            </div>
          </div>
          <div class="boundary-section" v-if="boundary.delegates_to && Object.keys(boundary.delegates_to).length">
            <h4>{{ t('agentProfile.text_17') }}</h4>
            <div class="delegate-list">
              <div v-for="(desc, key) in boundary.delegates_to" :key="key" class="delegate-item">
                <el-tag size="small" type="info" effect="plain">{{ key }}</el-tag>
                <span class="delegate-desc">{{ desc }}</span>
              </div>
            </div>
          </div>
        </section>

        <!-- Standards -->
        <section class="profile-card" v-if="standards.length">
          <h2><el-icon><Aim /></el-icon>{{ t('agentProfile.text_18') }}</h2>
          <ol class="standards-list">
            <li v-for="(s, i) in standards" :key="i">{{ s }}</li>
          </ol>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAgentStore } from '@/stores/agents'
import type { AgentProfile as AgentProfileType } from '@/stores/agents'
import { resolveAgentIcon } from '@/utils/agentIcon'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()

function goBackFromProfile() {
  let from = typeof route.query.from === 'string' ? route.query.from.trim() : ''
  try {
    from = decodeURIComponent(from)
  } catch {
    /* use raw */
  }
  if (from.startsWith('/') && !from.startsWith('//') && !from.includes('://')) {
    router.push(from)
    return
  }
  if (typeof window !== 'undefined' && window.history.length > 1) {
    router.back()
    return
  }
  router.push({ name: 'team' })
}

onMounted(() => {
  if (!agentStore.loaded) agentStore.fetchAgents()
})

const agent = computed<AgentProfileType | undefined>(
  () => agentStore.getAgent(route.params.id as string)
)
const caps = computed(() => agent.value?.capabilities || {})
const domainTags = computed(() => (caps.value.domain as string[]) || [])
const deliverables = computed(() => (caps.value.deliverables as string[]) || [])
const standards = computed(() => (caps.value.standards as string[]) || [])
const standardsCount = computed(() => standards.value.length)
const boundary = computed(() => caps.value.boundary as Record<string, unknown> | undefined)
const collaboration = computed(() => caps.value.collaboration as Record<string, string[]> | undefined)

const radarLabels = ['分析', '设计', '编码', '测试', '运维', '沟通']
const radarValues = computed(() => {
  const radar = (caps.value.radar || {}) as Record<string, number>
  return radarLabels.map(l => radar[l] || 0)
})

function radarPoint(i: number, scale: number) {
  const angle = (Math.PI * 2 * i) / radarLabels.length - Math.PI / 2
  return {
    x: 150 + 110 * scale * Math.cos(angle),
    y: 150 + 110 * scale * Math.sin(angle),
  }
}

function radarGridPoints(scale: number) {
  return radarLabels.map((_, i) => {
    const p = radarPoint(i, scale)
    return `${p.x},${p.y}`
  }).join(' ')
}

const radarDataPoints = computed(() =>
  radarLabels.map((_, i) => {
    const p = radarPoint(i, radarValues.value[i] / 100)
    return `${p.x},${p.y}`
  }).join(' ')
)

function radarLabelPos(i: number) {
  const p = radarPoint(i, 1.18)
  return { x: p.x, y: p.y }
}

function agentName(id: string) {
  return agentStore.getAgent(id)?.name ?? id
}
</script>

<style scoped>
.profile-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 40px;
}
.profile-page.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  color: var(--text-muted);
}

/* Hero */
.profile-hero {
  display: flex;
  gap: 24px;
  padding: 32px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  margin-bottom: 24px;
}
.hero-icon {
  width: 80px;
  height: 80px;
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.hero-info { flex: 1; min-width: 0; }
.hero-top { display: flex; align-items: center; gap: 12px; margin-bottom: 4px; }
.hero-top h1 { font-size: 24px; font-weight: 700; margin: 0; }
.hero-seniority { font-size: 13px; color: var(--text-muted); font-style: italic; margin: 4px 0 8px; }
.hero-desc { font-size: 14px; color: var(--text-secondary); margin-bottom: 12px; line-height: 1.6; }
.hero-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; }
.hero-stats { display: flex; gap: 24px; }
.stat-item { display: flex; flex-direction: column; align-items: center; }
.stat-num { font-size: 20px; font-weight: 700; color: var(--text-primary); }
.stat-label { font-size: 11px; color: var(--text-muted); }
.hero-actions { display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; }

/* Body grid */
.profile-body { display: grid; grid-template-columns: 380px 1fr; gap: 20px; }
.profile-col-left { display: flex; flex-direction: column; gap: 20px; }
.profile-col-right { display: flex; flex-direction: column; gap: 20px; }

/* Card */
.profile-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 20px 24px;
}
.profile-card h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 16px;
  color: var(--text-primary);
}

/* Radar */
.radar-container { display: flex; justify-content: center; }
.radar-svg { width: 300px; height: 300px; }
.radar-grid { fill: none; stroke: var(--border-color); stroke-width: 0.5; }
.radar-axis { stroke: var(--border-color); stroke-width: 0.3; }
.radar-data { stroke-width: 2; fill-opacity: 0.3; }
.radar-label { font-size: 11px; fill: var(--text-secondary); }

/* Tools */
.tool-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.tool-item {
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
}
.tool-name { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; margin-bottom: 4px; }
.tool-desc { font-size: 11px; color: var(--text-muted); margin: 0; line-height: 1.4; }

/* Skills */
.skill-list { display: flex; flex-direction: column; gap: 8px; }
.skill-item {
  padding: 10px 14px;
  border-radius: 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
}
.skill-header { display: flex; align-items: center; justify-content: space-between; }
.skill-name { font-size: 13px; font-weight: 600; }

/* Deliverables */
.deliverables-list { display: flex; flex-direction: column; gap: 8px; }
.deliverable-item { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-secondary); }

/* Boundary */
.boundary-section { margin-bottom: 14px; }
.boundary-section:last-child { margin-bottom: 0; }
.boundary-section h4 { font-size: 12px; font-weight: 600; color: var(--text-muted); margin: 0 0 8px; text-transform: uppercase; }
.boundary-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.delegate-list { display: flex; flex-direction: column; gap: 6px; }
.delegate-item { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.delegate-desc { color: var(--text-muted); font-size: 12px; }

/* Standards */
.standards-list { padding-left: 20px; margin: 0; }
.standards-list li { font-size: 13px; color: var(--text-secondary); margin-bottom: 6px; line-height: 1.5; }

/* Collaboration */
.collab-section { margin-bottom: 14px; }
.collab-section:last-child { margin-bottom: 0; }
.collab-section h4 { font-size: 12px; font-weight: 600; color: var(--text-muted); margin: 0 0 8px; }
.collab-agents { display: flex; flex-wrap: wrap; gap: 6px; }

.empty-hint { font-size: 13px; color: var(--text-muted); text-align: center; padding: 16px 0; }

@media (max-width: 900px) {
  .profile-body { grid-template-columns: 1fr; }
  .profile-hero { flex-direction: column; }
}
</style>
