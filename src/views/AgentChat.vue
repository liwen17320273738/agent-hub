<template>
  <div v-if="!agent" class="chat-page" style="display: flex; align-items: center; justify-content: center;">
    <div style="text-align: center; color: var(--text-secondary);">
      <p style="font-size: 18px; margin-bottom: 12px;">{{ t('agentChat.text_1') }}</p>
      <router-link to="/">
        <el-button type="primary">{{ t('agentChat.text_2') }}</el-button>
      </router-link>
    </div>
  </div>
  <div class="chat-page" v-else>
    <!-- Conversation sidebar -->
    <aside class="conv-sidebar">
      <div class="conv-header">
        <el-icon :style="{ color: agent.color }" :size="20">
          <component :is="resolveAgentIcon(agent.icon)" />
        </el-icon>
        <span class="conv-agent-name">{{ agent.name }}</span>
        <router-link :to="agentProfileLink" class="profile-link" :title="t('agentChat.title_1')">
          <el-icon :size="16"><User /></el-icon>
        </router-link>
      </div>

      <el-button class="new-chat-btn" @click="startNewChat" type="primary" plain>
        <el-icon><Plus /></el-icon>
        {{ t('agentChat.newChat') }}
      </el-button>

      <div class="conv-search">
        <el-input
          v-model="convListFilter"
          clearable
          size="small"
          :placeholder="t('agentChat.placeholder_1')"
        />
      </div>

      <div class="conv-list">
        <div
          v-for="conv in filteredConversations"
          :key="conv.id"
          class="conv-item"
          :class="{ active: conv.id === chatStore.activeConversationId }"
          @click="chatStore.activeConversationId = conv.id"
        >
          <el-icon :size="14"><ChatDotRound /></el-icon>
          <span class="conv-title">{{ conv.title }}</span>
          <el-icon class="conv-delete" :size="14" @click.stop="handleDelete(conv.id)">
            <Delete />
          </el-icon>
        </div>
      </div>
    </aside>

    <!-- Chat area -->
    <div class="chat-area">
      <div v-if="pipelineTask" class="pipeline-context-banner">
        <el-icon><Connection /></el-icon>
        <span>{{ t('agentChat.text_3') }}<strong>{{ pipelineTask.title }}</strong> ({{ pipelineTask.currentStageId }})</span>
        <router-link :to="`/pipeline/task/${pipelineTask.id}`" class="pipeline-link">
          {{ t('agentChat.viewTask') }}
        </router-link>
      </div>
      <div v-if="activeConv" class="chat-toolbar">
        <el-tag
          v-if="recommendedModelLabel"
          size="small"
          :type="recommendedModelApplied ? 'success' : 'warning'"
          effect="plain"
          class="recommended-model-tag"
        >
          {{
            (recommendedModelApplied ? t('agentChat.modelAppliedPrefix') : t('agentChat.modelRecommendedPrefix')) +
            recommendedModelLabel
          }}
        </el-tag>
        <el-tooltip
          v-if="activeConv"
          :content="t('agentChat.runtimeModeHint')"
          placement="bottom"
        >
          <el-switch
            v-model="useBackendRuntime"
            class="agent-runtime-switch"
            size="small"
            :active-text="t('agentChat.runtimeBackend')"
            :inactive-text="t('agentChat.runtimeLocal')"
          />
        </el-tooltip>
        <el-button text size="small" :disabled="isThisConvGenerating" @click="exportMarkdown">
          {{ t('agentChat.exportMd') }}
        </el-button>
        <el-button text size="small" :disabled="isThisConvGenerating" @click="exportJson">
          {{ t('agentChat.exportJson') }}
        </el-button>
        <el-button
          text
          size="small"
          :loading="summarizing"
          :disabled="isThisConvGenerating"
          @click="generateConversationSummary"
        >
          {{ t('agentChat.genSummary') }}
        </el-button>
        <el-select
          v-model="deliveryTargetDoc"
          size="small"
          class="delivery-target-select"
          :placeholder="t('agentChat.placeholder_2')"
        >
          <el-option v-for="doc in deliveryDocOptions" :key="doc.name" :label="doc.title" :value="doc.name" />
        </el-select>
        <el-button
          text
          size="small"
          :disabled="!deliveryTargetDoc || !latestAssistantMessage || isThisConvGenerating"
          @click="writeLatestAssistantToDelivery"
        >
          {{ t('agentChat.writeToDoc') }}
        </el-button>
      </div>

      <!-- Welcome / empty state -->
      <div v-if="!activeConv && !showAgentRouterPanel" class="chat-welcome">
        <div class="welcome-icon" :style="{ background: agent.color + '20', color: agent.color }">
          <el-icon :size="48"><component :is="resolveAgentIcon(agent.icon)" /></el-icon>
        </div>
        <h2>{{ agent.name }} · {{ agent.title }}</h2>
        <p class="welcome-desc">{{ agent.description }}</p>
        <router-link :to="agentProfileLink" class="view-profile-btn">
          <el-icon :size="14"><User /></el-icon> {{ t('agentChat.title_1') }}
        </router-link>

        <div class="quick-prompts">
          <h3>{{ t('agentChat.text_4') }}</h3>
          <div class="prompt-grid">
            <div
              v-for="(prompt, i) in agent.quickPrompts"
              :key="i"
              class="prompt-card"
              @click="handleQuickPrompt(prompt)"
            >
              <el-icon :size="16"><ChatLineRound /></el-icon>
              <span>{{ prompt }}</span>
            </div>
          </div>
        </div>
      </div>

      <div v-else-if="showAgentRouterPanel" class="Agent-router-panel">
        <div class="Agent-router-header">
          <div>
            <h3>{{ t('agentChat.text_5') }}</h3>
            <p>{{ t('agentChat.text_6') }}</p>
          </div>
          <el-tag type="warning" effect="plain">Orchestrator</el-tag>
        </div>

        <el-input
          v-model="AgentRoutingTask"
          type="textarea"
          :rows="3"
          :placeholder="t('agentChat.placeholder_3')"
        />

        <div class="Agent-router-actions">
          <el-button type="primary" @click="refreshAgentSuggestions">{{ t('agentChat.text_7') }}</el-button>
          <el-button text @click="resetAgentRouting">{{ t('agentChat.text_8') }}</el-button>
        </div>

        <div class="Agent-suggestion-list">
          <div
            v-for="routeItem in AgentSuggestions"
            :key="routeItem.id"
            class="Agent-suggestion-card"
          >
            <div class="Agent-suggestion-top">
              <div>
                <div class="Agent-suggestion-stage">{{ routeItem.stage }}</div>
                <div class="Agent-suggestion-title">{{ routeItem.title }}</div>
              </div>
              <el-tag size="small" type="info" effect="plain">{{ routeItem.recommendedModel }}</el-tag>
            </div>
            <div class="Agent-suggestion-agent">{{ routeItem.targetAgentName }}</div>
            <p class="Agent-suggestion-reason">{{ routeItem.reason }}</p>
            <div class="Agent-suggestion-actions">
              <el-button size="small" type="primary" @click="handoffAgentRoute(routeItem)">
                {{ t('agentChat.handoffToRole') }}
              </el-button>
              <el-button size="small" text @click="openRouteAgent(routeItem)">
                {{ t('agentChat.openRoleOnly') }}
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- Messages -->
      <div v-else class="chat-messages" ref="messagesRef">
        <ChatMessage
          v-for="(msg, idx) in activeConv.messages"
          :key="msg.id"
          :message="msg"
          :agent="agent"
          :show-regenerate="
            !!agent &&
            !isThisConvGenerating &&
            idx === activeConv.messages.length - 1 &&
            msg.role === 'assistant'
          "
          :show-edit-user="!isThisConvGenerating"
          @regenerate="regenerateLast"
          @edit-user="openEditUser"
        />
        <ChatMessage
          v-if="activeConv && chatStore.isGeneratingFor(activeConv.id)"
          :message="streamingMessage"
          :agent="agent"
          :streaming="true"
        />
        <div ref="scrollAnchor" />
      </div>

      <!-- Input -->
      <div class="chat-input-area">
        <el-alert
          v-if="visibleError"
          class="chat-error-alert"
          type="error"
          :description="visibleError"
          show-icon
          closable
          @close="clearRequestError"
        />
        <div v-if="agent" class="composer-card">
          <el-input
            v-model="inputText"
            class="composer-textarea"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 8 }"
            :placeholder="t('agentChat.placeholder_4')"
            @keydown="handleKeydown"
            :disabled="isThisConvGenerating"
          />
          <div class="composer-toolbar">
            <router-link
              :to="agentProfileLink"
              class="toolbar-pill composer-role-pill"
              :title="t('agentChat.title_1')"
            >
              <span class="composer-role-avatar" :style="{ background: agent.color + '30', color: agent.color }">
                <el-icon :size="14"><component :is="resolveAgentIcon(agent.icon)" /></el-icon>
              </span>
              <span class="composer-role-text">{{ agent.title || agent.name }}</span>
              <el-icon class="composer-role-chevron" :size="12"><ArrowDown /></el-icon>
            </router-link>

            <div class="toolbar-pill composer-model-pill" :title="resolvedChatModelDisplay">
              <span class="composer-model-brand" aria-hidden="true">{{ modelBrandMark(resolvedChatModelIdForAgent) }}</span>
              <el-select
                v-model="perAgentModelSelect"
                filterable
                clearable
                size="small"
                class="composer-model-select"
                :placeholder="chatModelShortLabel"
              >
                <el-option key="__auto__" :value="''" :label="t('agentChat.modelAuto')" />
                <el-option-group v-for="g in modelPickerGroups" :key="g.provider" :label="g.providerLabel">
                  <el-option v-for="m in g.models" :key="g.provider + m.id" :label="m.label" :value="m.id" />
                </el-option-group>
              </el-select>
            </div>

            <el-popover
              placement="top-start"
              :width="360"
              trigger="click"
              popper-class="agent-chat-skills-popover"
              @show="onComposerSkillsPopoverOpen"
            >
              <template #reference>
                <button type="button" class="toolbar-pill composer-skills-pill">
                  <span class="composer-skills-icon" aria-hidden="true">⛏</span>
                  Skills
                </button>
              </template>
              <div class="skills-popover-body">
                <div v-if="boundSkillIds.length" class="skills-bound-row">
                  <span class="skills-bound-label">{{ t('agentChat.skillsBoundLabel') }}</span>
                  <div class="skills-bound-tags">
                    <el-tag v-for="sid in boundSkillIds" :key="sid" size="small" effect="plain" type="info">
                      {{ sid }}
                    </el-tag>
                  </div>
                </div>
                <el-input
                  v-model="skillSearchQuery"
                  size="small"
                  clearable
                  :placeholder="t('agentChat.skillsSearchPlaceholder')"
                >
                  <template #suffix>
                    <el-icon><Search /></el-icon>
                  </template>
                </el-input>
                <p v-if="skillsPopoverError" class="skills-pop-msg skills-pop-error">{{ skillsPopoverError }}</p>
                <p v-else-if="skillsPopoverLoading" class="skills-pop-msg">{{ t('agentChat.skillsLoading') }}</p>
                <p v-else-if="!filteredComposerSkills.length" class="skills-pop-msg">{{ t('agentChat.skillsEmpty') }}</p>
                <ul v-else class="skills-pop-list">
                  <li
                    v-for="s in filteredComposerSkills"
                    :key="s.id"
                    class="skills-pop-item"
                    :class="{ 'is-disabled': !s.enabled }"
                    @click="insertSkillIntoInput(s)"
                  >
                    <span class="skills-pop-letter" :style="{ background: skillPickerColor(s.id) }">{{
                      skillPickerLetter(s)
                    }}</span>
                    <div class="skills-pop-item-text">
                      <div class="skills-pop-name">{{ s.name || s.id }}</div>
                      <div class="skills-pop-desc">{{ (s.description && s.description.trim()) || '—' }}</div>
                    </div>
                  </li>
                </ul>
                <router-link to="/skills" class="skills-pop-footer-link" @click.stop>
                  {{ t('agentChat.skillsImportOrManage') }}
                </router-link>
              </div>
            </el-popover>

            <div class="composer-toolbar-spacer" />

            <VoiceInput compact class="composer-voice" @fill-input="onVoiceFill" />

            <el-button
              v-if="isThisConvGenerating"
              class="composer-action-stop"
              type="danger"
              :icon="VideoPause"
              plain
              @click="stopGeneration"
            >
              {{ t('agentChat.stop') }}
            </el-button>
            <el-button
              v-else
              class="composer-send-btn"
              type="primary"
              :icon="Promotion"
              circle
              :disabled="!inputText.trim()"
              @click="sendMessage"
            />
          </div>
        </div>
      </div>
    </div>

    <el-dialog v-model="editDialogVisible" :title="t('agentChat.title_2')" width="520px" destroy-on-close>
      <el-input v-model="editDraft" type="textarea" :autosize="{ minRows: 4, maxRows: 14 }" />
      <template #footer>
        <el-button @click="editDialogVisible = false">{{ t('agentChat.text_9') }}</el-button>
        <el-button type="primary" :disabled="!editDraft.trim()" @click="confirmEditUser">
          {{ t('agentChat.saveAndResend') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Connection, Promotion, ArrowDown, VideoPause, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAgentStore } from '@/stores/agents'
import { useChatStore } from '@/stores/chat'
import { useSettingsStore } from '@/stores/settings'
import { useAgentWorkflowStore } from '@/stores/wayneWorkflow'
import { chatCompletion } from '@/services/llm'
import { completionWithToolLoop } from '@/services/chatWithTools'
import { buildLLMMessages } from '@/services/messageContext'
import { runAgentStream, type AgentRunRequest, type AgentStreamEvent } from '@/services/agentApi'
import { getAuthTokenOrPipelineKey, fetchLiveModels } from '@/services/api'
import { resolveStreamAgentKey } from '@/services/agentRuntimeRouting'
import { fetchTask, fetchSkills, type Skill } from '@/services/pipelineApi'
import type { AgentConfig, ChatMessage as ChatMessageType, Conversation, PipelineTask } from '@/agents/types'
import ChatMessage from '@/components/ChatMessage.vue'
import VoiceInput from '@/components/voice/VoiceInput.vue'
import { listDeliveryDocs, readDeliveryDoc, writeDeliveryDoc, type DeliveryDocMeta } from '@/services/deliveryDocs'
import {
  buildAgentSeed,
  getAgentDefaultRoutes,
  inferAgentRoute,
  tryApplyRecommendedModel,
  type AgentRouteSuggestion,
} from '@/services/wayneRouting'
import { resolveAgentIcon } from '@/utils/agentIcon'
import { useI18n } from 'vue-i18n'
import { appLocaleToBcp47 } from '@/i18n'
import { MODEL_CATALOG, liveModelProviderLabel, type ModelProvider, type ModelCatalogEntry } from '@/services/modelCatalog'

const { t, locale } = useI18n()

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const chatStore = useChatStore()
const settingsStore = useSettingsStore()
const AgentWorkflowStore = useAgentWorkflowStore()

const inputText = ref('')
const messagesRef = ref<HTMLElement>()
const scrollAnchor = ref<HTMLElement>()

/** Failure copy is not appended to history; only shown in this session. */
const requestError = ref<{ conversationId: string; message: string } | null>(null)
const conversationAbortControllers = new Map<string, AbortController>()
const summarizing = ref(false)
const convListFilter = ref('')
const editDialogVisible = ref(false)
const editDraft = ref('')
const editingMessageId = ref<string | null>(null)
const lastAutoRunKey = ref('')
const pendingRecommendedModel = ref('')
const pendingRecommendedApplied = ref(false)
const AgentRoutingTask = ref('')
const AgentSuggestions = ref<AgentRouteSuggestion[]>(getAgentDefaultRoutes())
const deliveryDocOptions = ref<DeliveryDocMeta[]>([])
const deliveryTargetDoc = ref('01-prd.md')
const pipelineTask = ref<PipelineTask | null>(null)

interface ModelPickGroup {
  provider: string
  providerLabel: string
  models: { id: string; label: string }[]
}

const modelPickerGroups = ref<ModelPickGroup[]>([])

async function loadModelPickerGroups() {
  try {
    const live = await fetchLiveModels()
    const prov = live.providers as Record<string, { id: string; label?: string }[]>
    const groups: ModelPickGroup[] = []
    for (const [key, list] of Object.entries(prov)) {
      if (!Array.isArray(list) || !list.length) continue
      const models = list
        .map((m) => ({
          id: m.id,
          label: m.label && m.label !== m.id ? `${m.label} · ${m.id}` : m.id,
        }))
        .sort((a, b) => a.id.localeCompare(b.id))
      groups.push({
        provider: key,
        providerLabel: liveModelProviderLabel(key),
        models,
      })
    }
    groups.sort((a, b) => a.providerLabel.localeCompare(b.providerLabel))
    if (groups.length) {
      modelPickerGroups.value = groups
      return
    }
  } catch {
    /* catalog fallback */
  }
  const byProv = new Map<ModelProvider, ModelCatalogEntry[]>()
  for (const e of MODEL_CATALOG) {
    if (!byProv.has(e.provider)) byProv.set(e.provider, [])
    byProv.get(e.provider)!.push(e)
  }
  modelPickerGroups.value = [...byProv.entries()]
    .map(([p, entries]) => ({
      provider: p,
      providerLabel: liveModelProviderLabel(p),
      models: entries.map((e) => ({ id: e.id, label: `${e.label} (${e.id})` })),
    }))
    .sort((a, b) => a.providerLabel.localeCompare(b.providerLabel))
}

function canSendChatWithoutLocalLlm(ag: AgentConfig): boolean {
  const s = settingsStore.settings
  if (s.agentChatUseBackendRuntime === false) return false
  return !!(getAuthTokenOrPipelineKey() && resolveStreamAgentKey(ag))
}

function canUseChatCompletion(ag: AgentConfig | undefined): boolean {
  if (!ag) return false
  if (settingsStore.isConfigured()) return true
  return canSendChatWithoutLocalLlm(ag)
}

const agentProfile = computed(() => agentStore.getAgent(route.params.id as string))
const agent = computed(() => agentProfile.value ? agentStore.agentAsConfig(agentProfile.value) : undefined)

const agentProfileLink = computed(() => {
  const ag = agent.value
  if (!ag) return '/'
  return { path: `/agent/${ag.id}/profile`, query: { from: route.fullPath } }
})

const composerSkillsCatalog = ref<Skill[]>([])
const skillsPopoverLoading = ref(false)
const skillsPopoverError = ref('')
const skillSearchQuery = ref('')

const boundSkillIds = computed(() => {
  const rows = agentProfile.value?.skills
  if (!rows?.length) return []
  return rows.filter((x) => x.enabled !== false).map((x) => x.skill_id)
})

const filteredComposerSkills = computed(() => {
  const q = skillSearchQuery.value.trim().toLowerCase()
  const list = composerSkillsCatalog.value
  if (!q) return list
  return list.filter(
    (s) =>
      s.id.toLowerCase().includes(q) ||
      (s.name || '').toLowerCase().includes(q) ||
      (s.description || '').toLowerCase().includes(q) ||
      (s.category || '').toLowerCase().includes(q),
  )
})

async function onComposerSkillsPopoverOpen() {
  skillsPopoverError.value = ''
  skillsPopoverLoading.value = true
  try {
    composerSkillsCatalog.value = await fetchSkills({ includeDisabled: true })
  } catch (e) {
    skillsPopoverError.value = e instanceof Error ? e.message : String(e)
    composerSkillsCatalog.value = []
  } finally {
    skillsPopoverLoading.value = false
  }
}

function skillPickerLetter(s: Skill) {
  const base = (s.name && s.name.trim()) || s.id
  return base.charAt(0).toUpperCase()
}

function skillPickerColor(id: string) {
  let h = 0
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0
  return `hsl(${h % 360} 42% 42%)`
}

function insertSkillIntoInput(s: Skill) {
  if (!s.enabled) {
    ElMessage.warning(t('agentChat.skillDisabledHint'))
    return
  }
  const tag = `[skill:${s.id}]`
  const cur = inputText.value
  if (cur.trim() && !cur.endsWith('\n')) {
    inputText.value = `${cur}\n${tag}\n`
  } else {
    inputText.value = `${cur}${tag}\n`
  }
}

const perAgentModelSelect = computed({
  get: () => {
    const id = agent.value?.id
    if (!id) return ''
    return settingsStore.getPerAgentChatModel(id) ?? ''
  },
  set: (v: string) => {
    const id = agent.value?.id
    if (!id) return
    settingsStore.setPerAgentChatModel(id, v || null)
  },
})

const resolvedChatModelIdForAgent = computed(() =>
  agent.value
    ? settingsStore.resolveChatModelId(agent.value.id, agentProfile.value?.preferredModel)
    : '',
)

const resolvedChatModelDisplay = computed(() => {
  const id = resolvedChatModelIdForAgent.value
  if (!id) return '—'
  for (const g of modelPickerGroups.value) {
    const hit = g.models.find((m) => m.id === id)
    if (hit) return hit.label
  }
  return id
})

const chatModelShortLabel = computed(() => {
  const id = resolvedChatModelIdForAgent.value
  if (!id) return t('agentChat.modelAuto')
  const tail = id.split('/').pop() ?? id
  return tail.length > 28 ? `${tail.slice(0, 25)}…` : tail
})

function modelBrandMark(modelId: string): string {
  const s = modelId.toLowerCase()
  if (!s) return '◇'
  if (s.includes('deepseek')) return '🐋'
  if (s.includes('glm') || s.includes('zhipu') || s.includes('chatglm')) return 'G'
  if (s.includes('gpt') || s.includes('openai') || s.includes('o4') || s.includes('o3')) return '●'
  if (s.includes('claude') || s.includes('anthropic')) return 'A'
  if (s.includes('gemini') || s.includes('gemma') || s.includes('google')) return 'G'
  if (s.includes('qwen') || s.includes('dashscope')) return 'Q'
  if (s.includes('mistral')) return 'M'
  return '◇'
}

function onVoiceFill(text: string) {
  const snippet = text.trim()
  if (!snippet) return
  const cur = inputText.value.trim()
  inputText.value = cur ? `${cur}\n${snippet}` : snippet
}

const conversations = computed(() =>
  agent.value ? chatStore.getConversationsByAgent(agent.value.id) : [],
)

const filteredConversations = computed(() => {
  const list = conversations.value
  const q = convListFilter.value.trim().toLowerCase()
  if (!q) return list
  return list.filter((c) => {
    if (c.title.toLowerCase().includes(q)) return true
    return c.messages.some(
      (m) =>
        (m.role === 'user' || m.role === 'assistant') && m.content.toLowerCase().includes(q),
    )
  })
})

const activeConv = computed(() => chatStore.activeConversation)

const isThisConvGenerating = computed(
  () => !!activeConv.value && chatStore.isGeneratingFor(activeConv.value.id),
)

const visibleError = computed(() => {
  const err = requestError.value
  const conv = activeConv.value
  if (!err || !conv || err.conversationId !== conv.id) return null
  return err.message
})

const recommendedModelLabel = computed(() => pendingRecommendedModel.value || null)
const recommendedModelApplied = computed(() => pendingRecommendedApplied.value)
const showAgentRouterPanel = computed(() => agent.value?.id === 'Agent-orchestrator' && !activeConv.value)
const currentWorkflowDoc = computed(() => AgentWorkflowStore.currentStage?.deliveryDocName || '01-prd.md')
const latestAssistantMessage = computed(() => {
  const messages = activeConv.value?.messages ?? []
  return [...messages].reverse().find((m) => m.role === 'assistant') ?? null
})

const streamingMessage = computed<ChatMessageType>(() => {
  const conv = activeConv.value
  const chunk =
    conv && chatStore.streamingByConversation[conv.id]
      ? chatStore.streamingByConversation[conv.id]
      : ''
  return {
    id: 'streaming',
    role: 'assistant',
    content: chunk || t('agentChat.thinking'),
    timestamp: Date.now(),
    agentId: agent.value?.id ?? '',
  }
})

const useBackendRuntime = computed({
  get: () => settingsStore.settings.agentChatUseBackendRuntime !== false,
  set: (v: boolean) => {
    settingsStore.save({ ...settingsStore.settings, agentChatUseBackendRuntime: v })
  },
})

watch(
  () => ({
    agentId: route.params.id as string | undefined,
    convQuery: typeof route.query.c === 'string' ? route.query.c : undefined,
  }),
  ({ agentId, convQuery }) => {
    if (!agentId) return
    const convs = chatStore.getConversationsByAgent(agentId)
    if (convQuery && convs.some((c) => c.id === convQuery)) {
      chatStore.activeConversationId = convQuery
    } else {
      chatStore.activeConversationId = convs[0]?.id ?? null
    }
  },
  { immediate: true },
)

watch(
  () => ({
    agentId: route.params.id as string | undefined,
    seed: typeof route.query.seed === 'string' ? route.query.seed : '',
    autorun: route.query.autorun === '1',
    recommendedModel:
      typeof route.query.recommendedModel === 'string' ? route.query.recommendedModel : '',
    recommendedApplied: route.query.recommendedApplied === '1',
  }),
  async ({ agentId, seed, autorun, recommendedModel, recommendedApplied }) => {
    pendingRecommendedModel.value = recommendedModel
    pendingRecommendedApplied.value = recommendedApplied
    if (!agentId || !seed || !autorun) return
    const runKey = `${agentId}:${seed}`
    if (lastAutoRunKey.value === runKey) return
    lastAutoRunKey.value = runKey
    await launchSeedPrompt(seed)
  },
  { immediate: true },
)

watch(
  () => {
    const conv = activeConv.value
    return conv ? chatStore.streamingByConversation[conv.id] ?? '' : ''
  },
  () => scrollToBottom(),
)

watch(
  () => activeConv.value?.id,
  async () => {
    try {
      deliveryDocOptions.value = await listDeliveryDocs()
      deliveryTargetDoc.value = currentWorkflowDoc.value
    } catch {
      deliveryDocOptions.value = []
    }
  },
  { immediate: true },
)

watch(
  () => route.query.pipelineTask as string | undefined,
  async (taskId) => {
    if (!taskId) {
      pipelineTask.value = null
      return
    }
    try {
      pipelineTask.value = await fetchTask(taskId)
    } catch {
      pipelineTask.value = null
    }
  },
  { immediate: true },
)

watch(
  () => route.params.id,
  () => {
    void loadModelPickerGroups()
  },
  { immediate: true },
)

function scrollToBottom() {
  nextTick(() => {
    scrollAnchor.value?.scrollIntoView({ behavior: 'smooth' })
  })
}

async function startNewChat() {
  if (!agent.value) return
  try {
    await chatStore.createConversation(agent.value.id)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : t('agentChat.errCreateConversation'))
  }
}

