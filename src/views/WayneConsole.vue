<template>
  <div class="Agent-console-page">
    <header class="console-header">
      <div>
        <h1>Agent Console</h1>
        <p class="subtitle">
          {{ $t('WayneConsole.subtitle') }}
        </p>
      </div>
      <div class="console-actions">
        <el-button type="primary" @click="$router.push('/Agent-stack')">{{ t('AgentConsole.text_1') }}</el-button>
      </div>
    </header>

    <el-alert class="console-alert" type="success" :closable="false" show-icon>
      <template #title>{{ $t('WayneConsole.recommended') }}</template>
      {{ $t('WayneConsole.recommended') }}
    </el-alert>

    <el-alert class="console-alert" type="warning" :closable="false" show-icon>
      <template #title>{{ $t('WayneConsole.currentCostMode', { mode: currentCostMode.label }) }}</template>
      {{ currentCostMode.description }}
    </el-alert>

    <el-card class="settings-card">
      <template #header>
        <div class="scenario-head">
          <span>{{ $t('WayneConsole.currentModelProfile') }}</span>
          <el-tag type="success" effect="plain">{{ activeProfileName }}</el-tag>
        </div>
      </template>
      <div class="profile-switch-row">
        <el-select v-model="consoleProfileId" class="profile-switch-select" :placeholder="$t('WayneConsole.switchProfile')">
          <el-option
            v-for="profile in profileOptions"
            :key="profile.id"
            :label="`${profile.name} (${profile.provider || 'unknown'} / ${profile.model || 'no-model'})`"
            :value="profile.id"
          />
        </el-select>
        <el-button type="primary" @click="applyConsoleProfile" :disabled="!consoleProfileId">{{ $t('WayneConsole.applyProfile') }}</el-button>
      </div>
      <p class="form-tip">{{ $t('WayneConsole.formTip') }}</p>
    </el-card>

    <el-card class="core-model-card-panel">
      <template #header>
        <div class="scenario-head">
          <span>{{ $t('WayneConsole.coreModelMapping') }}</span>
          <el-tag type="warning" effect="dark">{{ $t('WayneConsole.previewTag') }}</el-tag>
        </div>
      </template>
      <div class="core-model-panel-grid">
        <div v-for="item in coreModelRoles" :key="item.model" class="core-model-panel-item">
          <div class="core-model-panel-top">
            <strong>{{ item.model }}</strong>
            <el-tag size="small" effect="plain">{{ item.role }}</el-tag>
          </div>
          <p>{{ item.summary }}</p>
        </div>
      </div>
    </el-card>

    <el-card class="workflow-card">
      <template #header>
        <div class="scenario-head">
          <span>{{ $t('WayneConsole.workflowStateMachine') }}</span>
          <el-tag :type="currentWorkflow ? 'success' : 'info'" effect="plain">
            {{ currentWorkflow ? $t('WayneConsole.running') : $t('WayneConsole.notStarted') }}
          </el-tag>
        </div>
      </template>

      <div class="workflow-form">
        <el-input v-model="workflowForm.title" :placeholder="$t('WayneConsole.workflowTitlePlaceholder')" />
        <el-input
          v-model="workflowForm.goal"
          type="textarea"
          :rows="3"
          :placeholder="$t('WayneConsole.workflowGoalPlaceholder')"
        />
        <div class="workflow-actions">
          <el-button type="primary" @click="ensureWorkflowStarted">{{ $t('WayneConsole.startWorkflow') }}</el-button>
          <el-button @click="syncWorkflowMeta" :disabled="!currentWorkflow">{{ $t('WayneConsole.updateWorkflow') }}</el-button>
          <el-button type="success" plain @click="markCurrentStageDone" :disabled="!currentWorkflow">
            {{ $t('WayneConsole.currentStageDone') }}
          </el-button>
          <el-button type="warning" plain @click="markCurrentStageBlocked" :disabled="!currentWorkflow">
            {{ $t('WayneConsole.markBlocked') }}
          </el-button>
          <el-button text @click="resetWorkflow" :disabled="!currentWorkflow">{{ $t('WayneConsole.reset') }}</el-button>
        </div>
      </div>

      <div v-if="currentWorkflow" class="workflow-status">
        <div class="workflow-meta">
          <div>
            <div class="workflow-label">{{ $t('WayneConsole.currentTitle') }}</div>
            <div class="workflow-value">{{ currentWorkflow.title }}</div>
          </div>
          <div>
            <div class="workflow-label">{{ $t('WayneConsole.currentStage') }}</div>
            <div class="workflow-value">{{ workflowStore.currentStage?.label }}</div>
          </div>
          <div>
            <div class="workflow-label">{{ $t('WayneConsole.recommendedDoc') }}</div>
            <div class="workflow-value">{{ currentStageDoc }}</div>
          </div>
        </div>

        <div class="stage-timeline">
          <div
            v-for="stage in orderedStages"
            :key="stage.id"
            class="timeline-stage"
            :class="[`is-${stage.status}`, { current: currentStageId === stage.id }]"
          >
            <div class="timeline-badge">{{ stage.label }}</div>
            <div class="timeline-owner">{{ stage.ownerLabel }}</div>
            <div class="timeline-deliverable">{{ stage.deliverable }}</div>
            <div class="timeline-doc">{{ stage.deliveryDocName }}</div>
          </div>
        </div>

        <div class="handoff-section">
          <div class="section-heading small">
            <h2>{{ $t('WayneConsole.recentHandoff') }}</h2>
            <p>{{ $t('WayneConsole.handoffIntro') }}</p>
          </div>
          <div v-if="currentWorkflow.handoffs.length" class="handoff-list">
            <div v-for="item in currentWorkflow.handoffs.slice(0, 6)" :key="item.id" class="handoff-item">
              <div class="handoff-top">
                <span>{{ item.stageId }}</span>
                <el-tag size="small" effect="plain">{{ item.recommendedModel }}</el-tag>
              </div>
              <div class="handoff-route">{{ item.fromAgentId }} -> {{ item.toAgentId }}</div>
              <p>{{ item.note }}</p>
            </div>
          </div>
          <div v-else class="handoff-empty">{{ $t('WayneConsole.noHandoff') }}</div>
        </div>
      </div>
    </el-card>

    <section class="section-block">
      <div class="section-heading">
        <h2>{{ $t('WayneConsole.section1Title') }}</h2>
        <p>{{ $t('WayneConsole.section1Desc') }}</p>
      </div>

      <div class="stage-grid">
        <div
          v-for="stage in stages"
          :key="stage.id"
          class="stage-card"
          @click="openWorkflow(stage.agentId, stage.seed, stage.recommendedModel)"
        >
          <div class="stage-top">
            <div class="stage-badge">{{ stage.step }}</div>
            <el-tag size="small" effect="plain">{{ stage.agent }}</el-tag>
          </div>
          <div class="recommended-model">{{ stage.recommendedModel }}</div>
          <h3>{{ stage.title }}</h3>
          <p class="stage-desc">{{ stage.description }}</p>
          <div class="stage-footer">
            <span class="stage-output">{{ stage.output }}</span>
            <span class="launch-link">{{ $t('WayneConsole.launch') }}</span>
          </div>
        </div>
      </div>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>{{ $t('WayneConsole.section2Title') }}</h2>
        <p>{{ $t('WayneConsole.section2Desc') }}</p>
      </div>

      <div class="scenario-grid">
        <el-card v-for="scenario in scenarios" :key="scenario.title" class="scenario-card" shadow="hover">
          <template #header>
            <div class="scenario-head">
              <span>{{ scenario.title }}</span>
              <el-tag size="small" :type="scenario.tagType">{{ scenario.modelMode }}</el-tag>
            </div>
          </template>
          <p class="scenario-desc">{{ scenario.description }}</p>
          <div class="scenario-actions">
            <el-button
              v-for="action in scenario.actions"
              :key="action.label"
              size="small"
              @click="openWorkflow(action.agentId, action.seed, action.recommendedModel)"
            >
              {{ action.label }}
            </el-button>
          </div>
        </el-card>
      </div>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>{{ $t('WayneConsole.section3Title') }}</h2>
        <p>{{ $t('WayneConsole.section3Desc') }}</p>
      </div>

      <div class="agent-grid">
        <div
          v-for="entry in agents"
          :key="entry.id"
          class="agent-entry"
          @click="openAgent(entry.id, entry.recommendedModel.replace($t('WayneConsole.recommendedPrefix'), '').trim())"
        >
          <div class="agent-entry-icon" :style="{ background: `${entry.color}18`, color: entry.color }">
            <el-icon :size="22"><component :is="entry.icon" /></el-icon>
          </div>
          <div class="agent-entry-body">
            <div class="agent-entry-top">
              <h3>{{ entry.name }}</h3>
              <el-tag size="small" effect="plain">{{ entry.title }}</el-tag>
            </div>
            <div class="agent-recommended-model">{{ entry.recommendedModel }}</div>
            <div class="agent-bound-profile">
              {{ $t('WayneConsole.bindProfile', { name: settingsStore.getRoleBoundProfile(entry.id)?.name || $t('WayneConsole.unbound') }) }}
            </div>
            <p>{{ entry.description }}</p>
            <div class="agent-bind-row">
              <el-select
                :model-value="roleProfileDrafts[entry.id]"
                class="agent-bind-select"
                :placeholder="$t('WayneConsole.bindPlaceholder')"
                @change="(val) => (roleProfileDrafts[entry.id] = String(val || ''))"
                @click.stop
              >
                <el-option
                  v-for="profile in profileOptions"
                  :key="profile.id"
                  :label="profile.name"
                  :value="profile.id"
                />
              </el-select>
              <el-button size="small" @click.stop="bindRoleProfile(entry.id)">{{ $t('WayneConsole.bind') }}</el-button>
              <el-button size="small" text @click.stop="unbindRoleProfile(entry.id)">{{ $t('WayneConsole.clear') }}</el-button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="section-block">
      <div class="section-heading">
        <h2>{{ $t('WayneConsole.section4Title') }}</h2>
        <p>{{ $t('WayneConsole.section4Desc') }}</p>
      </div>

      <el-card class="delivery-card">
        <template #header>
          <div class="scenario-head">
            <span>{{ $t('WayneConsole.docsDelivery') }}</span>
            <div class="delivery-actions">
              <el-button
                size="small"
                type="success"
                plain
                :disabled="!currentWorkflow"
                @click="openDeliveryDoc(currentStageDoc)"
              >
                {{ $t('WayneConsole.openCurrentDoc') }}
              </el-button>
              <el-button size="small" @click="initializeDeliveryDocs" :loading="deliveryLoading">
                {{ $t('WayneConsole.initTemplate') }}
              </el-button>
              <el-button
                type="primary"
                size="small"
                @click="saveDeliveryDoc"
                :loading="deliverySaving"
                :disabled="!activeDeliveryName"
              >
                {{ $t('WayneConsole.saveCurrentDoc') }}
              </el-button>
            </div>
          </div>
        </template>

        <div class="delivery-layout">
          <aside class="delivery-sidebar">
            <div
              v-for="doc in sortedDeliveryDocs"
              :key="doc.name"
              class="delivery-doc-item"
              :class="{ active: doc.name === activeDeliveryName }"
              @click="openDeliveryDoc(doc.name)"
            >
              <div class="delivery-doc-top">
                <strong>{{ doc.title }}</strong>
                <el-tag size="small" effect="plain">{{ doc.name }}</el-tag>
              </div>
              <p>{{ doc.description }}</p>
            </div>
          </aside>

          <div class="delivery-editor">
            <div class="delivery-editor-top">
              <div>
                <h3>{{ activeDeliveryDoc?.title || activeDeliveryName }}</h3>
                <p>{{ activeDeliveryDoc?.description || $t('WayneConsole.selectDoc') }}</p>
              </div>
            </div>
            <el-input
              v-model="deliveryDraft"
              type="textarea"
              :rows="24"
              resize="none"
              :disabled="deliveryLoading"
            />
          </div>
        </div>
      </el-card>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  getAgentCostModeMeta,
  tryApplyRecommendedModel,
} from '@/services/wayneRouting'
import { useAgentWorkflowStore } from '@/stores/wayneWorkflow'
import { Agent_STAGE_ORDER } from '@/services/wayneWorkflow'
import { useSettingsStore } from '@/stores/settings'
import {
  initDeliveryDocs,
  listDeliveryDocs,
  readDeliveryDoc,
  writeDeliveryDoc,
  type DeliveryDoc,
  type DeliveryDocMeta,
} from '@/services/deliveryDocs'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const router = useRouter()
const workflowStore = useAgentWorkflowStore()
const settingsStore = useSettingsStore()
const consoleProfileId = ref(settingsStore.activeProfileId)
const roleProfileDrafts = reactive<Record<string, string>>({})
const workflowForm = reactive({
  title: workflowStore.workflow?.title || t('WayneConsole.startWorkflow'),
  goal: workflowStore.workflow?.goal || '',
})
const deliveryDocs = ref<DeliveryDocMeta[]>([])
const activeDeliveryName = ref('01-prd.md')
const activeDeliveryDoc = ref<DeliveryDoc | null>(null)
const deliveryDraft = ref('')
const deliveryLoading = ref(false)
const deliverySaving = ref(false)

