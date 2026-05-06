import type { ToolCall } from './tools'
import { apiUrl, isEnterpriseBuild } from './enterpriseApi'
import { useAuthStore } from '@/stores/auth'
import { useSettingsStore } from '@/stores/settings'
import { detectProviderFromApiUrl, type ModelProvider } from './modelCatalog'
import type { AgentCostMode } from './wayneRouting'

export interface LLMSettings {
  provider?: ModelProvider
  AgentCostMode?: AgentCostMode
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
  /**
   * 专家聊天走后端 `AgentRuntime`（`runAgentStream`）；关闭时用浏览器直连接口 + 轻工具（离线/demo）。
   */
  agentChatUseBackendRuntime: boolean
}

export const defaultSettings: LLMSettings = {
  provider: 'deepseek',
  AgentCostMode: 'balanced',
  apiUrl: 'https://api.deepseek.com/v1/chat/completions',
  apiKey: '',
  model: 'deepseek-chat',
  temperature: 0.7,
  maxTokens: 4096,
  contextMaxMessages: 32,
  contextMaxChars: 48000,
  enableTools: false,
  agentChatUseBackendRuntime: true,
}

export interface LLMMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
}

type ProviderMode = 'openai-compatible' | 'anthropic' | 'gemini'

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
  if (apiUrl.includes('api.anthropic.com'))
    return apiUrl.replace('https://api.anthropic.com', '/api/proxy/anthropic')
  if (apiUrl.includes('generativelanguage.googleapis.com'))
    return apiUrl.replace('https://generativelanguage.googleapis.com', '/api/proxy/gemini')
  if (apiUrl.includes('open.bigmodel.cn'))
    return apiUrl.replace('https://open.bigmodel.cn/api/paas/v4', '/api/proxy/zhipu')
  return apiUrl
}

function useServerLlm(): boolean {
  try {
    return isEnterpriseBuild && useAuthStore().isLoggedIn
  } catch {
    return false
  }
}

function inferProviderMode(rawApiUrl: string): ProviderMode {
  const detected = detectProviderFromApiUrl(rawApiUrl)
  if (detected === 'anthropic') return 'anthropic'
  if (detected === 'google') return 'gemini'
  return 'openai-compatible'
}

function providerModeForSettings(settings: LLMSettings): ProviderMode {
  if (useServerLlm()) {
    const host = useAuthStore().publicLlm?.host
    return inferProviderMode(host ? `https://${host}` : '')
  }
  const explicitProvider = settings.provider
  if (explicitProvider === 'anthropic') return 'anthropic'
  if (explicitProvider === 'google') return 'gemini'
  return inferProviderMode(settings.apiUrl)
}

function effectiveModel(settings: LLMSettings, override?: string): string {
  if (useServerLlm()) {
    return override ?? useSettingsStore().effectiveModel()
  }
  return override ?? settings.model
}

function extractSystemAndMessages(messages: Array<{ role: string; content?: string | null }>) {
  const system = messages
    .filter((m) => m.role === 'system')
    .map((m) => m.content ?? '')
    .join('\n\n')
    .trim()

  const conversation = messages
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .map((m) => ({
      role: m.role as 'user' | 'assistant',
      content: String(m.content ?? ''),
    }))

  return { system, conversation }
}

function anthropicHeaders(apiKey: string) {
  return {
    'Content-Type': 'application/json',
    'x-api-key': apiKey,
    'anthropic-version': '2023-06-01',
  }
}

function anthropicBody(
  model: string,
  messages: Array<{ role: string; content?: string | null }>,
  settings: LLMSettings,
) {
  const { system, conversation } = extractSystemAndMessages(messages)
  return {
    model,
    max_tokens: Math.min(settings.maxTokens, 16384),
    temperature: settings.temperature,
    ...(system ? { system } : {}),
    messages: conversation.map((m) => ({
      role: m.role,
      content: [{ type: 'text', text: m.content }],
    })),
  }
}

function parseAnthropicResponse(data: any) {
  const content = Array.isArray(data?.content)
    ? data.content
        .map((item: any) => (item?.type === 'text' ? item.text : ''))
        .filter(Boolean)
        .join('')
    : ''
  const usage = data?.usage
    ? {
        prompt_tokens: data.usage.input_tokens,
        completion_tokens: data.usage.output_tokens,
        total_tokens:
          (data.usage.input_tokens ?? 0) + (data.usage.output_tokens ?? 0),
      }
    : undefined
  return { content, usage }
}

function geminiEndpoint(baseApiUrl: string, model: string, apiKey: string) {
  const base = resolveApiUrl(baseApiUrl).replace(/\/$/, '')
  return `${base}/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(apiKey)}`
}

function geminiBody(
  model: string,
  messages: Array<{ role: string; content?: string | null }>,
  settings: LLMSettings,
) {
  void model
  const { system, conversation } = extractSystemAndMessages(messages)
  return {
    ...(system ? { systemInstruction: { parts: [{ text: system }] } } : {}),
    contents: conversation.map((m) => ({
      role: m.role === 'assistant' ? 'model' : 'user',
      parts: [{ text: m.content }],
    })),
    generationConfig: {
      temperature: settings.temperature,
      maxOutputTokens: Math.min(settings.maxTokens, 16384),
    },
  }
}

