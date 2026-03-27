/**
 * 模型对比维度（1–5 分，主观参考行业常见评价，非实时榜单；实测以「模型实验室」为准）。
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

export type ModelProvider = 'deepseek' | 'openai' | 'qwen'

export interface ModelCatalogEntry {
  /** 调用 API 时的 model 字段 */
  id: string
  provider: ModelProvider
  label: string
  /** 一句话适用场景 */
  blurb: string
  scores: ModelScores
  /** 约上下文长度（K tokens），取常见文档量级，以厂商为准 */
  contextK: number
  /** 选用时注意 */
  caution?: string
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
}

export const PROVIDER_LABEL: Record<ModelProvider, string> = {
  deepseek: 'DeepSeek',
  openai: 'OpenAI',
  qwen: '通义千问（DashScope）',
}

/** 与当前项目默认集成的常见模型（按厂商） */
export const MODEL_CATALOG: ModelCatalogEntry[] = [
  {
    id: 'deepseek-chat',
    provider: 'deepseek',
    label: 'DeepSeek Chat',
    blurb: '日常对话、营销文案、中文场景性价比高，适合作为默认主力。',
    scores: S({ cost: 5, speed: 4, reasoning: 3, chinese: 5, coding: 4, instruction: 4 }),
    contextK: 64,
  },
  {
    id: 'deepseek-reasoner',
    provider: 'deepseek',
    label: 'DeepSeek Reasoner',
    blurb: '推理向任务（数学题、链式分析）；更慢、更贵，不适合高频短问答。',
    scores: S({ cost: 3, speed: 2, reasoning: 5, chinese: 5, coding: 4, instruction: 4 }),
    contextK: 64,
    caution: '响应延迟明显高于 chat；按 token 计费通常更高。',
  },
  {
    id: 'gpt-4o-mini',
    provider: 'openai',
    label: 'GPT-4o mini',
    blurb: '低成本英文/简单任务、接口稳定；中文略弱于国产一线。',
    scores: S({ cost: 4, speed: 5, reasoning: 3, chinese: 3, coding: 4, instruction: 4 }),
    contextK: 128,
  },
  {
    id: 'gpt-4o',
    provider: 'openai',
    label: 'GPT-4o',
    blurb: '多模态与综合能力强，适合高质量交付与复杂指令；成本较高。',
    scores: S({ cost: 2, speed: 4, reasoning: 4, chinese: 4, coding: 5, instruction: 5 }),
    contextK: 128,
  },
  {
    id: 'gpt-4.1-mini',
    provider: 'openai',
    label: 'GPT-4.1 mini',
    blurb: '若账号已开通新系列，可作 4o-mini 同级备选（以控制台为准）。',
    scores: S({ cost: 4, speed: 5, reasoning: 3, chinese: 3, coding: 4, instruction: 4 }),
    contextK: 128,
    caution: '名称与可用性以 OpenAI 控制台为准，不可用则换 4o-mini。',
  },
  {
    id: 'qwen-turbo',
    provider: 'qwen',
    label: 'Qwen Turbo',
    blurb: '阿里云兼容接口下最便宜档位，适合大批量轻量生成。',
    scores: S({ cost: 5, speed: 5, reasoning: 2, chinese: 5, coding: 3, instruction: 3 }),
    contextK: 8,
    caution: '上下文与能力弱于 Plus/Max，长文请换型号。',
  },
  {
    id: 'qwen-plus',
    provider: 'qwen',
    label: 'Qwen Plus',
    blurb: '平衡成本与效果，适合日常业务文案与国内合规场景。',
    scores: S({ cost: 4, speed: 4, reasoning: 3, chinese: 5, coding: 4, instruction: 4 }),
    contextK: 32,
  },
  {
    id: 'qwen-max',
    provider: 'qwen',
    label: 'Qwen Max',
    blurb: '千问系列顶配之一，复杂任务与长上下文（以官方为准）。',
    scores: S({ cost: 2, speed: 3, reasoning: 4, chinese: 5, coding: 4, instruction: 5 }),
    contextK: 32,
    caution: '单价高，建议配合摘要与窗口限制使用。',
  },
]

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
  return null
}

/** 企业模式仅暴露上游 host 时，用于模型实验室的厂商匹配 */
export function inferDefaultApiFromLlmHost(host: string): string {
  const h = host.toLowerCase()
  if (h.includes('deepseek')) return PROVIDER_DEFAULT_API.deepseek
  if (h.includes('openai')) return PROVIDER_DEFAULT_API.openai
  if (h.includes('dashscope') || h.includes('aliyuncs')) return PROVIDER_DEFAULT_API.qwen
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
