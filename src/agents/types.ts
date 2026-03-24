export interface AgentConfig {
  id: string
  name: string
  title: string
  icon: string
  color: string
  description: string
  systemPrompt: string
  quickPrompts: string[]
  category: 'core' | 'support'
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  agentId: string
}

export interface Conversation {
  id: string
  agentId: string
  title: string
  messages: ChatMessage[]
  createdAt: number
  updatedAt: number
  /** 用户触发生成的早前对话摘要，会并入系统侧上下文 */
  summary?: string
}

export interface ConversationSearchHit {
  conversationId: string
  agentId: string
  title: string
  snippet: string
}
