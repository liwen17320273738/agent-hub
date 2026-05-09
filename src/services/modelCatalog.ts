/**
 * Model lab catalog: API ids, scores, and short marketing blurbs.
 * 
 * 模型版本保持与各厂商最新公开 API 一致。每行带 `liveCheckModel` 用于
 * 对接后端 `/api/models/live` 实时状态校验。
 */
export interface ModelScores {
  /** 相对性价比：5=极省，1=很贵 */
  cost: number
  /** 首包/整体体感速度 */
  speed: number
  /** 数理、逻辑链、复杂推理 */
  reasoning: number
  /** 中文表达与本土化 */
  chinese: number
  /** 代码读写与调试建议 */
  coding: number
  /** 复杂指令、格式、角色遵循 */
  instruction: number
}

export type ModelProvider = 'deepseek' | 'openai' | 'qwen' | 'anthropic' | 'google' | 'zhipu'

export interface ModelCatalogEntry {
  /** 调用 API 时的 model 字段 */
  id: string
  provider: ModelProvider
  label: string
  /** Agent Hub 中最推荐承担的角色 */
  recommendedRole?: string
  /** 是否属于 Agent Hub 核心模型 */
  isCore?: boolean
  /** 一句话适用场景 */
  blurb: string
  scores: ModelScores
  /** 约上下文长度（K tokens），取常见文档量级，以厂商为准 */
  contextK: number
  /** 选用时注意 */
  caution?: string
  /** 用于与 /api/models/live 结果匹配的 model ID（可能不同于调用 id） */
  liveCheckModel?: string
}

const S = (partial: Partial<ModelScores> & Pick<ModelScores, 'cost' | 'speed'>): ModelScores => ({
  cost: partial.cost,
  speed: partial.speed,
  reasoning: partial.reasoning ?? 3,
  chinese: partial.chinese ?? 3,
  coding: partial.coding ?? 3,
  instruction: partial.instruction ?? 3,
})

export const PROVIDER_DEFAULT_API: Record<ModelProvider, string> = {
  deepseek: 'https://api.deepseek.com/v1/chat/completions',
  openai: 'https://api.openai.com/v1/chat/completions',
  qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
  anthropic: 'https://api.anthropic.com/v1/messages',
  google: 'https://generativelanguage.googleapis.com/v1beta/models',
  zhipu: 'https://open.bigmodel.cn/api/paas/v4/chat/completions',
}

export const PROVIDER_LABEL: Record<ModelProvider, string> = {
  deepseek: 'DeepSeek',
  openai: 'OpenAI',
  qwen: '通义千问（DashScope）',
  anthropic: 'Anthropic',
  google: 'Google',
  zhipu: '智谱',
}

/** Labels for `/models/live` response keys not in MODEL_CATALOG providers. */
export function liveModelProviderLabel(providerKey: string): string {
  if (providerKey === 'gateway') return '当前网关'
  if (providerKey === 'local') return '兼容网关'
  if (providerKey in PROVIDER_LABEL) return PROVIDER_LABEL[providerKey as ModelProvider]
  return providerKey
}