const currentWorkflow = computed(() => workflowStore.workflow)
const currentStageId = computed(() => workflowStore.currentStage?.id || null)
const currentStageDoc = computed(() => workflowStore.currentStage?.deliveryDocName || '01-prd.md')
const currentCostMode = computed(() => getAgentCostModeMeta(settingsStore.settings.AgentCostMode))
const activeProfileName = computed(() => settingsStore.activeProfile?.name || t('WayneConsole.unnamedProfile'))
const profileOptions = computed(() =>
  settingsStore.profiles.map((profile) => ({
    id: profile.id,
    name: profile.name,
    provider: profile.settings.provider,
    model: profile.settings.model,
  })),
)
const orderedStages = computed(() => {
  const wf = workflowStore.workflow
  if (!wf) return []
  return Agent_STAGE_ORDER.map((id) => wf.stages.find((stage) => stage.id === id)).filter(Boolean)
})

const sortedDeliveryDocs = computed(() => deliveryDocs.value)

const stages = [
  {
    id: 'orchestrate',
    step: '01',
    title: t('WayneConsole.stage01Title'),
    agent: t('WayneConsole.agentOrchName'),
    agentId: 'Agent-orchestrator',
    description: t('WayneConsole.stage01Desc'),
    output: t('WayneConsole.stage01Output'),
    seed: t('WayneConsole.stage01Seed'),
    recommendedModel: 'Opus 4.6',
  },
  {
    id: 'prd',
    step: '02',
    title: t('WayneConsole.stage02Title'),
    agent: t('WayneConsole.agentPmName'),
    agentId: 'Agent-product-manager',
    description: t('WayneConsole.stage02Desc'),
    output: '01-prd.md',
    seed: t('WayneConsole.stage02Seed'),
    recommendedModel: 'GPT-4.5',
  },
  {
    id: 'build',
    step: '03',
    title: t('WayneConsole.stage03Title'),
    agent: t('WayneConsole.agentDevName'),
    agentId: 'Agent-developer',
    description: t('WayneConsole.stage03Desc'),
    output: t('WayneConsole.stage03Output'),
    seed: t('WayneConsole.stage03Seed'),
    recommendedModel: 'Sonnet 4.6',
  },
  {
    id: 'qa',
    step: '04',
    title: t('WayneConsole.stage04Title'),
    agent: t('WayneConsole.agentQaName'),
    agentId: 'Agent-qa-lead',
    description: t('WayneConsole.stage04Desc'),
    output: t('WayneConsole.stage04Output'),
    seed: t('WayneConsole.stage04Seed'),
    recommendedModel: 'Gemini 4',
  },
]

