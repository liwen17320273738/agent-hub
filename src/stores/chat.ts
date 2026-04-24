import { defineStore } from 'pinia'
import { useI18n } from 'vue-i18n'
import { ref, computed, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import type { ChatMessage, Conversation, ConversationSearchHit } from '@/agents/types'
import { apiUrl, isEnterpriseBuild } from '@/services/enterpriseApi'
import { useAuthStore } from '@/stores/auth'

const STORAGE_KEY = 'agent-hub-conversations'

function loadLocalConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw)
  } catch {
    /* ignore */
  }
  return []
}

export const useChatStore = defineStore('chat', () => {
  const { t } = useI18n()
  const conversations = ref<Conversation[]>(isEnterpriseBuild ? [] : loadLocalConversations())
  const activeConversationId = ref<string | null>(null)

  const generatingFlags = reactive<Record<string, boolean>>({})
  const streamingByConversation = reactive<Record<string, string>>({})

  /** 企业模式下按会话串行 PATCH，避免乱序覆盖 */
  const remoteSyncTail = new Map<string, Promise<void>>()

  function isRemoteMode(): boolean {
    return isEnterpriseBuild && useAuthStore().isLoggedIn
  }

  function persistLocal() {
    if (isRemoteMode()) return
    localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations.value))
  }

  async function pushConversationToServer(conversationId: string): Promise<void> {
    const conv = conversations.value.find((c) => c.id === conversationId)
    if (!conv) return
    const expectedRevision = typeof conv.revision === 'number' && Number.isInteger(conv.revision) ? conv.revision : 0
    const r = await fetch(apiUrl(`/conversations/${conversationId}`), {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: conv.title,
        summary: conv.summary ?? null,
        messages: conv.messages,
        updatedAt: conv.updatedAt,
        expectedRevision,
      }),
    })
    if (r.status === 409) {
      remoteSyncTail.delete(conversationId)
      await loadRemoteConversations()
      ElMessage.warning(t('chat.elMessage_1'))
      return
    }
    if (!r.ok) {
      const t = await r.text()
      throw new Error(t || `HTTP ${r.status}`)
    }
    const data = (await r.json()) as Conversation
    const idx = conversations.value.findIndex((c) => c.id === conversationId)
    if (idx >= 0) {
      conversations.value[idx].revision = data.revision
      conversations.value[idx].updatedAt = data.updatedAt
    }
  }

  function chainRemoteSync(conversationId: string) {
    if (!isRemoteMode()) return
    const tail = remoteSyncTail.get(conversationId) ?? Promise.resolve()
    const next = tail
      .then(() => pushConversationToServer(conversationId))
      .catch((e) => console.error('[agent-hub] 会话同步失败', e))
    remoteSyncTail.set(conversationId, next)
  }

  async function loadRemoteConversations(): Promise<void> {
    if (!isEnterpriseBuild || !useAuthStore().isLoggedIn) return
    const r = await fetch(apiUrl('/conversations'), { credentials: 'include' })
    if (!r.ok) return
    conversations.value = (await r.json()) as Conversation[]
  }

  function resetConversationsForEnterpriseLogout(): void {
    remoteSyncTail.clear()
    conversations.value = []
    activeConversationId.value = null
  }

  const activeConversation = computed(() =>
    conversations.value.find((c) => c.id === activeConversationId.value),
  )

  function getConversationsByAgent(agentId: string) {
    return conversations.value
      .filter((c) => c.agentId === agentId)
      .sort((a, b) => b.updatedAt - a.updatedAt)
  }

  async function createConversation(agentId: string, title?: string): Promise<Conversation> {
    if (isRemoteMode()) {
      const r = await fetch(apiUrl('/conversations'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agentId, title: title || '新对话' }),
      })
      if (!r.ok) {
        const err = await r.text()
        throw new Error(err || '创建会话失败')
      }
      const conv = (await r.json()) as Conversation
      conversations.value.unshift(conv)
      activeConversationId.value = conv.id
      return conv
    }

    const conv: Conversation = {
      id: crypto.randomUUID(),
      agentId,
      title: title || '新对话',
      messages: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
      revision: 0,
    }
    conversations.value.unshift(conv)
    activeConversationId.value = conv.id
    persistLocal()
    return conv
  }

  function addMessage(conversationId: string, role: 'user' | 'assistant', content: string, agentId: string) {
    const conv = conversations.value.find((c) => c.id === conversationId)
    if (!conv) return

    const msg: ChatMessage = {
      id: crypto.randomUUID(),
      role,
      content,
      timestamp: Date.now(),
      agentId,
    }
    conv.messages.push(msg)
    conv.updatedAt = Date.now()

    if (conv.messages.length === 1 && role === 'user') {
      conv.title = content.slice(0, 30) + (content.length > 30 ? '...' : '')
    }

    persistLocal()
    chainRemoteSync(conversationId)
    return msg
  }

  function removeLastAssistant(conversationId: string): boolean {
    const conv = conversations.value.find((c) => c.id === conversationId)
    if (!conv || conv.messages.length === 0) return false
    const last = conv.messages[conv.messages.length - 1]
    if (last.role !== 'assistant') return false
    conv.messages.pop()
    conv.updatedAt = Date.now()
    persistLocal()
    chainRemoteSync(conversationId)
    return true
  }

  function setConversationSummary(conversationId: string, summary: string) {
    const conv = conversations.value.find((c) => c.id === conversationId)
    if (!conv) return
    conv.summary = summary.trim() || undefined
    conv.updatedAt = Date.now()
    persistLocal()
    chainRemoteSync(conversationId)
  }

  function editUserMessageAndTruncate(conversationId: string, messageId: string, newContent: string): boolean {
    const conv = conversations.value.find((c) => c.id === conversationId)
    if (!conv) return false
    const idx = conv.messages.findIndex((m) => m.id === messageId)
    if (idx < 0) return false
    const target = conv.messages[idx]
    if (target.role !== 'user') return false
    target.content = newContent
    target.timestamp = Date.now()
    conv.messages.splice(idx + 1)
    conv.updatedAt = Date.now()
    if (idx === 0) {
      conv.title = newContent.slice(0, 30) + (newContent.length > 30 ? '...' : '')
    }
    persistLocal()
    chainRemoteSync(conversationId)
    return true
  }

  function searchConversations(query: string, limit = 25): ConversationSearchHit[] {
    const q = query.trim().toLowerCase()
    if (!q) return []
    const hits: ConversationSearchHit[] = []
    for (const c of conversations.value) {
      if (c.title.toLowerCase().includes(q)) {
        hits.push({
          conversationId: c.id,
          agentId: c.agentId,
          title: c.title,
          snippet: '匹配：会话标题',
        })
        if (hits.length >= limit) return hits
        continue
      }
      for (const m of c.messages) {
        if (m.role !== 'user' && m.role !== 'assistant') continue
        const lc = m.content.toLowerCase()
        const idx = lc.indexOf(q)
        if (idx >= 0) {
          const start = Math.max(0, idx - 24)
          const end = Math.min(m.content.length, start + 72)
          hits.push({
            conversationId: c.id,
            agentId: c.agentId,
            title: c.title,
            snippet:
              (start > 0 ? '…' : '') + m.content.slice(start, end) + (end < m.content.length ? '…' : ''),
          })
          break
        }
      }
      if (hits.length >= limit) return hits
    }
    return hits
  }

  async function deleteConversation(id: string): Promise<void> {
    if (isRemoteMode()) {
      try {
        const r = await fetch(apiUrl(`/conversations/${id}`), {
          method: 'DELETE',
          credentials: 'include',
        })
        if (!r.ok) console.error('[agent-hub] 删除会话失败', await r.text())
      } catch (e) {
        console.error('[agent-hub] 删除会话失败', e)
      }
    }
    remoteSyncTail.delete(id)
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (activeConversationId.value === id) {
      activeConversationId.value = null
    }
    persistLocal()
  }

  async function clearAgentConversations(agentId: string): Promise<void> {
    const toRemove = conversations.value.filter((c) => c.agentId === agentId)
    for (const c of toRemove) {
      await deleteConversation(c.id)
    }
    activeConversationId.value = null
  }

  function isGeneratingFor(conversationId: string) {
    return !!generatingFlags[conversationId]
  }

  function startGeneration(conversationId: string) {
    generatingFlags[conversationId] = true
    streamingByConversation[conversationId] = ''
  }

  function setStreamChunk(conversationId: string, text: string) {
    streamingByConversation[conversationId] = text
  }

  function endGeneration(conversationId: string) {
    delete generatingFlags[conversationId]
    delete streamingByConversation[conversationId]
  }

  function persist() {
    persistLocal()
  }

  return {
    conversations,
    activeConversationId,
    activeConversation,
    streamingByConversation,
    isGeneratingFor,
    startGeneration,
    setStreamChunk,
    endGeneration,
    getConversationsByAgent,
    createConversation,
    addMessage,
    removeLastAssistant,
    setConversationSummary,
    editUserMessageAndTruncate,
    searchConversations,
    deleteConversation,
    clearAgentConversations,
    persist,
    loadRemoteConversations,
    resetConversationsForEnterpriseLogout,
  }
})
