/**
 * Model Registry — 实时获取各厂商最新模型列表并缓存
 *
 * 支持: OpenAI-compatible, Anthropic, Google Gemini, DeepSeek, 智谱, 通义千问
 * 缓存策略: 内存缓存 + 可选 Redis; TTL 可配置 (默认 10 分钟)
 */

const CACHE_TTL = Number(process.env.MODEL_CACHE_TTL_MS) || 10 * 60 * 1000

const _cache = new Map()

function cacheGet(key) {
  const entry = _cache.get(key)
  if (!entry) return null
  if (Date.now() - entry.ts > CACHE_TTL) {
    _cache.delete(key)
    return null
  }
  return entry.data
}

function cacheSet(key, data) {
  _cache.set(key, { data, ts: Date.now() })
}

export function clearModelCache() {
  _cache.clear()
}

const PROVIDER_CONFIGS = {
  openai: {
    label: 'OpenAI',
    modelsUrl: 'https://api.openai.com/v1/models',
    chatUrl: 'https://api.openai.com/v1/chat/completions',
    authHeader: (key) => ({ Authorization: `Bearer ${key}` }),
    parseModels: (data) =>
      (data?.data || [])
        .filter((m) => m.id && /gpt|o[134]|chatgpt/i.test(m.id))
        .map((m) => ({
          id: m.id,
          provider: 'openai',
          label: m.id,
          owned_by: m.owned_by,
          created: m.created,
        }))
        .sort((a, b) => (b.created || 0) - (a.created || 0)),
  },
  anthropic: {
    label: 'Anthropic',
    modelsUrl: 'https://api.anthropic.com/v1/models',
    chatUrl: 'https://api.anthropic.com/v1/messages',
    authHeader: (key) => ({
      'x-api-key': key,
      'anthropic-version': '2023-06-01',
    }),
    parseModels: (data) =>
      (data?.data || [])
        .map((m) => ({
          id: m.id,
          provider: 'anthropic',
          label: m.display_name || m.id,
          created: m.created_at ? new Date(m.created_at).getTime() / 1000 : undefined,
        }))
        .sort((a, b) => (b.created || 0) - (a.created || 0)),
  },
  deepseek: {
    label: 'DeepSeek',
    modelsUrl: 'https://api.deepseek.com/models',
    chatUrl: 'https://api.deepseek.com/v1/chat/completions',
    authHeader: (key) => ({ Authorization: `Bearer ${key}` }),
    parseModels: (data) =>
      (data?.data || [])
        .map((m) => ({
          id: m.id,
          provider: 'deepseek',
          label: m.id,
          owned_by: m.owned_by,
        })),
  },
  zhipu: {
    label: '智谱',
    modelsUrl: 'https://open.bigmodel.cn/api/paas/v4/models',
    chatUrl: 'https://open.bigmodel.cn/api/paas/v4/chat/completions',
    authHeader: (key) => ({ Authorization: `Bearer ${key}` }),
    parseModels: (data) =>
      (data?.data || [])
        .map((m) => ({
          id: m.id,
          provider: 'zhipu',
          label: m.id,
          owned_by: m.owned_by,
        })),
  },
  qwen: {
    label: '通义千问 (DashScope)',
    modelsUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1/models',
    chatUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
    authHeader: (key) => ({ Authorization: `Bearer ${key}` }),
    parseModels: (data) =>
      (data?.data || [])
        .filter((m) => m.id)
        .map((m) => ({
          id: m.id,
          provider: 'qwen',
          label: m.id,
          owned_by: m.owned_by,
        })),
  },
  google: {
    label: 'Google',
    modelsUrl: null,
    chatUrl: 'https://generativelanguage.googleapis.com/v1beta/models',
    authHeader: () => ({}),
    getModelsUrl: (key) =>
      `https://generativelanguage.googleapis.com/v1beta/models?key=${encodeURIComponent(key)}`,
    parseModels: (data) =>
      (data?.models || [])
        .filter((m) => m.supportedGenerationMethods?.includes('generateContent'))
        .map((m) => ({
          id: m.name?.replace('models/', '') || m.name,
          provider: 'google',
          label: m.displayName || m.name,
          description: m.description,
          contextWindow: m.inputTokenLimit,
          maxOutput: m.outputTokenLimit,
        })),
  },
}