const scenarios = [
  {
    title: t('WayneConsole.scenario1Title'),
    description: t('WayneConsole.scenario1Desc'),
    modelMode: t('WayneConsole.scenario1ModelMode'),
    tagType: 'success' as const,
    actions: [
      {
        label: t('WayneConsole.scenario1Action1'),
        agentId: 'Agent-orchestrator',
        seed: t('WayneConsole.scenario1Seed1'),
        recommendedModel: 'Opus 4.6',
      },
      {
        label: t('WayneConsole.scenario1Action2'),
        agentId: 'Agent-product-manager',
        seed: t('WayneConsole.scenario1Seed2'),
        recommendedModel: 'GPT-4.5',
      },
    ],
  },
  {
    title: t('WayneConsole.scenario2Title'),
    description: t('WayneConsole.scenario2Desc'),
    modelMode: t('WayneConsole.scenario2ModelMode'),
    tagType: 'primary' as const,
    actions: [
      {
        label: t('WayneConsole.scenario2Action1'),
        agentId: 'Agent-developer',
        seed: t('WayneConsole.scenario2Seed1'),
        recommendedModel: 'Sonnet 4.6',
      },
      {
        label: t('WayneConsole.scenario2Action2'),
        agentId: 'Agent-orchestrator',
        seed: t('WayneConsole.scenario2Seed2'),
        recommendedModel: 'Opus 4.6',
      },
    ],
  },
  {
    title: t('WayneConsole.scenario3Title'),
    description: t('WayneConsole.scenario3Desc'),
    modelMode: t('WayneConsole.scenario3ModelMode'),
    tagType: 'warning' as const,
    actions: [
      {
        label: t('WayneConsole.scenario3Action1'),
        agentId: 'Agent-qa-lead',
        seed: t('WayneConsole.scenario3Seed1'),
        recommendedModel: 'Gemini 4',
      },
      {
        label: t('WayneConsole.scenario3Action2'),
        agentId: 'Agent-orchestrator',
        seed: t('WayneConsole.scenario3Seed2'),
        recommendedModel: 'Opus 4.6',
      },
    ],
  },
  {
    title: t('WayneConsole.scenario4Title'),
    description: t('WayneConsole.scenario4Desc'),
    modelMode: t('WayneConsole.scenario4ModelMode'),
    tagType: 'info' as const,
    actions: [
      {
        label: t('WayneConsole.scenario4Action1'),
        agentId: 'Agent-china-strategist',
        seed: t('WayneConsole.scenario4Seed1'),
        recommendedModel: t('WayneStack.modelGlm'),
      },
      {
        label: t('WayneConsole.scenario4Action2'),
        agentId: 'Agent-china-strategist',
        seed: t('WayneConsole.scenario4Seed2'),
        recommendedModel: t('WayneStack.modelGlm'),
      },
    ],
  },
]

