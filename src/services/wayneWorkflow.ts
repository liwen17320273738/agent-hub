export type AgentStageId = 'discovery' | 'prd' | 'build' | 'qa' | 'retro'

export type AgentStageStatus = 'pending' | 'active' | 'done' | 'blocked'

export interface AgentStageMeta {
  id: AgentStageId
  label: string
  ownerAgentId: string
  ownerLabel: string
  deliverable: string
  deliveryDocName: string
  description: string
  recommendedModel: string
}

export interface AgentStageState extends AgentStageMeta {
  status: AgentStageStatus
  updatedAt: number
}

export interface AgentHandoffRecord {
  id: string
  fromAgentId: string
  toAgentId: string
  stageId: AgentStageId
  note: string
  recommendedModel: string
  createdAt: number
}

export interface AgentWorkflow {
  id: string
  title: string
  goal: string
  currentStageId: AgentStageId
  stages: AgentStageState[]
  handoffs: AgentHandoffRecord[]
  createdAt: number
  updatedAt: number
}

export const Agent_STAGE_ORDER: AgentStageId[] = ['discovery', 'prd', 'build', 'qa', 'retro']

export const Agent_STAGE_META: AgentStageMeta[] = [
  {
    id: 'discovery',
    label: '需求发现',
    ownerAgentId: 'Agent-orchestrator',
    ownerLabel: 'Agent Hub 总控',
    deliverable: '阶段判断 / 下一步动作',
    deliveryDocName: '01-prd.md',
    description: '判断当前任务处于哪个阶段，识别缺失产物和下一步最小动作。',
    recommendedModel: 'Opus 4.6',
  },
  {
    id: 'prd',
    label: 'PRD 定义',
    ownerAgentId: 'Agent-product-manager',
    ownerLabel: '产品经理',
    deliverable: '01-prd.md',
    deliveryDocName: '01-prd.md',
    description: '把需求整理成目标、范围、非目标、用户故事和验收标准。',
    recommendedModel: 'GPT-4.5',
  },
  {
    id: 'build',
    label: '开发实现',
    ownerAgentId: 'Agent-developer',
    ownerLabel: '开发工程师',
    deliverable: '实现方案 / 代码改动',
    deliveryDocName: '04-implementation-notes.md',
    description: '根据确认后的需求输出最小实现方案、修改点和验证步骤。',
    recommendedModel: 'Sonnet 4.6',
  },
  {
    id: 'qa',
    label: '质量验证',
    ownerAgentId: 'Agent-qa-lead',
    ownerLabel: 'QA 负责人',
    deliverable: '测试计划 / 风险结论',
    deliveryDocName: '05-test-report.md',
    description: '基于需求和改动做风险导向验证，并输出 PASS / NEEDS WORK 结论。',
    recommendedModel: 'Gemini 4',
  },
  {
    id: 'retro',
    label: '复盘收口',
    ownerAgentId: 'Agent-orchestrator',
    ownerLabel: 'Agent Hub 总控',
    deliverable: '复盘 / 下一步建议',
    deliveryDocName: '06-acceptance.md',
    description: '收敛本轮结果、复盘缺口，并决定下一轮是继续还是关闭。',
    recommendedModel: 'Opus 4.6',
  },
]

export function createAgentStages(now = Date.now()): AgentStageState[] {
  return Agent_STAGE_META.map((meta, index) => ({
    ...meta,
    status: index === 0 ? 'active' : 'pending',
    updatedAt: now,
  }))
}

export function stageMetaById(id: AgentStageId): AgentStageMeta {
  const hit = Agent_STAGE_META.find((item) => item.id === id)
  if (!hit) throw new Error(`Unknown stage: ${id}`)
  return hit
}

export function nextAgentStage(id: AgentStageId): AgentStageId | null {
  const index = Agent_STAGE_ORDER.indexOf(id)
  if (index < 0 || index === Agent_STAGE_ORDER.length - 1) return null
  return Agent_STAGE_ORDER[index + 1]
}

export function inferPrimaryStageByAgent(agentId: string): AgentStageId | null {
  const hit = Agent_STAGE_META.find((item) => item.ownerAgentId === agentId)
  return hit?.id ?? null
}
