import { useAuthStore } from '@/stores/auth'
import { useSettingsStore } from '@/stores/settings'
import { isEnterpriseBuild } from './enterpriseApi'
import {
  detectProviderFromApiUrl,
  findCatalogEntry,
  inferDefaultApiFromLlmHost,
  PROVIDER_LABEL,
} from './modelCatalog'

export type WayneCostMode = 'economy' | 'balanced' | 'quality' | 'critical'

export const WAYNE_COST_MODE_OPTIONS: Array<{
  value: WayneCostMode
  label: string
  description: string
}> = [
  {
    value: 'economy',
    label: '省钱模式',
    description: '优先低成本模型，避免默认命中高价模型。',
  },
  {
    value: 'balanced',
    label: '平衡模式',
    description: '在成本和效果之间折中，适合作为日常默认。',
  },
  {
    value: 'quality',
    label: '高质量模式',
    description: '优先使用强模型，适合重要但非极高风险任务。',
  },
  {
    value: 'critical',
    label: '关键任务模式',
    description: '允许高价值模型优先，用于发布、架构、重大决策。',
  },
]

export interface WayneRouteSuggestion {
  id: string
  stage: string
  title: string
  targetAgentId: string
  targetAgentName: string
  recommendedModel: string
  roleKey: WayneRoleKey
  reason: string
}

export type WayneRoleKey = 'orchestrator' | 'product' | 'developer' | 'qa' | 'china'

type RouteRule = WayneRouteSuggestion & {
  keywords: string[]
}

const ROLE_MODEL_MATRIX: Record<WayneRoleKey, Record<WayneCostMode, string>> = {
  orchestrator: {
    economy: 'deepseek-reasoner',
    balanced: 'deepseek-reasoner',
    quality: 'Opus 4.6',
    critical: 'Opus 4.6',
  },
  product: {
    economy: 'qwen-plus',
    balanced: 'gpt-4o',
    quality: 'GPT-4.5',
    critical: 'GPT-4.5',
  },
  developer: {
    economy: 'deepseek-chat',
    balanced: 'Sonnet 4.6',
    quality: 'Sonnet 4.6',
    critical: 'Sonnet 4.6',
  },
  qa: {
    economy: 'qwen-plus',
    balanced: 'Gemini 4',
    quality: 'Gemini 4',
    critical: 'Gemini 4',
  },
  china: {
    economy: '智谱 GLM-4.5',
    balanced: '智谱 GLM-4.5',
    quality: '智谱 GLM-4.5',
    critical: '智谱 GLM-4.5',
  },
}

const ROUTE_RULES: RouteRule[] = [
  {
    id: 'orchestrator',
    stage: '判断阶段',
    title: '先由 Wayne 总控判断阶段',
    targetAgentId: 'wayne-orchestrator',
    targetAgentName: 'Wayne Stack 总控',
    roleKey: 'orchestrator',
    recommendedModel: 'Opus 4.6',
    reason: '适合先判断阶段、拆解路径、识别缺失产物和高风险动作。',
    keywords: ['阶段', '流程', '顺序', '下一步', '怎么推进', '如何推进', '分配', '路由', '总控'],
  },
  {
    id: 'product',
    stage: '需求定义',
    title: '路由到 Wayne 产品经理',
    targetAgentId: 'wayne-product-manager',
    targetAgentName: 'Wayne 产品经理',
    roleKey: 'product',
    recommendedModel: 'GPT-4.5',
    reason: '适合 PRD、范围管理、目标/非目标、验收标准、用户故事。',
    keywords: ['prd', '需求', '产品', '范围', '非目标', '验收', '用户故事', 'roadmap', '规划', '想法', '功能定义'],
  },
  {
    id: 'developer',
    stage: '进入开发',
    title: '路由到 Wayne 开发工程师',
    targetAgentId: 'wayne-developer',
    targetAgentName: 'Wayne 开发工程师',
    roleKey: 'developer',
    recommendedModel: 'Sonnet 4.6',
    reason: '适合实现方案、模块改动、开发任务拆分、代码落地。',
    keywords: ['开发', '实现', '代码', '重构', '修复', 'bug', '接口', '前端', '后端', 'build', '改动'],
  },
  {
    id: 'qa',
    stage: '质量验证',
    title: '路由到 Wayne QA 负责人',
    targetAgentId: 'wayne-qa-lead',
    targetAgentName: 'Wayne QA 负责人',
    roleKey: 'qa',
    recommendedModel: 'Gemini 4',
    reason: '适合测试清单、风险验证、回归、上线前质量判断。',
    keywords: ['qa', '测试', '验证', '回归', '风险', '验收', '发布', '上线', '检查', '质量'],
  },
  {
    id: 'china',
    stage: '中文本土化',
    title: '路由到 Wayne 中文策略',
    targetAgentId: 'wayne-china-strategist',
    targetAgentName: 'Wayne 中文策略',
    roleKey: 'china',
    recommendedModel: '智谱 GLM-4.5',
    reason: '适合中文润色、本土化表达、老板汇报版和中国市场语境适配。',
    keywords: ['中文', '本土化', '老板', '汇报', '润色', '中国市场', '表达', '文案', '语气'],
  },
]