const agents = [
  {
    id: 'Agent-orchestrator',
    name: t('WayneConsole.agentOrchName'),
    title: 'Orchestrator',
    icon: 'Connection',
    color: '#7c5cff',
    description: t('WayneConsole.agentOrchDesc'),
    recommendedModel: t('WayneStack.recommendedOpus'),
  },
  {
    id: 'Agent-product-manager',
    name: t('WayneConsole.agentPmName'),
    title: 'Product Manager',
    icon: 'Memo',
    color: '#3b82f6',
    description: t('WayneConsole.agentPmDesc'),
    recommendedModel: t('WayneStack.recommendedGpt'),
  },
  {
    id: 'Agent-developer',
    name: t('WayneConsole.agentDevName'),
    title: 'Developer',
    icon: 'Cpu',
    color: '#14b8a6',
    description: t('WayneConsole.agentDevDesc'),
    recommendedModel: t('WayneStack.recommendedSonnet'),
  },
  {
    id: 'Agent-qa-lead',
    name: t('WayneConsole.agentQaName'),
    title: 'QA Lead',
    icon: 'CircleCheckFilled',
    color: '#f59e0b',
    description: t('WayneConsole.agentQaDesc'),
    recommendedModel: t('WayneStack.recommendedGemini'),
  },
  {
    id: 'Agent-china-strategist',
    name: t('WayneConsole.agentChinaName'),
    title: 'China Strategist',
    icon: 'ChatLineSquare',
    color: '#ef4444',
    description: t('WayneConsole.agentChinaDesc'),
    recommendedModel: t('WayneStack.recommendedGlm'),
  },
]

