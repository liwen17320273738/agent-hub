import type { ToolCall } from './tools'

export interface LLMSettings {
  apiUrl: string
  apiKey: string
  model: string
  temperature: number
  maxTokens: number
  /** 单次请求最多携带的用户/助手消息条数（滑动窗口） */
  contextMaxMessages: number
  /** 单次请求中用户/助手消息总字符上限（粗略控费） */
  contextMaxChars: number
  /**
   * 启用 OpenAI 格式 function calling（多轮 tool 在单次回复内完成，无流式）。
   * 部分兼容接口不支持 tools，失败时可关闭此项。
   */
  enableTools: boolean
}

export const defaultSettings: LLMSettings = {
  apiUrl: 'https://api.deepseek.com/v1/chat/completions',
  apiKey: '',
  model: 'deepseek-chat',
  temperature: 0.7,
  maxTokens: 4096,
  contextMaxMessages: 32,
  contextMaxChars: 48000,
  enableTools: false,
}

export interface LLMMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
}

/** 发往 API 的消息（含 tool 角色与 assistant 的 tool_calls） */
export type ApiChatMessage =
  | { role: 'system'; content: string }
  | { role: 'user'; content: string }
  | { role: 'assistant'; content?: string | null; tool_calls?: ToolCall[] }
  | { role: 'tool'; tool_call_id: string; content: string }

/**
 * 通过同源相对路径走 Vite dev/preview 或部署时的反向代理，避免浏览器 CORS，
 * 并在配置 `VITE_USE_RELATIVE_PROXY=true` 时让生产构建也走代理（需 Nginx 等配置相同路径）。
 */
function useRelativeApiProxy(): boolean {
  return import.meta.env.DEV || import.meta.env.VITE_USE_RELATIVE_PROXY === 'true'
}

function resolveApiUrl(apiUrl: string): string {
  if (!useRelativeApiProxy()) return apiUrl
  if (apiUrl.includes('dashscope.aliyuncs.com'))
    return apiUrl.replace('https://dashscope.aliyuncs.com/compatible-mode/v1', '/api/proxy/dashscope')
  if (apiUrl.includes('api.deepseek.com'))
    return apiUrl.replace('https://api.deepseek.com/v1', '/api/proxy/deepseek')
  if (apiUrl.includes('api.openai.com'))
    return apiUrl.replace('https://api.openai.com/v1', '/api/proxy/openai')
  return apiUrl
}

export interface ChatCompletionOptions {
  signal?: AbortSignal
}

export interface ChatCompletionApiOptions extends ChatCompletionOptions {
  tools?: unknown[]
}

/** 非流式单次补全，返回 assistant 消息（可含 tool_calls） */
export async function chatCompletionApiMessage(
  messages: ApiChatMessage[],
  settings: LLMSettings,
  options?: ChatCompletionApiOptions,
): Promise<{ content: string | null; tool_calls?: ToolCall[] }> {
  const url = resolveApiUrl(settings.apiUrl)
  const body: Record<string, unknown> = {
    model: settings.model,
    messages,
    temperature: settings.temperature,
    max_tokens: Math.min(settings.maxTokens, 16384),
    stream: false,
  }
  if (options?.tools?.length) {
    body.tools = options.tools
    body.tool_choice = 'auto'
  }

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${settings.apiKey}`,
    },
    body: JSON.stringify(body),
    signal: options?.signal,
  })

  if (!response.ok) {
    const err = await response.text()
    throw new Error(`API 请求失败 (${response.status}): ${err}`)
  }

  const data = (await response.json()) as {
    choices?: Array<{ message?: { content?: string | null; tool_calls?: ToolCall[] } }>
  }
  const msg = data.choices?.[0]?.message
  return {
    content: msg?.content ?? null,
    tool_calls: msg?.tool_calls,
  }
}

export async function chatCompletion(
  messages: LLMMessage[],
  settings: LLMSettings,
  onChunk?: (text: string) => void,
  options?: ChatCompletionOptions,
): Promise<string> {
  const url = resolveApiUrl(settings.apiUrl)
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${settings.apiKey}`,
    },
    body: JSON.stringify({
      model: settings.model,
      messages,
      temperature: settings.temperature,
      max_tokens: Math.min(settings.maxTokens, 16384),
      stream: !!onChunk,
    }),
    signal: options?.signal,
  })

  if (!response.ok) {
    const err = await response.text()
    throw new Error(`API 请求失败 (${response.status}): ${err}`)
  }

  if (onChunk) {
    return streamResponse(response, onChunk, options?.signal)
  }

  const data = await response.json()
  return data.choices?.[0]?.message?.content ?? ''
}

export interface CompletionUsage {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
}

export interface CompletionOnceResult {
  content: string
  latencyMs: number
  usage?: CompletionUsage
  error?: string
}

/** 非流式单次补全，用于延迟与 token 统计（模型对比等） */
export async function chatCompletionOnce(
  messages: LLMMessage[],
  settings: LLMSettings,
  options?: ChatCompletionOptions & { model?: string },
): Promise<CompletionOnceResult> {
  const started = performance.now()
  const url = resolveApiUrl(settings.apiUrl)
  const model = options?.model ?? settings.model

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${settings.apiKey}`,
      },
      body: JSON.stringify({
        model,
        messages,
        temperature: settings.temperature,
        max_tokens: Math.min(settings.maxTokens, 16384),
        stream: false,
      }),
      signal: options?.signal,
    })

    const latencyMs = Math.round(performance.now() - started)

    if (!response.ok) {
      const err = await response.text()
      return {
        content: '',
        latencyMs,
        error: `HTTP ${response.status}: ${err.slice(0, 500)}`,
      }
    }

    const data = (await response.json()) as {
      choices?: Array<{ message?: { content?: string | null } }>
      usage?: CompletionUsage
    }

    return {
      content: data.choices?.[0]?.message?.content ?? '',
      latencyMs,
      usage: data.usage,
    }
  } catch (e) {
    const latencyMs = Math.round(performance.now() - started)
    const msg = e instanceof Error ? e.message : String(e)
    return {
      content: '',
      latencyMs,
      error: msg,
    }
  }
}

async function streamResponse(
  response: Response,
  onChunk: (text: string) => void,
  signal?: AbortSignal,
): Promise<string> {
  const reader = response.body?.getReader()
  if (!reader) throw new Error('无法获取响应流')

  const decoder = new TextDecoder()
  let fullText = ''
  let buffer = ''

  while (true) {
    if (signal?.aborted) {
      await reader.cancel()
      throw new DOMException('Aborted', 'AbortError')
    }
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed || !trimmed.startsWith('data: ')) continue
      const data = trimmed.slice(6)
      if (data === '[DONE]') break

      try {
        const parsed = JSON.parse(data)
        const delta = parsed.choices?.[0]?.delta?.content ?? ''
        if (delta) {
          fullText += delta
          onChunk(fullText)
        }
      } catch {
        // skip malformed chunks
      }
    }
  }

  return fullText
}