async function launchSeedPrompt(seed: string) {
  const currentAgent = agent.value
  if (!currentAgent) return

  const promptText = seed.trim()
  if (!promptText) return

  if (!canUseChatCompletion(currentAgent)) {
    inputText.value = promptText
    await router.replace({ name: 'agent-chat', params: { id: currentAgent.id } })
    ElMessage.warning(t('agentChat.elMessage_1'))
    return
  }

  try {
    const conv = await chatStore.createConversation(currentAgent.id)
    chatStore.addMessage(conv.id, 'user', promptText, currentAgent.id)
    requestError.value = null
    scrollToBottom()
    await router.replace({
      name: 'agent-chat',
      params: { id: currentAgent.id },
      query: { c: conv.id },
    })
    await invokeModelCompletion(conv.id)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : t('agentChat.errStartWorkflow'))
  }
}

async function handleDelete(id: string) {
  await chatStore.deleteConversation(id)
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

function handleQuickPrompt(prompt: string) {
  inputText.value = prompt
  sendMessage()
}

function clearRequestError() {
  requestError.value = null
}

function refreshAgentSuggestions() {
  AgentSuggestions.value = inferAgentRoute(AgentRoutingTask.value)
}

function resetAgentRouting() {
  AgentRoutingTask.value = ''
  AgentSuggestions.value = getAgentDefaultRoutes()
}

async function openRouteAgent(routeItem: AgentRouteSuggestion) {
  const result = tryApplyRecommendedModel(routeItem.recommendedModel)
  if (result.reason) {
    if (result.applied) ElMessage.success(result.reason)
    else ElMessage.warning(result.reason)
  }

  const stageId = AgentWorkflowStore.currentStage?.id ?? AgentWorkflowStore.inferStageForAgent(routeItem.targetAgentId)
  if (stageId) {
    AgentWorkflowStore.handoffToAgent(
      routeItem.targetAgentId,
      t('agentChat.handoffOpenRole', { title: routeItem.title }),
    )
  }

  await router.push({
    path: `/agent/${routeItem.targetAgentId}`,
    query: {
      recommendedModel: routeItem.recommendedModel,
      recommendedApplied: result.applied ? '1' : '0',
    },
  })
}

async function handoffAgentRoute(routeItem: AgentRouteSuggestion) {
  const seed = buildAgentSeed(routeItem, AgentRoutingTask.value)
  const result = tryApplyRecommendedModel(routeItem.recommendedModel)
  if (result.reason) {
    if (result.applied) ElMessage.success(result.reason)
    else ElMessage.warning(result.reason)
  }

  const stageId = AgentWorkflowStore.currentStage?.id ?? AgentWorkflowStore.inferStageForAgent(routeItem.targetAgentId)
  if (stageId) {
    AgentWorkflowStore.handoffToAgent(
      routeItem.targetAgentId,
      t('agentChat.handoffOrchestrator', {
        title: routeItem.title,
        task: AgentRoutingTask.value.trim() || t('agentChat.taskUnset'),
      }),
    )
  }

  await router.push({
    path: `/agent/${routeItem.targetAgentId}`,
    query: {
      autorun: '1',
      seed,
      recommendedModel: routeItem.recommendedModel,
      recommendedApplied: result.applied ? '1' : '0',
    },
  })
}

async function writeLatestAssistantToDelivery() {
  if (!deliveryTargetDoc.value || !latestAssistantMessage.value) return
  try {
    const current = await readDeliveryDoc(deliveryTargetDoc.value)
    const nextContent = `${current.content.trim()}\n\n---\n\n${latestAssistantMessage.value.content.trim()}\n`
    await writeDeliveryDoc(deliveryTargetDoc.value, nextContent)
    ElMessage.success(t('agentChat.elMessage_writeDoc', { doc: deliveryTargetDoc.value }))
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : t('agentChat.errWriteDoc'))
  }
}