const coreModelRoles = [
  {
    model: 'Opus 4.6',
    role: t('WayneConsole.coreOpusRole'),
    summary: t('WayneConsole.coreOpusSummary'),
  },
  {
    model: 'Sonnet 4.6',
    role: t('WayneConsole.coreSonnetRole'),
    summary: t('WayneConsole.coreSonnetSummary'),
  },
  {
    model: 'GPT-4.5',
    role: t('WayneConsole.coreGptRole'),
    summary: t('WayneConsole.coreGptSummary'),
  },
  {
    model: 'Gemini 4',
    role: t('WayneConsole.coreGeminiRole'),
    summary: t('WayneConsole.coreGeminiSummary'),
  },
  {
    model: t('WayneStack.modelGlm'),
    role: t('WayneConsole.coreGlmRole'),
    summary: t('WayneConsole.coreGlmSummary'),
  },
]

async function openAgent(agentId: string, recommendedModel?: string) {
  const matchedProfile =
    settingsStore.getRoleBoundProfile(agentId) ?? findProfileForRecommendedModel(recommendedModel)
  if (matchedProfile) {
    settingsStore.activateProfile(matchedProfile.id)
    consoleProfileId.value = matchedProfile.id
    ElMessage.success(t('WayneConsole.profileSwitched', { name: matchedProfile.name }))
  }
  const result = tryApplyRecommendedModel(recommendedModel)
  if (result.reason) {
    if (result.applied) ElMessage.success(result.reason)
    else ElMessage.warning(result.reason)
  }

  router.push({
    path: `/agent/${agentId}`,
    query: recommendedModel
      ? {
          recommendedModel,
          recommendedApplied: result.applied ? '1' : '0',
        }
      : {},
  })
}

