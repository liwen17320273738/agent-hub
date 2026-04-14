import { randomUUID } from 'node:crypto'

export const PIPELINE_STAGES = [
  {
    id: 'intake',
    label: '需求接入',
    ownerRole: 'openclaw',
    description: 'OpenClaw 解析消息意图，结构化需求',
    autoAdvance: true,
  },
  {
    id: 'planning',
    label: 'PRD 定义',
    ownerRole: 'product-manager',
    description: '产品经理整理需求、定义范围和验收标准',
    autoAdvance: false,
  },
  {
    id: 'architecture',
    label: '技术方案',
    ownerRole: 'developer',
    description: '开发工程师输出技术方案和实现路径',
    autoAdvance: false,
  },
  {
    id: 'building',
    label: '开发实现',
    ownerRole: 'executor',
    description: 'Claude Code 在终端执行开发任务',
    autoAdvance: false,
  },
  {
    id: 'testing',
    label: '质量验证',
    ownerRole: 'qa-lead',
    description: 'QA 验证功能、回归、输出测试结论',
    autoAdvance: false,
  },
  {
    id: 'reviewing',
    label: '验收评审',
    ownerRole: 'orchestrator',
    description: '总控评审交付物，决定发布或打回',
    autoAdvance: false,
  },
  {
    id: 'done',
    label: '完成',
    ownerRole: 'system',
    description: '任务完成闭环',
    autoAdvance: false,
  },
]

export const STAGE_IDS = PIPELINE_STAGES.map((s) => s.id)

export const TASK_STATUSES = ['active', 'paused', 'done', 'cancelled']

export const VALID_SOURCES = ['feishu', 'qq', 'web', 'api']

export function createTask({ title, description, source, sourceMessageId, sourceUserId, createdBy }) {
  const now = Date.now()
  const id = randomUUID()

  return {
    id,
    title: title || '未命名任务',
    description: description || '',
    source: VALID_SOURCES.includes(source) ? source : 'web',
    sourceMessageId: sourceMessageId || null,
    sourceUserId: sourceUserId || null,
    status: 'active',
    currentStageId: 'intake',
    stages: PIPELINE_STAGES.map((stage, index) => ({
      id: stage.id,
      label: stage.label,
      status: index === 0 ? 'active' : 'pending',
      ownerRole: stage.ownerRole,
      startedAt: index === 0 ? now : null,
      completedAt: null,
      output: null,
    })),
    artifacts: [],
    createdBy: createdBy || 'system',
    createdAt: now,
    updatedAt: now,
  }
}

export function advanceTask(task) {
  const currentIndex = STAGE_IDS.indexOf(task.currentStageId)
  if (currentIndex < 0 || currentIndex >= STAGE_IDS.length - 1) {
    return { ok: false, error: '已在最终阶段，无法推进' }
  }

  const now = Date.now()
  const nextStageId = STAGE_IDS[currentIndex + 1]
  const stages = task.stages.map((s) => {
    if (s.id === task.currentStageId) {
      return { ...s, status: 'done', completedAt: now }
    }
    if (s.id === nextStageId) {
      return { ...s, status: 'active', startedAt: now }
    }
    return s
  })

  const status = nextStageId === 'done' ? 'done' : task.status

  return {
    ok: true,
    task: {
      ...task,
      currentStageId: nextStageId,
      stages,
      status,
      updatedAt: now,
    },
  }
}

export function rejectTask(task, targetStageId) {
  const targetIndex = STAGE_IDS.indexOf(targetStageId)
  const currentIndex = STAGE_IDS.indexOf(task.currentStageId)
  if (targetIndex < 0 || targetIndex >= currentIndex) {
    return { ok: false, error: '只能打回到之前的阶段' }
  }

  const now = Date.now()
  const stages = task.stages.map((s) => {
    const idx = STAGE_IDS.indexOf(s.id)
    if (idx === targetIndex) {
      return { ...s, status: 'active', startedAt: now, completedAt: null, output: null }
    }
    if (idx > targetIndex) {
      return { ...s, status: 'pending', startedAt: null, completedAt: null, output: null }
    }
    return s
  })

  return {
    ok: true,
    task: {
      ...task,
      currentStageId: targetStageId,
      stages,
      updatedAt: now,
    },
  }
}

export function addArtifact(task, { type, name, content, stageId }) {
  const artifact = {
    id: randomUUID(),
    type,
    name,
    content,
    stageId,
    createdAt: Date.now(),
  }
  return {
    ...task,
    artifacts: [...task.artifacts, artifact],
    updatedAt: Date.now(),
  }
}

export function updateStageOutput(task, stageId, output) {
  const stages = task.stages.map((s) => {
    if (s.id === stageId) return { ...s, output }
    return s
  })
  return { ...task, stages, updatedAt: Date.now() }
}