function openEditUser(msg: ChatMessageType) {
  if (!activeConv.value || msg.role !== 'user') return
  editingMessageId.value = msg.id
  editDraft.value = msg.content
  editDialogVisible.value = true
}

async function confirmEditUser() {
  const conv = activeConv.value
  const mid = editingMessageId.value
  if (!conv || !mid || !agent.value) return
  const text = editDraft.value.trim()
  if (!text) return
  if (!canUseChatCompletion(agent.value)) {
    ElMessage.warning(t('agentChat.elMessage_2'))
    return
  }
  if (chatStore.isGeneratingFor(conv.id)) return

  if (!chatStore.editUserMessageAndTruncate(conv.id, mid, text)) {
    ElMessage.error(t('agentChat.elMessage_3'))
    editDialogVisible.value = false
    return
  }
  editDialogVisible.value = false
  editingMessageId.value = null
  requestError.value = null
  scrollToBottom()
  await invokeModelCompletion(conv.id)
}

function stopGeneration() {
  const id = activeConv.value?.id
  if (!id) return
  conversationAbortControllers.get(id)?.abort()
}

function safeFilename(base: string) {
  return base.replace(/[/\\?%*:|"<>]/g, '-').trim().slice(0, 80) || 'conversation'
}

function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function exportMarkdown() {
  const conv = activeConv.value
  const ag = agent.value
  if (!conv || !ag) return
  let md = `# ${conv.title}\n\n`
  md += `- ${t('agentChat.mdAgentLabel')}: ${ag.name}\n- ${t('agentChat.mdTimeLabel')}: ${new Date().toLocaleString(appLocaleToBcp47(locale.value))}\n\n`
  if (conv.summary) {
    md += `${t('agentChat.mdSummaryHeading')}\n\n${conv.summary}\n\n---\n\n`
  }
  for (const m of conv.messages) {
    const who = m.role === 'user' ? t('agentChat.roleUser') : ag.name
    md += `## ${who}\n\n${m.content}\n\n`
  }
  downloadBlob(
    `${safeFilename(conv.title)}.md`,
    new Blob([md], { type: 'text/markdown;charset=utf-8' }),
  )
  ElMessage.success(t('agentChat.elMessage_4'))
}

function exportJson() {
  const conv = activeConv.value
  const ag = agent.value
  if (!conv || !ag) return
  const payload = {
    exportedAt: new Date().toISOString(),
    agent: { id: ag.id, name: ag.name },
    conversation: conv,
  }
  downloadBlob(
    `${safeFilename(conv.title)}.json`,
    new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' }),
  )
  ElMessage.success(t('agentChat.elMessage_5'))
}

async function generateConversationSummary() {
  if (!activeConv.value || !agent.value) return
  if (!settingsStore.isConfigured()) {
    ElMessage.warning(t('agentChat.elMessage_2'))
    return
  }
  const conv = activeConv.value
  if (conv.messages.length < 2) {
    ElMessage.warning(t('agentChat.elMessage_6'))
    return
  }
  if (summarizing.value || chatStore.isGeneratingFor(conv.id)) return
  summarizing.value = true
  try {
    let body = conv.messages
      .map((m) =>
        `${m.role === 'user' ? t('agentChat.roleUser') : t('agentChat.roleAssistant')}: ${m.content}`,
      )
      .join('\n\n')
    const max = 120_000
    if (body.length > max) body = body.slice(-max)
    const agId = agent.value.id
    const pref = agentStore.getAgent(agId)?.preferredModel
    const llmSettings = {
      ...settingsStore.settings,
      model: settingsStore.resolveChatModelId(agId, pref),
    }
    const summary = await chatCompletion(
      [
        { role: 'system', content: t('agentChat.summarizeSystemPrompt') },
        { role: 'user', content: `${t('agentChat.summarizeUserPrefix')}\n\n${body}` },
      ],
      llmSettings,
    )
    chatStore.setConversationSummary(conv.id, summary)
    ElMessage.success(t('agentChat.elMessage_7'))
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : String(e)
    ElMessage.error(t('agentChat.errSummary', { message }))
  } finally {
    summarizing.value = false
  }
}

async function invokeBackendRuntimeCompletion(
  convId: string,
  conv: Conversation,
  currentAgent: AgentConfig,
  streamKey: string,
  signal: AbortSignal,
) {
  const msgs = conv.messages
  const lastUser = msgs[msgs.length - 1]
  if (!lastUser || lastUser.role !== 'user') {
    throw new Error('no user message')
  }
  const prior = msgs.slice(0, -1)
  let taskBody: string
  if (prior.length) {
    const history = prior
      .map((m) => `${m.role === 'user' ? 'User' : 'Assistant'}: ${m.content}`)
      .join('\n\n')
    taskBody = `Prior conversation:\n\n${history}\n\n---\n\nCurrent message:\n${lastUser.content}`
  } else {
    taskBody = lastUser.content
  }

  const context: Record<string, string> = {}
  if (pipelineTask.value) {
    context.pipeline_task_id = pipelineTask.value.id
    context.current_stage = pipelineTask.value.currentStageId
  }

  const s = settingsStore.settings
  const pref = agentStore.getAgent(currentAgent.id)?.preferredModel
  const modelOverride = settingsStore.resolveChatModelId(currentAgent.id, pref)

  chatStore.setStreamChunk(convId, t('agentChat.streamBackendPrep'))

  const body: AgentRunRequest = {
    task: taskBody,
    max_steps: 8,
    temperature: s.temperature,
    ...(Object.keys(context).length ? { context } : {}),
    ...(modelOverride ? { model_override: modelOverride } : {}),
  }

  let toolLog = ''
  const stream = runAgentStream(streamKey, body, signal)
  for await (const evt of stream as AsyncIterable<AgentStreamEvent>) {
    if (evt.event === 'progress' && evt.phase === 'agent:tool-call') {
      const d = evt.data as { tool?: string; input?: unknown }
      const line = `${t('agentChat.streamToolCall')}: ${d.tool || '?'} ${JSON.stringify(d.input ?? '').slice(0, 200)}…`
      toolLog = toolLog ? `${toolLog}\n${line}` : line
      chatStore.setStreamChunk(
        convId,
        `${t('agentChat.streamBackendPrep')}${toolLog ? `\n\n${toolLog}` : ''}`,
      )
    } else if (evt.event === 'progress' && evt.phase === 'agent:execute-start') {
      chatStore.setStreamChunk(
        convId,
        `${t('agentChat.streamBackendPrep')}${toolLog ? `\n\n${toolLog}` : ''}\n\n${t('agentChat.thinking')}`,
      )
    } else if (evt.event === 'completed') {
      let out = evt.content || ''
      if (evt.error && !out) {
        out = String(evt.error)
      }
      if (evt.verification) {
        out += `\n\n---\n**Verification:**\n${evt.verification}`
      }
      if (evt.mcp_tools_loaded?.length) {
        out += `\n\n*MCP: ${evt.mcp_tools_loaded.join(', ')}*`
      }
      if (!evt.ok && evt.error) {
        const errStr = String(evt.error).trim()
        const bodyTrim = out.trim()
        if (bodyTrim && bodyTrim !== errStr) {
          out = `${out}\n\n[${evt.error}]`
        } else if (!bodyTrim) {
          out = String(evt.error)
        }
      }
      chatStore.setStreamChunk(convId, out.trim())
      chatStore.addMessage(convId, 'assistant', out.trim(), currentAgent.id)
      return
    } else if (evt.event === 'error') {
      throw new Error(evt.error)
    }
  }
  throw new Error('stream ended without completed event')
}

async function invokeModelCompletion(convId: string) {
  const currentAgent = agent.value
  if (!currentAgent) return
  const conv = chatStore.conversations.find((c) => c.id === convId)
  if (!conv) return

  const ac = new AbortController()
  conversationAbortControllers.set(convId, ac)
  chatStore.startGeneration(convId)

  const s = settingsStore.settings
  const streamKey = resolveStreamAgentKey(currentAgent)
  const authed = getAuthTokenOrPipelineKey()
  const shouldTryRuntime = s.agentChatUseBackendRuntime !== false && !!streamKey && !!authed

  try {
    if (shouldTryRuntime) {
      try {
        await invokeBackendRuntimeCompletion(convId, conv, currentAgent, streamKey, ac.signal)
        return
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : String(e)
        const is401 = message.includes('401') || message.includes('未认证')
        const aborted = e instanceof DOMException && e.name === 'AbortError'
        if (aborted) {
          ElMessage.info(t('agentChat.elMessage_8'))
          return
        }
        if (!is401) {
          requestError.value = { conversationId: convId, message }
          ElMessage.error(t('agentChat.errRequest', { message }))
          return
        }
        ElMessage.warning(t('agentChat.runtimeNoAuth'))
      }
    } else if (s.agentChatUseBackendRuntime !== false) {
      if (streamKey && !authed) {
        ElMessage.warning(t('agentChat.runtimeNoAuth'))
      } else if (!streamKey) {
        ElMessage.info(t('agentChat.runtimeNoMapping'))
      }
    }

    // --- Frontend fallback (demo/offline mode) ---
    // Per issue24.md: frontend light tools are allowed only as explicit fallback.
    const fallbackNotice = t('agentChat.fallbackNotice') || '⚠️ [Demo/Offline Mode] Backend runtime unavailable — using frontend light tools. Tool calls, MCP, and verification are disabled.'
    chatStore.setStreamChunk(convId, fallbackNotice + '\n\n')

    const systemPrompt = s.enableTools
      ? `${currentAgent.systemPrompt}\n\n${t('agentChat.toolsPromptSuffix')}`
      : currentAgent.systemPrompt
    const llmMessages = buildLLMMessages(systemPrompt, conv.messages, {
      maxMessages: s.contextMaxMessages,
      maxContextChars: s.contextMaxChars,
      memorySummary: conv.summary,
      pipelineTask: pipelineTask.value ?? undefined,
    })

    const agentPref = agentStore.getAgent(currentAgent.id)?.preferredModel
    const llmSettings = {
      ...settingsStore.settings,
      model: settingsStore.resolveChatModelId(currentAgent.id, agentPref),
    }

    let finalContent: string
    if (s.enableTools) {
      chatStore.setStreamChunk(convId, t('agentChat.streamPrepTools'))
      finalContent = await completionWithToolLoop(llmMessages, llmSettings, {
        signal: ac.signal,
        onStatus: (t) => chatStore.setStreamChunk(convId, t),
      })
    } else {
      finalContent = await chatCompletion(
        llmMessages,
        llmSettings,
        (text) => {
          chatStore.setStreamChunk(convId, text)
        },
        { signal: ac.signal },
      )
    }
    // Prefix fallback marker so UI clearly shows this was not backend runtime
    finalContent = `${fallbackNotice}\n\n---\n\n${finalContent}`
    chatStore.addMessage(convId, 'assistant', finalContent, currentAgent.id)
  } catch (e: unknown) {
    const aborted = e instanceof DOMException && e.name === 'AbortError'
    if (aborted) {
      ElMessage.info(t('agentChat.elMessage_8'))
    } else {
      const message = e instanceof Error ? e.message : String(e)
      requestError.value = { conversationId: convId, message }
      ElMessage.error(t('agentChat.errRequest', { message }))
    }
  } finally {
    conversationAbortControllers.delete(convId)
    chatStore.endGeneration(convId)
    scrollToBottom()
  }
}

async function regenerateLast() {
  if (!agent.value || !activeConv.value) return
  if (!canUseChatCompletion(agent.value)) {
    ElMessage.warning(t('agentChat.elMessage_2'))
    return
  }
  const conv = activeConv.value
  if (chatStore.isGeneratingFor(conv.id)) return
  if (!chatStore.removeLastAssistant(conv.id)) {
    ElMessage.info(t('agentChat.elMessage_9'))
    return
  }
  requestError.value = null
  scrollToBottom()
  await invokeModelCompletion(conv.id)
}

async function sendMessage() {
  if (!inputText.value.trim() || !agent.value) return

  if (!canUseChatCompletion(agent.value)) {
    ElMessage.warning(t('agentChat.elMessage_2'))
    return
  }

  const currentAgent = agent.value
  let conv = activeConv.value
  if (!conv) {
    try {
      conv = await chatStore.createConversation(currentAgent.id)
    } catch (e) {
      ElMessage.error(e instanceof Error ? e.message : t('agentChat.errCreateConversation'))
      return
    }
  }

  if (chatStore.isGeneratingFor(conv.id)) return

  const userText = inputText.value.trim()
  inputText.value = ''
  requestError.value = null
  chatStore.addMessage(conv.id, 'user', userText, currentAgent.id)
  scrollToBottom()

  await invokeModelCompletion(conv.id)
}
</script>

<style scoped>
.pipeline-context-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: rgba(99, 102, 241, 0.1);
  border-bottom: 1px solid rgba(99, 102, 241, 0.2);
  font-size: 13px;
  color: var(--text-secondary);
}

.pipeline-context-banner strong {
  color: var(--text-primary);
}

.pipeline-link {
  margin-left: auto;
  color: #6366f1;
  font-size: 12px;
  text-decoration: none;
}

.pipeline-link:hover {
  text-decoration: underline;
}

.chat-page {
  display: flex;
  height: 100vh;
}

/* Conversation sidebar */
.conv-sidebar {
  width: 240px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.conv-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  font-weight: 600;
  font-size: 15px;
  border-bottom: 1px solid var(--border-color);
}
.profile-link {
  margin-left: auto;
  color: var(--text-muted);
  transition: color 0.15s;
  display: flex;
  align-items: center;
}
.profile-link:hover {
  color: var(--accent);
}

.new-chat-btn {
  margin: 12px;
}

.conv-search {
  padding: 0 12px 8px;
}

.conv-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}

