import { defineStore } from 'pinia'
import { ref, computed, reactive } from 'vue'
import type { ChatMessage, Conversation, ConversationSearchHit } from '@/agents/types'

const STORAGE_KEY = 'agent-hub-conversations'

export const useChatStore = defineStore('chat', () => {
  const conversations = ref<Conversation[]>(loadConversations())
  const activeConversationId = ref<string | null>(null)

  /** 按会话隔离流式状态，避免多对话并发时互相覆盖 */
  const generatingFlags = reactive<Record<string, boolean>>({})
  const streamingByConversation = reactive<Record<string, string>>({})

  function loadConversations(): Conversation[] {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) return JSON.parse(raw)
    } catch { /* ignore */ }
    return []
  }

  function persist() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations.value))
  }

  const activeConversation = computed(() =>
    conversations.value.find((c) => c.id === activeConversationId.value),
  )

  function getConversationsByAgent(agentId: string) {
    return conversations.value
      .filter((c) => c.agentId === agentId)
      .sort((a, b) => b.updatedAt - a.updatedAt)
  }

  function createConversation(agentId: string, title?: string): Conversation {
    const conv: Conversation = {
      id: crypto.randomUUID(),
      agentId,
      title: title || '新对话',
      messages: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
    }
    conversations.value.unshift(conv)
    activeConversationId.value = conv.id
    persist()
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

    persist()
    return msg
  }

  function removeLastAssistant(conversationId: string): boolean {
    const conv = conversations.value.find((c) => c.id === conversationId)
    if (!conv || conv.messages.length === 0) return false
    const last = conv.messages[conv.messages.length - 1]
    if (last.role !== 'assistant') return false
    conv.messages.pop()
    conv.updatedAt = Date.now()
    persist()
    return true
  }

  function setConversationSummary(conversationId: string, summary: string) {
    const conv = conversations.value.find((c) => c.id === conversationId)
    if (!conv) return
    conv.summary = summary.trim() || undefined
    conv.updatedAt = Date.now()
    persist()
  }

  /** 修改某条用户消息，并删除其后的所有消息（用于编辑后重发） */
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
    persist()
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

  function deleteConversation(id: string) {
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (activeConversationId.value === id) {
      activeConversationId.value = null
    }
    persist()
  }

  function clearAgentConversations(agentId: string) {
    conversations.value = conversations.value.filter((c) => c.agentId !== agentId)
    activeConversationId.value = null
    persist()
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

  return {
    conversations,
    activeConversationId,
    activeConversation,
    /** 供模板/计算属性订阅流式片段（按会话 id） */
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
  }
})
