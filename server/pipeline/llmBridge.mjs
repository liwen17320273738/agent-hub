/**
 * LLM Bridge — 统一的 LLM 调用抽象层
 *
 * 支持: OpenAI-compatible / Anthropic / Gemini / Ollama
 * 从 orchestrator.mjs 抽离，供 Lead Agent 和 Subtask 共用
 *
 * === Planner-Worker Model Tiering ===
 * Tier 1 (planning):  claude-opus-4 / gpt-4.5       — 需求分析、架构决策
 * Tier 2 (execution): claude-sonnet-4 / deepseek-chat — 代码实现、文档撰写
 * Tier 3 (routine):   deepseek-chat / gpt-4o-mini    — 格式化、翻译、验证
 */

const MODEL_TIERS = {
  planning:  { models: ['claude-opus-4-20250514', 'gpt-4.5', 'deepseek-chat'], label: 'Tier 1 — Planning' },
  execution: { models: ['claude-sonnet-4-20250514', 'deepseek-chat', 'gpt-4o'], label: 'Tier 2 — Execution' },
  routine:   { models: ['deepseek-chat', 'gpt-4o-mini', 'qwen-plus'], label: 'Tier 3 — Routine' },
}

const ROLE_TIER = {
  'orchestrator': 'planning',
  'lead-agent': 'planning',
  'product-manager': 'execution',
  'developer': 'execution',
  'qa-lead': 'execution',
  'executor': 'execution',
}

export function resolveModelForRole(role, stageId) {
  const tier = ROLE_TIER[role] || 'routine'
  const tierConf = MODEL_TIERS[tier]
  const envModel = process.env.LLM_MODEL
  if (envModel && tierConf.models.includes(envModel)) return { model: envModel, tier }
  return { model: envModel || tierConf.models[0], tier }
}

export async function callLLM(systemPrompt, userMessage, options = {}) {
  const role = options.role || ''
  const resolved = role ? resolveModelForRole(role, options.stageId) : { model: null, tier: 'default' }
  const LLM_API_URL = options.apiUrl || process.env.LLM_API_URL
  const LLM_API_KEY = options.apiKey || process.env.LLM_API_KEY
  const LLM_MODEL = options.model || resolved.model || process.env.LLM_MODEL || 'deepseek-chat'
  const maxTokens = options.maxTokens || 8192
  const temperature = options.temperature ?? 0.5

  if (!LLM_API_URL || !LLM_API_KEY) {
    return { ok: false, error: 'LLM 未配置（LLM_API_URL / LLM_API_KEY）' }
  }

  const provider = inferProvider(LLM_API_URL)
  const messages = [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: userMessage },
  ]

  try {
    let content = ''
    let tokenUsage = null

    if (provider === 'anthropic') {
      const { system, conversation } = extractSysConv(messages)
      const resp = await fetch(LLM_API_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': LLM_API_KEY,
          'anthropic-version': '2023-06-01',
        },
        body: JSON.stringify({
          model: LLM_MODEL,
          max_tokens: maxTokens,
          temperature,
          ...(system ? { system } : {}),
          messages: conversation.map(m => ({
            role: m.role,
            content: [{ type: 'text', text: m.content }],
          })),
        }),
      })
      const data = await resp.json()
      if (!resp.ok) return { ok: false, error: `Anthropic ${resp.status}: ${JSON.stringify(data).slice(0, 500)}` }
      content = data.content?.map(c => c.text || '').join('') || ''
      tokenUsage = data.usage

    } else if (provider === 'gemini') {
      const { system, conversation } = extractSysConv(messages)
      const base = LLM_API_URL.replace(/\/$/, '')
      const url = `${base}/${encodeURIComponent(LLM_MODEL)}:generateContent?key=${encodeURIComponent(LLM_API_KEY)}`
      const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...(system ? { systemInstruction: { parts: [{ text: system }] } } : {}),
          contents: conversation.map(m => ({
            role: m.role === 'assistant' ? 'model' : 'user',
            parts: [{ text: m.content }],
          })),
          generationConfig: { temperature, maxOutputTokens: maxTokens },
        }),
      })
      const data = await resp.json()
      if (!resp.ok) return { ok: false, error: `Gemini ${resp.status}: ${JSON.stringify(data).slice(0, 500)}` }
      content = data.candidates?.[0]?.content?.parts?.map(p => p.text || '').join('') || ''
      tokenUsage = data.usageMetadata

    } else {
      const resp = await fetch(LLM_API_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${LLM_API_KEY}`,
        },
        body: JSON.stringify({
          model: LLM_MODEL,
          messages,
          temperature,
          max_tokens: maxTokens,
          stream: false,
        }),
      })
      const data = await resp.json()
      if (!resp.ok) return { ok: false, error: `LLM ${resp.status}: ${JSON.stringify(data).slice(0, 500)}` }
      content = data.choices?.[0]?.message?.content || ''
      tokenUsage = data.usage
    }

    return { ok: true, content, tokenUsage, model: LLM_MODEL, provider, tier: resolved.tier }
  } catch (e) {
    return { ok: false, error: e.message }
  }
}

function inferProvider(url) {
  const u = url.toLowerCase()
  if (u.includes('anthropic.com')) return 'anthropic'
  if (u.includes('generativelanguage.googleapis.com') || u.includes('gemini')) return 'gemini'
  return 'openai-compatible'
}

function extractSysConv(messages) {
  const system = messages.filter(m => m.role === 'system').map(m => m.content).join('\n\n').trim()
  const conversation = messages.filter(m => m.role !== 'system')
  return { system, conversation }
}
