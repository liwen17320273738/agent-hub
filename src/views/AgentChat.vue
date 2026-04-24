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
        <router-link :to="`/agent/${agent.id}/profile`" class="profile-link" :title="t('agentChat.title_1')">
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
      <div v-if="!activeConv && !showWayneRouterPanel" class="chat-welcome">
        <div class="welcome-icon" :style="{ background: agent.color + '20', color: agent.color }">
          <el-icon :size="48"><component :is="resolveAgentIcon(agent.icon)" /></el-icon>
        </div>
        <h2>{{ agent.name }} · {{ agent.title }}</h2>
        <p class="welcome-desc">{{ agent.description }}</p>
        <router-link :to="`/agent/${agent.id}/profile`" class="view-profile-btn">
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

      <div v-else-if="showWayneRouterPanel" class="wayne-router-panel">
        <div class="wayne-router-header">
          <div>
            <h3>{{ t('agentChat.text_5') }}</h3>
            <p>{{ t('agentChat.text_6') }}</p>
          </div>
          <el-tag type="warning" effect="plain">Orchestrator</el-tag>
        </div>

        <el-input
          v-model="wayneRoutingTask"
          type="textarea"
          :rows="3"
          :placeholder="t('agentChat.placeholder_3')"
        />

        <div class="wayne-router-actions">
          <el-button type="primary" @click="refreshWayneSuggestions">{{ t('agentChat.text_7') }}</el-button>
          <el-button text @click="resetWayneRouting">{{ t('agentChat.text_8') }}</el-button>
        </div>

        <div class="wayne-suggestion-list">
          <div
            v-for="routeItem in wayneSuggestions"
            :key="routeItem.id"
            class="wayne-suggestion-card"
          >
            <div class="wayne-suggestion-top">
              <div>
                <div class="wayne-suggestion-stage">{{ routeItem.stage }}</div>
                <div class="wayne-suggestion-title">{{ routeItem.title }}</div>
              </div>
              <el-tag size="small" type="info" effect="plain">{{ routeItem.recommendedModel }}</el-tag>
            </div>
            <div class="wayne-suggestion-agent">{{ routeItem.targetAgentName }}</div>
            <p class="wayne-suggestion-reason">{{ routeItem.reason }}</p>
            <div class="wayne-suggestion-actions">
              <el-button size="small" type="primary" @click="handoffWayneRoute(routeItem)">
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
        <div class="input-wrapper">
          <el-input
            v-model="inputText"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 6 }"
            :placeholder="t('agentChat.placeholder_4')"
            @keydown="handleKeydown"
            :disabled="isThisConvGenerating"
          />
          <el-button
            v-if="isThisConvGenerating"
            class="stop-btn"
            type="danger"
            plain
            @click="stopGeneration"
          >
            {{ t('agentChat.stop') }}
          </el-button>
          <el-button
            class="send-btn"
            type="primary"
            :icon="isThisConvGenerating ? Loading : Promotion"
            circle
            :disabled="!inputText.trim() || isThisConvGenerating"
            @click="sendMessage"
          />
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
import { Connection, Promotion, Loading } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAgentStore } from '@/stores/agents'
import { useChatStore } from '@/stores/chat'
import { useSettingsStore } from '@/stores/settings'
import { useWayneWorkflowStore } from '@/stores/wayneWorkflow'
import { chatCompletion } from '@/services/llm'
import { completionWithToolLoop } from '@/services/chatWithTools'
import { buildLLMMessages } from '@/services/messageContext'
import { fetchTask } from '@/services/pipelineApi'
import type { ChatMessage as ChatMessageType, PipelineTask } from '@/agents/types'
import ChatMessage from '@/components/ChatMessage.vue'
import { listDeliveryDocs, readDeliveryDoc, writeDeliveryDoc, type DeliveryDocMeta } from '@/services/deliveryDocs'
import {
  buildWayneSeed,
  getWayneDefaultRoutes,
  inferWayneRoute,
  tryApplyRecommendedModel,
  type WayneRouteSuggestion,
} from '@/services/wayneRouting'
import { resolveAgentIcon } from '@/utils/agentIcon'
import { useI18n } from 'vue-i18n'
import { appLocaleToBcp47 } from '@/i18n'

const { t, locale } = useI18n()

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const chatStore = useChatStore()
const settingsStore = useSettingsStore()
const wayneWorkflowStore = useWayneWorkflowStore()

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
const wayneRoutingTask = ref('')
const wayneSuggestions = ref<WayneRouteSuggestion[]>(getWayneDefaultRoutes())
const deliveryDocOptions = ref<DeliveryDocMeta[]>([])
const deliveryTargetDoc = ref('01-prd.md')
const pipelineTask = ref<PipelineTask | null>(null)