function parseGeminiResponse(data: any) {
  const parts = data?.candidates?.[0]?.content?.parts
  const content = Array.isArray(parts)
    ? parts
        .map((part: any) => part?.text ?? '')
        .filter(Boolean)
        .join('')
    : ''
  const usage = data?.usageMetadata
    ? {
        prompt_tokens: data.usageMetadata.promptTokenCount,
        completion_tokens: data.usageMetadata.candidatesTokenCount,
        total_tokens: data.usageMetadata.totalTokenCount,
      }
    : undefined
  return { content, usage }
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
  const providerMode = providerModeForSettings(settings)
  if (providerMode !== 'openai-compatible') {
    if (options?.tools?.length) {
      throw new Error('当前 provider 不支持 OpenAI 风格工具调用，请关闭工具调用后重试')
    }
    const content = await chatCompletion(
      messages
        .filter((m) => m.role === 'system' || m.role === 'user' || m.role === 'assistant')
        .map((m) => ({
          role: m.role as 'system' | 'user' | 'assistant',
          content: String(m.content ?? ''),
        })),
      settings,
      undefined,
      options,
    )
    return { content }
  }

  const body: Record<string, unknown> = {
    model: effectiveModel(settings),
    messages,
    temperature: settings.temperature,
    max_tokens: Math.min(settings.maxTokens, 16384),
    stream: false,
  }
  if (options?.tools?.length) {
    body.tools = options.tools
    body.tool_choice = 'auto'
  }

  const response = useServerLlm()
    ? await fetch(apiUrl('/llm/chat-api'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: options?.signal,
      })
    : await fetch(resolveApiUrl(settings.apiUrl), {
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
  const providerMode = providerModeForSettings(settings)
  if (!useServerLlm() && providerMode === 'anthropic') {
    const response = await fetch(resolveApiUrl(settings.apiUrl), {
      method: 'POST',
      headers: anthropicHeaders(settings.apiKey),
      body: JSON.stringify(anthropicBody(effectiveModel(settings), messages, settings)),
      signal: options?.signal,
    })
    if (!response.ok) {
      const err = await response.text()
      throw new Error(`API 请求失败 (${response.status}): ${err}`)
    }
    const parsed = parseAnthropicResponse(await response.json())
    if (onChunk) onChunk(parsed.content)
    return parsed.content
  }

  if (!useServerLlm() && providerMode === 'gemini') {
    const response = await fetch(geminiEndpoint(settings.apiUrl, effectiveModel(settings), settings.apiKey), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(geminiBody(effectiveModel(settings), messages, settings)),
      signal: options?.signal,
    })
    if (!response.ok) {
      const err = await response.text()
      throw new Error(`API 请求失败 (${response.status}): ${err}`)
    }
    const parsed = parseGeminiResponse(await response.json())
    if (onChunk) onChunk(parsed.content)
    return parsed.content
  }

  const payload = {
    model: effectiveModel(settings),
    messages,
    temperature: settings.temperature,
    max_tokens: Math.min(settings.maxTokens, 16384),
    stream: !!onChunk,
  }

  const response = useServerLlm()
    ? await fetch(apiUrl('/llm/chat'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: options?.signal,
      })
    : await fetch(resolveApiUrl(settings.apiUrl), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${settings.apiKey}`,
        },
        body: JSON.stringify(payload),
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
  const model = effectiveModel(settings, options?.model)
  const providerMode = providerModeForSettings(settings)

  try {
    if (!useServerLlm() && providerMode === 'anthropic') {
      const response = await fetch(resolveApiUrl(settings.apiUrl), {
        method: 'POST',
        headers: anthropicHeaders(settings.apiKey),
        body: JSON.stringify(anthropicBody(model, messages, settings)),
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
      const parsed = parseAnthropicResponse(await response.json())
      return {
        content: parsed.content,
        latencyMs,
        usage: parsed.usage,
      }
    }

    if (!useServerLlm() && providerMode === 'gemini') {
      const response = await fetch(geminiEndpoint(settings.apiUrl, model, settings.apiKey), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(geminiBody(model, messages, settings)),
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
      const parsed = parseGeminiResponse(await response.json())
      return {
        content: parsed.content,
        latencyMs,
        usage: parsed.usage,
      }
    }

    const body = {
      model,
      messages,
      temperature: settings.temperature,
      max_tokens: Math.min(settings.maxTokens, 16384),
      stream: false,
    }

    const response = useServerLlm()
      ? await fetch(apiUrl('/llm/chat-once'), {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: options?.signal,
        })
      : await fetch(resolveApiUrl(settings.apiUrl), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${settings.apiKey}`,
          },
          body: JSON.stringify(body),
          signal: options?.signal,
        })

    const latencyMs = Math.round(performance.now() - started)

    if (useServerLlm()) {
      const data = (await response.json()) as {
        content?: string
        latencyMs?: number
        usage?: CompletionUsage
        error?: string
      }
      if (!response.ok) {
        return {
          content: '',
          latencyMs: data.latencyMs ?? latencyMs,
          error: data.error || `HTTP ${response.status}`,
        }
      }
      if (data.error) {
        return { content: '', latencyMs: data.latencyMs ?? latencyMs, error: data.error }
      }
      return {
        content: data.content ?? '',
        latencyMs: data.latencyMs ?? latencyMs,
        usage: data.usage,
      }
    }

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