.conv-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  margin-bottom: 2px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 13px;
  transition: all 0.15s;
}

.conv-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.conv-item.active {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.conv-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-delete {
  opacity: 0;
  transition: opacity 0.15s;
  color: var(--text-muted);
}

.conv-item:hover .conv-delete {
  opacity: 1;
}

.conv-delete:hover {
  color: #e74c3c;
}

/* Chat area */
.chat-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.chat-toolbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  padding: 8px 24px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.recommended-model-tag {
  margin-right: 6px;
}

.delivery-target-select {
  width: 180px;
}

/* Welcome state */
.chat-welcome {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.welcome-icon {
  width: 96px;
  height: 96px;
  border-radius: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 20px;
}

.chat-welcome h2 {
  font-size: 24px;
  font-weight: 700;
  margin-bottom: 8px;
}

.welcome-desc {
  color: var(--text-secondary);
  font-size: 14px;
  margin-bottom: 16px;
  text-align: center;
  max-width: 500px;
}
.view-profile-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 20px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  font-size: 13px;
  text-decoration: none;
  margin-bottom: 28px;
  transition: all 0.2s;
}
.view-profile-btn:hover {
  color: var(--accent);
  border-color: var(--accent);
  background: var(--accent-bg, rgba(124, 92, 255, 0.08));
}

.quick-prompts {
  width: 100%;
  max-width: 700px;
}

.Agent-router-panel {
  margin: 24px auto 0;
  width: min(920px, calc(100% - 48px));
  padding: 20px;
  border-radius: 18px;
  border: 1px solid var(--border-color);
  background: var(--bg-card);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.18);
}