function matchScore(text: string, keywords: string[]) {
  return keywords.reduce((score, keyword) => score + (text.includes(keyword.toLowerCase()) ? 1 : 0), 0)
}

export function getWayneCostMode(): WayneCostMode {
  return useSettingsStore().settings.wayneCostMode ?? 'balanced'
}

export function getRecommendedModelForRole(roleKey: WayneRoleKey, mode = getWayneCostMode()) {
  return ROLE_MODEL_MATRIX[roleKey][mode]
}

export function getWayneCostModeMeta(mode = getWayneCostMode()) {
  return WAYNE_COST_MODE_OPTIONS.find((item) => item.value === mode) ?? WAYNE_COST_MODE_OPTIONS[1]
}

export function getWayneDefaultRoutes(): WayneRouteSuggestion[] {
  const mode = getWayneCostMode()
  return ROUTE_RULES.map(({ keywords: _keywords, ...rest }) => ({
    ...rest,
    recommendedModel: getRecommendedModelForRole(rest.roleKey, mode),
  }))
}

export function inferWayneRoute(input: string): WayneRouteSuggestion[] {
  const text = input.trim().toLowerCase()
  if (!text) return getWayneDefaultRoutes()

  const ranked = ROUTE_RULES.map((rule) => ({
    rule,
    score: matchScore(text, rule.keywords),
  }))
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score)
    .map(({ rule }) => {
      const { keywords: _keywords, ...rest } = rule
      return {
        ...rest,
        recommendedModel: getRecommendedModelForRole(rest.roleKey),
      }
    })

  if (!ranked.length) {
    return getWayneDefaultRoutes().slice(0, 3)
  }

  const uniq = new Map<string, WayneRouteSuggestion>()
  for (const item of ranked) {
    if (!uniq.has(item.id)) uniq.set(item.id, item)
  }
  return Array.from(uniq.values()).slice(0, 3)
}

function resolveRuntimeProvider() {
  if (!isEnterpriseBuild) {
    const settings = useSettingsStore().settings
    return settings.provider ?? detectProviderFromApiUrl(settings.apiUrl || '')
  }
  const host = useAuthStore().publicLlm?.host
  if (!host) return null
  return detectProviderFromApiUrl(inferDefaultApiFromLlmHost(host))
}

export function tryApplyRecommendedModel(modelId?: string) {
  if (!modelId) return { applied: false, reason: '' }
  const entry = findCatalogEntry(modelId)
  if (!entry) return { applied: false, reason: '' }

  const runtimeProvider = resolveRuntimeProvider()
  if (!runtimeProvider) {
    return {
      applied: false,
      reason: '当前网关厂商未知，未自动切换模型',
    }
  }

  if (runtimeProvider !== entry.provider) {
    return {
      applied: false,
      reason: `当前网关为 ${PROVIDER_LABEL[runtimeProvider]}，与 ${entry.label} 不兼容，未自动切换`,
    }
  }

  const settingsStore = useSettingsStore()
  if (settingsStore.settings.model !== modelId) {
    settingsStore.save({
      ...settingsStore.settings,
      model: modelId,
    })
    return {
      applied: true,
      reason: `已切换到推荐模型 ${entry.label}`,
    }
  }

  return {
    applied: true,
    reason: `当前已使用推荐模型 ${entry.label}`,
  }
}

export function buildWayneSeed(route: WayneRouteSuggestion, task: string) {
  const normalizedTask = task.trim()
  if (!normalizedTask) return ''

  if (route.targetAgentId === 'wayne-orchestrator') {
    return `请判断这个任务现在处于 Wayne Stack 的哪个阶段，并给出下一步最小动作：\n\n${normalizedTask}`
  }

  return `Wayne Orchestrator 已将以下任务路由给你，请按你的角色处理，并先输出最重要的下一步：\n\n${normalizedTask}`
}
