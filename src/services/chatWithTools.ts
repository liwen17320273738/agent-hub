import type { ApiChatMessage, LLMMessage, LLMSettings } from './llm'
import { chatCompletionApiMessage } from './llm'
import { TOOL_DEFINITIONS, executeTool } from './tools'

export function llmMessagesToApi(msgs: LLMMessage[]): ApiChatMessage[] {
  return msgs.map((m) => {
    if (m.role === 'system') return { role: 'system', content: m.content }
    if (m.role === 'user') return { role: 'user', content: m.content }
    return { role: 'assistant', content: m.content }
  })
}

const MAX_TOOL_STEPS = 8

/**
 * 在同一轮用户发送后，循环请求 API 直至得到最终文本（中间可执行多步 tool）。
 * 不使用流式，适合 OpenAI 兼容的 tools 接口。
 */
export async function completionWithToolLoop(
  seed: LLMMessage[],
  settings: LLMSettings,
  options?: {
    signal?: AbortSignal
    onStatus?: (text: string) => void
  },
): Promise<string> {
  const messages: ApiChatMessage[] = llmMessagesToApi(seed)

  for (let step = 0; step < MAX_TOOL_STEPS; step++) {
    if (options?.signal?.aborted) throw new DOMException('Aborted', 'AbortError')

    const msg = await chatCompletionApiMessage(messages, settings, {
      signal: options?.signal,
      tools: TOOL_DEFINITIONS,
    })

    if (msg.tool_calls?.length) {
      messages.push({
        role: 'assistant',
        content: msg.content,
        tool_calls: msg.tool_calls,
      })
      for (const tc of msg.tool_calls) {
        const name = tc.function?.name ?? ''
        const rawArgs = tc.function?.arguments
        const argStr =
          typeof rawArgs === 'string' ? rawArgs : JSON.stringify(rawArgs ?? {})
        options?.onStatus?.(`调用工具: ${name}…`)
        const out = executeTool(name, argStr)
        messages.push({
          role: 'tool',
          tool_call_id: tc.id,
          content: out,
        })
      }
      continue
    }

    return msg.content ?? ''
  }

  throw new Error('工具调用次数过多，已中止')
}