.Agent-router-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.Agent-router-header h3 {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.Agent-router-header p {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.7;
}

.Agent-router-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.Agent-suggestion-list {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}

.Agent-suggestion-card {
  padding: 14px;
  border-radius: 14px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
}

.Agent-suggestion-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.Agent-suggestion-stage {
  font-size: 12px;
  color: var(--accent);
  font-weight: 600;
  margin-bottom: 4px;
}

.Agent-suggestion-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.Agent-suggestion-agent {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.Agent-suggestion-reason {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.7;
}

.Agent-suggestion-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.quick-prompts h3 {
  font-size: 14px;
  color: var(--text-muted);
  margin-bottom: 12px;
  font-weight: 500;
}

.prompt-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.prompt-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 14px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
  transition: all 0.2s;
  line-height: 1.5;
}

.prompt-card:hover {
  background: var(--bg-hover);
  border-color: var(--accent);
  color: var(--text-primary);
}

.prompt-card .el-icon {
  margin-top: 2px;
  flex-shrink: 0;
}

/* Messages */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px 0;
}

/* Input area */
.chat-input-area {
  padding: 16px 24px 24px;
  border-top: 1px solid var(--border-color);
}

.chat-error-alert {
  max-width: 920px;
  margin: 0 auto 12px;
}