/** 与各厂商最新公开 API 对应的模型目录（版本以 2026-05 为准） */
export const MODEL_CATALOG: ModelCatalogEntry[] = [
  // ===== Anthropic =====
  {
    id: 'claude-sonnet-4-20250514',
    provider: 'anthropic',
    label: 'Claude Sonnet 4',
    recommendedRole: '开发工程师 / 主力施工',
    isCore: true,
    blurb: '主力施工模型，适合连续编码、修复和仓库级执行。平衡速度与质量。',
    scores: S({ cost: 3, speed: 4, reasoning: 4, chinese: 4, coding: 5, instruction: 5 }),
    contextK: 200,
    caution: '需 Anthropic API Key。当前环境通过兼容网关代理接入。',
    liveCheckModel: 'claude-sonnet-4-20250514',
  },
  {
    id: 'claude-opus-4-20250514',
    provider: 'anthropic',
    label: 'Claude Opus 4',
    recommendedRole: '总控 / 架构裁决',
    isCore: true,
    blurb: '最高能力模型，负责高价值判断、架构收口、复杂取舍和发布前 go/no-go。',
    scores: S({ cost: 1, speed: 2, reasoning: 5, chinese: 4, coding: 5, instruction: 5 }),
    contextK: 200,
    caution: '成本最高；适合关键决策，不建议用于批量任务。',
    liveCheckModel: 'claude-opus-4-20250514',
  },
  {
    id: 'claude-3-5-haiku-20241022',
    provider: 'anthropic',
    label: 'Claude 3.5 Haiku',
    recommendedRole: '轻量任务 / 快速响应',
    blurb: 'Anthropic 最快最便宜的模型，适合简单问答、分类和路由。',
    scores: S({ cost: 5, speed: 5, reasoning: 3, chinese: 3, coding: 3, instruction: 4 }),
    contextK: 200,
    liveCheckModel: 'claude-3-5-haiku-20241022',
  },

  // ===== OpenAI =====
  {
    id: 'gpt-4o',
    provider: 'openai',
    label: 'GPT-4o',
    recommendedRole: '综合交付 / 多模态',
    isCore: true,
    blurb: '多模态与综合能力强，适合高质量交付与复杂指令；成本较高。',
    scores: S({ cost: 2, speed: 4, reasoning: 4, chinese: 4, coding: 5, instruction: 5 }),
    contextK: 128,
    liveCheckModel: 'gpt-4o',
  },
  {
    id: 'gpt-4o-mini',
    provider: 'openai',
    label: 'GPT-4o mini',
    recommendedRole: '轻量任务 / 低成本',
    blurb: '低成本英文/简单任务、接口稳定；中文略弱于国产一线。',
    scores: S({ cost: 4, speed: 5, reasoning: 3, chinese: 3, coding: 4, instruction: 4 }),
    contextK: 128,
    liveCheckModel: 'gpt-4o-mini',
  },
  {
    id: 'o3-mini',
    provider: 'openai',
    label: 'o3-mini',
    recommendedRole: '推理密集型任务',
    blurb: 'OpenAI 推理系列，适合数学、逻辑链、代码分析等需要深度思考的任务。',
    scores: S({ cost: 3, speed: 3, reasoning: 5, chinese: 3, coding: 5, instruction: 4 }),
    contextK: 200,
    liveCheckModel: 'o3-mini',
  },

  // ===== DeepSeek =====
  {
    id: 'deepseek-chat',
    provider: 'deepseek',
    label: 'DeepSeek V3',
    recommendedRole: '日常默认主力 / 成本敏感任务',
    blurb: 'DeepSeek 最新旗舰，中文场景性价比极高，适合作为默认主力。',
    scores: S({ cost: 5, speed: 4, reasoning: 4, chinese: 5, coding: 4, instruction: 4 }),
    contextK: 64,
    liveCheckModel: 'deepseek-chat',
  },
  {
    id: 'deepseek-reasoner',
    provider: 'deepseek',
    label: 'DeepSeek R1',
    recommendedRole: '低成本推理备选',
    blurb: '推理向任务（数学题、链式分析）；更慢但推理深度高。',
    scores: S({ cost: 3, speed: 2, reasoning: 5, chinese: 5, coding: 5, instruction: 4 }),
    contextK: 64,
    caution: '响应延迟明显高于 V3；按 token 计费通常更高。',
    liveCheckModel: 'deepseek-reasoner',
  },

  // ===== Google =====
  {
    id: 'gemini-2.5-pro',
    provider: 'google',
    label: 'Gemini 2.5 Pro',
    recommendedRole: '研究 / 长上下文分析',
    isCore: true,
    blurb: 'Google 最强模型，适合长上下文研究、方案对比、多模态分析。',
    scores: S({ cost: 3, speed: 3, reasoning: 5, chinese: 4, coding: 5, instruction: 5 }),
    contextK: 1048,
    liveCheckModel: 'gemini-2.5-pro',
  },
  {
    id: 'gemini-2.5-flash',
    provider: 'google',
    label: 'Gemini 2.5 Flash',
    recommendedRole: '高速 / 低成本',
    blurb: 'Gemini 家族最快模型，适合高吞吐、低延迟场景。',
    scores: S({ cost: 4, speed: 5, reasoning: 3, chinese: 4, coding: 4, instruction: 4 }),
    contextK: 1048,
    liveCheckModel: 'gemini-2.5-flash',
  },

  // ===== Zhipu (智谱) =====
  {
    id: 'glm-4.7',
    provider: 'zhipu',
    label: 'GLM-4.7',
    recommendedRole: '中文策略 / 本土化',
    isCore: true,
    blurb: '智谱最新旗舰，中文表达优秀，适合本土化内容和中文业务沟通。',
    scores: S({ cost: 4, speed: 4, reasoning: 4, chinese: 5, coding: 4, instruction: 5 }),
    contextK: 128,
    caution: '当前已有 API Key 接入，可直接使用。',
    liveCheckModel: 'glm-4.7',
  },
  {
    id: 'glm-4.7-flash',
    provider: 'zhipu',
    label: 'GLM-4.7 Flash',
    recommendedRole: '中文轻量任务',
    blurb: 'GLM 家族快速版本，适合高频中文对话和轻量生成。',
    scores: S({ cost: 5, speed: 5, reasoning: 3, chinese: 5, coding: 3, instruction: 4 }),
    contextK: 128,
    liveCheckModel: 'glm-4-flash',
  },

  // ===== Qwen (通义千问) =====
  {
    id: 'qwen-plus',
    provider: 'qwen',
    label: 'Qwen Plus',
    recommendedRole: '国内业务平衡档',
    blurb: '平衡成本与效果，适合日常业务文案与国内合规场景。',
    scores: S({ cost: 4, speed: 4, reasoning: 3, chinese: 5, coding: 4, instruction: 4 }),
    contextK: 131072,
    liveCheckModel: 'qwen-plus',
  },
  {
    id: 'qwen-max',
    provider: 'qwen',
    label: 'Qwen Max',
    recommendedRole: '千问高阶复杂任务',
    blurb: '千问系列顶配，复杂任务与长上下文。',
    scores: S({ cost: 2, speed: 3, reasoning: 4, chinese: 5, coding: 4, instruction: 5 }),
    contextK: 32768,
    caution: '单价高，建议配合摘要与窗口限制使用。',
    liveCheckModel: 'qwen-max',
  },
  {
    id: 'qwen-turbo',
    provider: 'qwen',
    label: 'Qwen Turbo',
    recommendedRole: '海量轻量中文生成',
    blurb: '阿里云兼容接口下最便宜档位，适合大批量轻量生成。',
    scores: S({ cost: 5, speed: 5, reasoning: 2, chinese: 5, coding: 3, instruction: 3 }),
    contextK: 8192,
    caution: '上下文与能力弱于 Plus/Max，长文请换型号。',
    liveCheckModel: 'qwen-turbo',
  },
]

