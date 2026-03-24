import type { ChatMessage } from '@/agents/types'
import type { LLMMessage } from './llm'

/** 控制成本与上下文上限：条数 + 字符预算（中文约 2–3 字/token，留余量） */
const DEFAULT_MAX_MESSAGES = 32
const DEFAULT_MAX_CONTEXT_CHARS = 48000

/**
 * 从完整对话历史构造发给模型的 messages：保留末尾若干轮，避免超长与费用失控。
 */
export function buildLLMMessages(
  systemPrompt: string,
  history: ChatMessage[],
  options?: {
    maxMessages?: number
    maxContextChars?: number
    /** 会话级摘要，补充被滑动窗口裁掉的早前信息 */
    memorySummary?: string
  },
): LLMMessage[] {
  const maxMessages = options?.maxMessages ?? DEFAULT_MAX_MESSAGES
  const maxChars = options?.maxContextChars ?? DEFAULT_MAX_CONTEXT_CHARS

  const relevant = history.filter((m) => m.role === 'user' || m.role === 'assistant')
  let slice = relevant
  let dropped = false

  if (slice.length > maxMessages) {
    slice = slice.slice(-maxMessages)
    dropped = true
  }

  let total = slice.reduce((s, m) => s + m.content.length, 0)
  while (slice.length > 1 && total > maxChars) {
    slice = slice.slice(1)
    dropped = true
    total = slice.reduce((s, m) => s + m.content.length, 0)
  }

  while (slice.length > 0 && slice[0].role === 'assistant') {
    slice = slice.slice(1)
    dropped = true
  }

  let systemContent = systemPrompt
  const sum = options?.memorySummary?.trim()
  if (sum) {
    systemContent += `\n\n【早前对话摘要（仅供参考，勿编造细节）】\n${sum}`
  }
  if (dropped) {
    systemContent +=
      '\n\n（内部说明：因长度限制，更早的多轮对话未包含在本次请求中。请勿编造未出现的用户原话；若需历史细节请让用户补充。）'
  }

  return [
    { role: 'system', content: systemContent },
    ...slice.map((m) => ({
      role: m.role as 'user' | 'assistant',
      content: m.content,
    })),
  ]
}