.composer-card {
  max-width: 920px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.composer-textarea :deep(.el-textarea__inner) {
  background: var(--bg-tertiary);
  border-color: var(--border-color);
  color: var(--text-primary);
  border-radius: 14px;
  padding: 12px 16px;
  font-size: 14px;
  resize: none;
}

.composer-textarea :deep(.el-textarea__inner:focus) {
  border-color: var(--accent);
}

.composer-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.composer-toolbar-spacer {
  flex: 1;
  min-width: 16px;
}

.toolbar-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 12px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  font-size: 13px;
  text-decoration: none;
  transition: border-color 0.15s, background 0.15s;
  max-width: min(260px, 42vw);
}

.toolbar-pill:hover {
  border-color: var(--accent);
  background: var(--bg-hover);
  color: var(--text-primary);
}

.composer-role-pill {
  flex-shrink: 0;
}

.composer-role-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  flex-shrink: 0;
}

.composer-role-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer-role-chevron {
  flex-shrink: 0;
  color: var(--text-muted);
}

.composer-model-pill {
  gap: 4px;
  padding-right: 4px;
}

.composer-model-brand {
  flex-shrink: 0;
  font-size: 14px;
  line-height: 1;
}

.composer-model-select {
  flex: 1;
  min-width: 96px;
  max-width: 200px;
}

