export interface ToolBinding {
  name: string
  description: string
  permissions: ('read' | 'write' | 'execute' | 'network')[]
}

export interface AgentConfig {
  id: string
  name: string
  title: string
  icon: string
  color: string
  description: string
  systemPrompt: string
  quickPrompts: string[]
  category: 'core' | 'support' | 'pipeline'
  pipelineRole?: PipelineRole
  tools?: ToolBinding[]
  skills?: string[]
  modelPreference?: {
    planning?: string
    execution?: string
  }
  verificationStrategy?: {
    type: 'test' | 'schema' | 'llm-review' | 'none'
  }
  maxConcurrentTasks?: number
}

export type PipelineRole =
  | 'gateway'
  | 'orchestrator'
  | 'product-manager'
  | 'developer'
  | 'executor'
  | 'qa-lead'
  | 'ops'

export interface PipelineTask {
  id: string
  title: string
  description: string
  source: 'feishu' | 'qq' | 'web' | 'api'
  sourceMessageId?: string
  sourceUserId?: string
  status: 'active' | 'paused' | 'done' | 'cancelled' | 'failed' | 'awaiting_final_acceptance'
  currentStageId: string
  template?: string | null
  repoUrl?: string | null
  projectPath?: string | null
  stages: PipelineStageState[]
  artifacts: TaskArtifact[]
  qualityGateConfig?: Record<string, unknown> | null
  overallQualityScore?: number | null
  // Final acceptance terminus — see backend migration c2d3e4f5a6b7.
  finalAcceptanceStatus?: 'pending' | 'accepted' | 'rejected' | null
  finalAcceptanceBy?: string | null
  finalAcceptanceAt?: number | null
  finalAcceptanceFeedback?: string | null
  autoFinalAccept?: boolean | null
  createdBy: string
  createdAt: number
  updatedAt: number
}

export interface PipelineStageState {
  id: string
  label: string
  status: 'pending' | 'active' | 'done' | 'blocked' | 'reviewing' | 'rejected' | 'awaiting_approval'
  ownerRole: string
  startedAt: number | null
  completedAt: number | null
  output: string | null
  reviewStatus?: 'approved' | 'rejected' | null
  reviewerFeedback?: string | null
  reviewerAgent?: string | null
  reviewAttempts?: number
  approvalId?: string | null
  verifyStatus?: 'pass' | 'warn' | 'fail' | null
  verifyChecks?: Array<{ name: string; status: string; message?: string }> | null
  qualityScore?: number | null
  gateStatus?: 'passed' | 'warning' | 'failed' | 'bypassed' | 'pending' | null
  gateScore?: number | null
  gateDetails?: {
    checks?: Array<{ name: string; category: string; status: string; score: number; message: string }>
    suggestions?: string[]
    block_reason?: string | null
    override?: { by: string; reason: string }
  } | null
}

export interface TaskArtifact {
  id: string
  type: string
  name: string
  content: string
  stageId: string
  metadata?: Record<string, unknown>
  createdAt: number
}

export interface PipelineEvent {
  event: string
  data: unknown
  timestamp: number
}

export interface SubtaskInfo {
  id: string
  title: string
  role: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  output?: string
  error?: string
  startTime?: number
  endTime?: number
}

export const PIPELINE_EVENTS = {
  TASK_CREATED: 'task:created',
  TASK_UPDATED: 'task:updated',
  TASK_STAGE_ADVANCED: 'task:stage-advanced',
  TASK_REJECTED: 'task:rejected',
  TASK_DELETED: 'task:deleted',
  STAGE_QUEUED: 'stage:queued',
  STAGE_PROCESSING: 'stage:processing',
  STAGE_COMPLETED: 'stage:completed',
  STAGE_ERROR: 'stage:error',
  PIPELINE_AUTO_START: 'pipeline:auto-start',
  PIPELINE_AUTO_COMPLETED: 'pipeline:auto-completed',
  PIPELINE_AUTO_PAUSED: 'pipeline:auto-paused',
  PIPELINE_AUTO_ERROR: 'pipeline:auto-error',
  STAGE_QUALITY_GATE: 'stage:quality-gate',
  STAGE_GATE_OVERRIDDEN: 'stage:gate-overridden',
  PIPELINE_SMART_START: 'pipeline:smart-start',
  PIPELINE_SMART_COMPLETED: 'pipeline:smart-completed',
  PIPELINE_SMART_ERROR: 'pipeline:smart-error',
  SUBTASK_START: 'subtask:start',
  SUBTASK_COMPLETED: 'subtask:completed',
  SUBTASK_FAILED: 'subtask:failed',
  LEAD_AGENT_ANALYZING: 'lead-agent:analyzing',
  LEAD_AGENT_PLAN_READY: 'lead-agent:plan-ready',
  LEAD_AGENT_ERROR: 'lead-agent:error',
  EXECUTOR_STARTED: 'executor:started',
  EXECUTOR_COMPLETED: 'executor:completed',
  EXECUTOR_ERROR: 'executor:error',
} as const

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  agentId: string
}

export interface Conversation {
  id: string
  agentId: string
  title: string
  messages: ChatMessage[]
  createdAt: number
  updatedAt: number
  /** 用户触发生成的早前对话摘要，会并入系统侧上下文 */
  summary?: string
  /** 企业模式：服务端乐观锁版本，PATCH 需携带 expectedRevision */
  revision?: number
}

export interface ConversationSearchHit {
  conversationId: string
  agentId: string
  title: string
  snippet: string
}