const agentProfile = computed(() => agentStore.getAgent(route.params.id as string))
const agent = computed(() => agentProfile.value ? agentStore.agentAsConfig(agentProfile.value) : undefined)

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
const showWayneRouterPanel = computed(() => agent.value?.id === 'wayne-orchestrator' && !activeConv.value)
const currentWorkflowDoc = computed(() => wayneWorkflowStore.currentStage?.deliveryDocName || '01-prd.md')
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

  if (!settingsStore.isConfigured()) {
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

function refreshWayneSuggestions() {
  wayneSuggestions.value = inferWayneRoute(wayneRoutingTask.value)
}

function resetWayneRouting() {
  wayneRoutingTask.value = ''
  wayneSuggestions.value = getWayneDefaultRoutes()
}

async function openRouteAgent(routeItem: WayneRouteSuggestion) {
  const result = tryApplyRecommendedModel(routeItem.recommendedModel)
  if (result.reason) {
    if (result.applied) ElMessage.success(result.reason)
    else ElMessage.warning(result.reason)
  }

  const stageId = wayneWorkflowStore.currentStage?.id ?? wayneWorkflowStore.inferStageForAgent(routeItem.targetAgentId)
  if (stageId) {
    wayneWorkflowStore.handoffToAgent(
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

async function handoffWayneRoute(routeItem: WayneRouteSuggestion) {
  const seed = buildWayneSeed(routeItem, wayneRoutingTask.value)
  const result = tryApplyRecommendedModel(routeItem.recommendedModel)
  if (result.reason) {
    if (result.applied) ElMessage.success(result.reason)
    else ElMessage.warning(result.reason)
  }

  const stageId = wayneWorkflowStore.currentStage?.id ?? wayneWorkflowStore.inferStageForAgent(routeItem.targetAgentId)
  if (stageId) {
    wayneWorkflowStore.handoffToAgent(
      routeItem.targetAgentId,
      t('agentChat.handoffOrchestrator', {
        title: routeItem.title,
        task: wayneRoutingTask.value.trim() || t('agentChat.taskUnset'),
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
  if (!settingsStore.isConfigured()) {
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
    const summary = await chatCompletion(
      [
        { role: 'system', content: t('agentChat.summarizeSystemPrompt') },
        { role: 'user', content: `${t('agentChat.summarizeUserPrefix')}\n\n${body}` },
      ],
      settingsStore.settings,
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

async function invokeModelCompletion(convId: string) {
  const currentAgent = agent.value
  if (!currentAgent) return
  const conv = chatStore.conversations.find((c) => c.id === convId)
  if (!conv) return

  const ac = new AbortController()
  conversationAbortControllers.set(convId, ac)
  chatStore.startGeneration(convId)

  try {
    const s = settingsStore.settings
    const systemPrompt = s.enableTools
      ? `${currentAgent.systemPrompt}\n\n${t('agentChat.toolsPromptSuffix')}`
      : currentAgent.systemPrompt
    const llmMessages = buildLLMMessages(systemPrompt, conv.messages, {
      maxMessages: s.contextMaxMessages,
      maxContextChars: s.contextMaxChars,
      memorySummary: conv.summary,
      pipelineTask: pipelineTask.value ?? undefined,
    })

    let finalContent: string
    if (s.enableTools) {
      chatStore.setStreamChunk(convId, t('agentChat.streamPrepTools'))
      finalContent = await completionWithToolLoop(llmMessages, s, {
        signal: ac.signal,
        onStatus: (t) => chatStore.setStreamChunk(convId, t),
      })
    } else {
      finalContent = await chatCompletion(
        llmMessages,
        s,
        (text) => {
          chatStore.setStreamChunk(convId, text)
        },
        { signal: ac.signal },
      )
    }
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
  if (!settingsStore.isConfigured()) {
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

  if (!settingsStore.isConfigured()) {
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

.wayne-router-panel {
  margin: 24px auto 0;
  width: min(920px, calc(100% - 48px));
  padding: 20px;
  border-radius: 18px;
  border: 1px solid var(--border-color);
  background: var(--bg-card);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.18);
}

.wayne-router-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.wayne-router-header h3 {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.wayne-router-header p {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.7;
}

.wayne-router-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.wayne-suggestion-list {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}

.wayne-suggestion-card {
  padding: 14px;
  border-radius: 14px;
  border: 1px solid var(--border-color);
  background: var(--bg-tertiary);
}

.wayne-suggestion-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.wayne-suggestion-stage {
  font-size: 12px;
  color: var(--accent);
  font-weight: 600;
  margin-bottom: 4px;
}

.wayne-suggestion-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.wayne-suggestion-agent {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.wayne-suggestion-reason {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.7;
}

.wayne-suggestion-actions {
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
  max-width: 800px;
  margin: 0 auto 12px;
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  max-width: 800px;
  margin: 0 auto;
}

.input-wrapper :deep(.el-textarea__inner) {
  background: var(--bg-tertiary);
  border-color: var(--border-color);
  color: var(--text-primary);
  border-radius: 12px;
  padding: 12px 16px;
  font-size: 14px;
  resize: none;
}

.input-wrapper :deep(.el-textarea__inner:focus) {
  border-color: var(--accent);
}

.stop-btn {
  flex-shrink: 0;
  height: 40px;
}

.send-btn {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
}
</style>