export const Agent_CORE_MODELS = MODEL_CATALOG.filter((m) => m.isCore)

export const SCORE_LABELS: { key: keyof ModelScores; label: string }[] = [
  { key: 'cost', label: '性价比' },
  { key: 'speed', label: '速度' },
  { key: 'reasoning', label: '推理' },
  { key: 'chinese', label: '中文' },
  { key: 'coding', label: '代码' },
  { key: 'instruction', label: '指令遵循' },
]

export function detectProviderFromApiUrl(apiUrl: string): ModelProvider | null {
  const u = apiUrl.toLowerCase()
  if (u.includes('deepseek')) return 'deepseek'
  if (u.includes('openai.com')) return 'openai'
  if (u.includes('dashscope') || u.includes('aliyuncs')) return 'qwen'
  if (u.includes('anthropic.com')) return 'anthropic'
  if (u.includes('generativelanguage.googleapis.com') || u.includes('gemini')) return 'google'
  if (u.includes('bigmodel.cn') || u.includes('open.bigmodel.cn')) return 'zhipu'
  return null
}

/** 企业模式仅暴露上游 host 时，用于模型实验室的厂商匹配 */
export function inferDefaultApiFromLlmHost(host: string): string {
  const h = host.toLowerCase()
  if (h.includes('deepseek')) return PROVIDER_DEFAULT_API.deepseek
  if (h.includes('openai')) return PROVIDER_DEFAULT_API.openai
  if (h.includes('dashscope') || h.includes('aliyuncs')) return PROVIDER_DEFAULT_API.qwen
  if (h.includes('anthropic')) return PROVIDER_DEFAULT_API.anthropic
  if (h.includes('generativelanguage.googleapis.com') || h.includes('gemini')) return PROVIDER_DEFAULT_API.google
  if (h.includes('bigmodel.cn')) return PROVIDER_DEFAULT_API.zhipu
  return ''
}

export function catalogByProvider(provider: ModelProvider): ModelCatalogEntry[] {
  return MODEL_CATALOG.filter((m) => m.provider === provider)
}

export function catalogMatchingApiUrl(apiUrl: string): ModelCatalogEntry[] {
  const p = detectProviderFromApiUrl(apiUrl)
  if (!p) return []
  return catalogByProvider(p)
}

export function findCatalogEntry(modelId: string): ModelCatalogEntry | undefined {
  return MODEL_CATALOG.find((m) => m.id === modelId)
}

/**
 * 若 model 在目录中有记录且与当前厂商不一致，则换成本厂商目录中的首个推荐 ID；
 * 未知/自定义 model id（不在目录中）则保留，便于接入新模型名。
 */
export function coerceModelForProvider(model: string, provider: ModelProvider): string {
  const trimmed = model.trim()
  const fallback = catalogByProvider(provider)[0]?.id ?? ''
  if (!trimmed) return fallback
  const entry = findCatalogEntry(trimmed)
  if (entry && entry.provider !== provider) return fallback
  return trimmed
}