.composer-model-select :deep(.el-select__wrapper) {
  padding: 0 6px;
  min-height: 30px;
  box-shadow: none;
  background: transparent;
  border: none;
}

.composer-model-select :deep(.el-select__caret) {
  color: var(--text-muted);
}

.composer-skills-pill .composer-skills-icon {
  font-size: 14px;
}

button.composer-skills-pill {
  font: inherit;
  cursor: pointer;
}

.composer-voice {
  flex-shrink: 0;
}

.composer-action-stop {
  flex-shrink: 0;
  height: 40px;
  border-radius: 12px !important;
  padding-left: 14px !important;
  padding-right: 14px !important;
}

.composer-send-btn {
  flex-shrink: 0;
  width: 40px !important;
  height: 40px !important;
}
</style>

<style>
/* Skills popover content is teleported — not under scoped root */
.agent-chat-skills-popover.el-popover.el-popper {
  padding: 0 !important;
}
.agent-chat-skills-popover .skills-popover-body {
  padding: 12px;
  max-height: 400px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-sizing: border-box;
}
.agent-chat-skills-popover .skills-bound-row {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.agent-chat-skills-popover .skills-bound-label {
  display: block;
  margin-bottom: 6px;
  font-weight: 600;
}
.agent-chat-skills-popover .skills-bound-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.agent-chat-skills-popover .skills-pop-msg {
  margin: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.agent-chat-skills-popover .skills-pop-error {
  color: var(--el-color-danger);
}
.agent-chat-skills-popover .skills-pop-list {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  max-height: 220px;
  border-top: 1px solid var(--el-border-color-lighter);
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.agent-chat-skills-popover .skills-pop-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 4px;
  cursor: pointer;
  border-radius: 8px;
}
.agent-chat-skills-popover .skills-pop-item:hover {
  background: var(--el-fill-color-light);
}
.agent-chat-skills-popover .skills-pop-item.is-disabled {
  opacity: 0.55;
}
.agent-chat-skills-popover .skills-pop-item.is-disabled:hover {
  background: transparent;
}
.agent-chat-skills-popover .skills-pop-letter {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
}
.agent-chat-skills-popover .skills-pop-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  line-height: 1.3;
}
.agent-chat-skills-popover .skills-pop-desc {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.agent-chat-skills-popover .skills-pop-footer-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--el-color-primary);
  text-decoration: none;
}
.agent-chat-skills-popover .skills-pop-footer-link:hover {
  text-decoration: underline;
}
</style>