async function openWorkflow(agentId: string, seed: string, recommendedModel?: string) {
  const matchedProfile =
    settingsStore.getRoleBoundProfile(agentId) ?? findProfileForRecommendedModel(recommendedModel)
  if (matchedProfile) {
    settingsStore.activateProfile(matchedProfile.id)
    consoleProfileId.value = matchedProfile.id
    ElMessage.success(t('WayneConsole.profileSwitched', { name: matchedProfile.name }))
  }
  const result = tryApplyRecommendedModel(recommendedModel)
  if (result.reason) {
    if (result.applied) ElMessage.success(result.reason)
    else ElMessage.warning(result.reason)
  }

  router.push({
    path: `/agent/${agentId}`,
    query: {
      autorun: '1',
      seed,
      ...(recommendedModel
        ? {
            recommendedModel,
            recommendedApplied: result.applied ? '1' : '0',
          }
        : {}),
    },
  })
}

function recommendedModelNeedles(label?: string) {
  const text = (label || '').toLowerCase()
  if (text.includes('opus')) return ['claude-opus-4-6', 'opus']
  if (text.includes('sonnet')) return ['claude-sonnet-4-6', 'sonnet']
  if (text.includes('gpt-4.5')) return ['gpt-4.5']
  if (text.includes('gemini')) return ['gemini']
  if (text.includes('glm') || text.includes('智谱')) return ['glm-4.5', 'glm', 'zhipu']
  return [text]
}

function findProfileForRecommendedModel(label?: string) {
  const needles = recommendedModelNeedles(label)
  return settingsStore.profiles.find((profile) => {
    const name = profile.name.toLowerCase()
    const model = (profile.settings.model || '').toLowerCase()
    return needles.some((needle) => needle && (name.includes(needle) || model.includes(needle)))
  })
}