async function fetchProviderModels(provider, apiKey) {
  const config = PROVIDER_CONFIGS[provider]
  if (!config) return []

  const cacheKey = `models:${provider}`
  const cached = cacheGet(cacheKey)
  if (cached) return cached

  try {
    const url = config.getModelsUrl
      ? config.getModelsUrl(apiKey)
      : config.modelsUrl
    if (!url) return []

    const headers = {
      'Content-Type': 'application/json',
      ...config.authHeader(apiKey),
    }

    const res = await fetch(url, {
      method: 'GET',
      headers,
      signal: AbortSignal.timeout(15_000),
    })

    if (!res.ok) {
      console.warn(`[modelRegistry] ${provider} models API returned ${res.status}`)
      return []
    }

    const data = await res.json()
    const models = config.parseModels(data)
    cacheSet(cacheKey, models)
    return models
  } catch (e) {
    console.warn(`[modelRegistry] ${provider} fetch error: ${e.message}`)
    return []
  }
}

/**
 * 获取所有已配置厂商的模型列表
 * @param {Record<string, string>} apiKeys - { provider: apiKey }
 */
export async function fetchAllModels(apiKeys) {
  const allCacheKey = 'models:all:' + Object.keys(apiKeys).sort().join(',')
  const cached = cacheGet(allCacheKey)
  if (cached) return cached

  const results = await Promise.allSettled(
    Object.entries(apiKeys)
      .filter(([, key]) => key?.trim())
      .map(async ([provider, key]) => {
        const models = await fetchProviderModels(provider, key)
        return { provider, models }
      }),
  )

  const providerResults = {}
  for (const r of results) {
    if (r.status === 'fulfilled') {
      providerResults[r.value.provider] = r.value.models
    }
  }

  cacheSet(allCacheKey, providerResults)
  return providerResults
}

/**
 * 从环境变量推断已配置的厂商 API Keys
 */
export function resolveApiKeysFromEnv() {
  const keys = {}
  const envMappings = {
    openai: ['OPENAI_API_KEY', 'LLM_API_KEY'],
    anthropic: ['ANTHROPIC_API_KEY'],
    deepseek: ['DEEPSEEK_API_KEY'],
    zhipu: ['ZHIPU_API_KEY'],
    qwen: ['QWEN_API_KEY', 'DASHSCOPE_API_KEY'],
    google: ['GOOGLE_API_KEY', 'GEMINI_API_KEY'],
  }

  for (const [provider, envKeys] of Object.entries(envMappings)) {
    for (const envKey of envKeys) {
      if (process.env[envKey]?.trim()) {
        keys[provider] = process.env[envKey].trim()
        break
      }
    }
  }

  // Fallback: infer from LLM_API_URL + LLM_API_KEY
  const llmUrl = (process.env.LLM_API_URL || '').toLowerCase()
  const llmKey = process.env.LLM_API_KEY || ''
  if (llmKey) {
    if (llmUrl.includes('deepseek') && !keys.deepseek) keys.deepseek = llmKey
    else if (llmUrl.includes('openai.com') && !keys.openai) keys.openai = llmKey
    else if (llmUrl.includes('anthropic') && !keys.anthropic) keys.anthropic = llmKey
    else if (llmUrl.includes('bigmodel.cn') && !keys.zhipu) keys.zhipu = llmKey
    else if (llmUrl.includes('dashscope') && !keys.qwen) keys.qwen = llmKey
    else if ((llmUrl.includes('googleapis') || llmUrl.includes('gemini')) && !keys.google) keys.google = llmKey
  }

  return keys
}

export { PROVIDER_CONFIGS }