function applyConsoleProfile() {
  if (!consoleProfileId.value) return
  settingsStore.activateProfile(consoleProfileId.value)
  ElMessage.success(t('WayneConsole.profileSwitched', { name: settingsStore.activeProfile?.name || '' }))
}

function bindRoleProfile(agentId: string) {
  const profileId = roleProfileDrafts[agentId]
  if (!profileId) {
    ElMessage.warning(t('AgentConsole.elMessage_1'))
    return
  }
  const ok = settingsStore.bindRoleProfile(agentId, profileId)
  if (!ok) {
    ElMessage.error(t('AgentConsole.elMessage_2'))
    return
  }
  ElMessage.success(t('AgentConsole.elMessage_3'))
}

function unbindRoleProfile(agentId: string) {
  settingsStore.unbindRoleProfile(agentId)
  roleProfileDrafts[agentId] = ''
  ElMessage.success(t('AgentConsole.elMessage_4'))
}

for (const entry of agents) {
  roleProfileDrafts[entry.id] = settingsStore.getRoleBoundProfileId(entry.id) || ''
}

function ensureWorkflowStarted() {
  if (workflowStore.hasWorkflow) return true
  if (!workflowForm.goal.trim()) {
    ElMessage.warning(t('AgentConsole.elMessage_5'))
    return false
  }
  workflowStore.startWorkflow(workflowForm.title, workflowForm.goal)
  activeDeliveryName.value = currentStageDoc.value
  void openDeliveryDoc(currentStageDoc.value)
  ElMessage.success(t('AgentConsole.elMessage_6'))
  return true
}

function syncWorkflowMeta() {
  if (!workflowStore.hasWorkflow) return
  workflowStore.updateMetadata({
    title: workflowForm.title,
    goal: workflowForm.goal,
  })
  ElMessage.success(t('AgentConsole.elMessage_7'))
}

function markCurrentStageDone() {
  if (!workflowStore.hasWorkflow) return
  workflowStore.completeCurrentStage(t('WayneConsole.blockReason'))
  activeDeliveryName.value = currentStageDoc.value
  void openDeliveryDoc(currentStageDoc.value)
  ElMessage.success(t('AgentConsole.elMessage_8'))
}

function markCurrentStageBlocked() {
  if (!workflowStore.hasWorkflow) return
  workflowStore.blockCurrentStage(t('WayneConsole.blockReason'))
  ElMessage.warning(t('AgentConsole.elMessage_9'))
}

function resetWorkflow() {
  workflowStore.resetWorkflow()
  workflowForm.title = t('WayneConsole.startWorkflow')
  workflowForm.goal = ''
  ElMessage.success(t('AgentConsole.elMessage_10'))
}

async function loadDeliveryList() {
  deliveryDocs.value = await listDeliveryDocs()
}

async function openDeliveryDoc(name: string) {
  deliveryLoading.value = true
  try {
    activeDeliveryName.value = name
    activeDeliveryDoc.value = await readDeliveryDoc(name)
    deliveryDraft.value = activeDeliveryDoc.value.content
  } finally {
    deliveryLoading.value = false
  }
}

async function initializeDeliveryDocs() {
  deliveryLoading.value = true
  try {
    deliveryDocs.value = await initDeliveryDocs()
    await openDeliveryDoc(activeDeliveryName.value)
    ElMessage.success(t('AgentConsole.elMessage_11'))
  } finally {
    deliveryLoading.value = false
  }
}

async function saveDeliveryDoc() {
  if (!activeDeliveryName.value) return
  deliverySaving.value = true
  try {
    activeDeliveryDoc.value = await writeDeliveryDoc(activeDeliveryName.value, deliveryDraft.value)
    await loadDeliveryList()
    ElMessage.success(t('AgentConsole.elMessage_12'))
  } finally {
    deliverySaving.value = false
  }
}

onMounted(async () => {
  try {
    await loadDeliveryList()
    activeDeliveryName.value = currentStageDoc.value
    await openDeliveryDoc(activeDeliveryName.value)
  } catch (e) {
    console.error(e)
  }
})
</script>

<style scoped>
@import "./WayneConsole.css";
</style>
