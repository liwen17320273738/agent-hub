import type { PipelineTask, PipelineStageState } from '@/agents/types'

const STORAGE_KEY = 'agent-hub-pipeline-tasks'

const PIPELINE_STAGES = [
  { id: 'intake', label: '需求接入', ownerRole: 'openclaw' },
  { id: 'planning', label: 'PRD 定义', ownerRole: 'product-manager' },
  { id: 'architecture', label: '技术方案', ownerRole: 'developer' },
  { id: 'building', label: '开发实现', ownerRole: 'executor' },
  { id: 'testing', label: '质量验证', ownerRole: 'qa-lead' },
  { id: 'reviewing', label: '验收评审', ownerRole: 'orchestrator' },
  { id: 'done', label: '完成', ownerRole: 'system' },
]

const STAGE_IDS = PIPELINE_STAGES.map((s) => s.id)

function loadTasks(): PipelineTask[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function persistTasks(tasks: PipelineTask[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(tasks))
}

function generateId(): string {
  return crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function createStages(now: number): PipelineStageState[] {
  return PIPELINE_STAGES.map((s, i) => ({
    id: s.id,
    label: s.label,
    status: i === 0 ? 'active' : 'pending',
    ownerRole: s.ownerRole,
    startedAt: i === 0 ? now : null,
    completedAt: null,
    output: null,
  }))
}

export function localFetchTasks(filters?: {
  status?: string
  stage?: string
  source?: string
}): PipelineTask[] {
  let tasks = loadTasks()
  if (filters?.status) tasks = tasks.filter((t) => t.status === filters.status)
  if (filters?.stage) tasks = tasks.filter((t) => t.currentStageId === filters.stage)
  if (filters?.source) tasks = tasks.filter((t) => t.source === filters.source)
  return tasks.sort((a, b) => b.updatedAt - a.updatedAt)
}

export function localFetchTask(id: string): PipelineTask | null {
  return loadTasks().find((t) => t.id === id) ?? null
}

export function localCreateTask(payload: {
  title: string
  description?: string
  source?: string
}): PipelineTask {
  const now = Date.now()
  const task: PipelineTask = {
    id: generateId(),
    title: payload.title,
    description: payload.description || '',
    source: (payload.source || 'web') as PipelineTask['source'],
    status: 'active',
    currentStageId: 'intake',
    stages: createStages(now),
    artifacts: [],
    createdBy: 'local',
    createdAt: now,
    updatedAt: now,
  }
  const tasks = loadTasks()
  tasks.unshift(task)
  persistTasks(tasks)
  return task
}

export function localAdvanceTask(id: string, output?: string): PipelineTask {
  const tasks = loadTasks()
  const idx = tasks.findIndex((t) => t.id === id)
  if (idx < 0) throw new Error('任务不存在')

  const task = tasks[idx]
  const currentIndex = STAGE_IDS.indexOf(task.currentStageId)
  if (currentIndex < 0 || currentIndex >= STAGE_IDS.length - 1) {
    throw new Error('已在最终阶段')
  }

  const now = Date.now()
  const nextStageId = STAGE_IDS[currentIndex + 1]

  if (output) {
    const stage = task.stages.find((s) => s.id === task.currentStageId)
    if (stage) stage.output = output
  }

  const currentStage = task.stages.find((s) => s.id === task.currentStageId)
  if (currentStage) {
    currentStage.status = 'done'
    currentStage.completedAt = now
  }

  const nextStage = task.stages.find((s) => s.id === nextStageId)
  if (nextStage) {
    nextStage.status = 'active'
    nextStage.startedAt = now
  }

  task.currentStageId = nextStageId
  if (nextStageId === 'done') task.status = 'done'
  task.updatedAt = now

  tasks[idx] = task
  persistTasks(tasks)
  return task
}

export function localRejectTask(id: string, targetStageId: string, _reason?: string): PipelineTask {
  const tasks = loadTasks()
  const idx = tasks.findIndex((t) => t.id === id)
  if (idx < 0) throw new Error('任务不存在')

  const task = tasks[idx]
  const targetIndex = STAGE_IDS.indexOf(targetStageId)
  const currentIndex = STAGE_IDS.indexOf(task.currentStageId)
  if (targetIndex < 0 || targetIndex >= currentIndex) {
    throw new Error('只能打回到之前的阶段')
  }

  const now = Date.now()
  task.stages = task.stages.map((s) => {
    const sIdx = STAGE_IDS.indexOf(s.id)
    if (sIdx === targetIndex) {
      return { ...s, status: 'active' as const, startedAt: now, completedAt: null, output: null }
    }
    if (sIdx > targetIndex) {
      return { ...s, status: 'pending' as const, startedAt: null, completedAt: null, output: null }
    }
    return s
  })
  task.currentStageId = targetStageId
  task.updatedAt = now

  tasks[idx] = task
  persistTasks(tasks)
  return task
}

export function localDeleteTask(id: string): void {
  const tasks = loadTasks().filter((t) => t.id !== id)
  persistTasks(tasks)
}

export function localUpdateTask(
  id: string,
  updates: Partial<Pick<PipelineTask, 'title' | 'description' | 'status'>>,
): PipelineTask {
  const tasks = loadTasks()
  const idx = tasks.findIndex((t) => t.id === id)
  if (idx < 0) throw new Error('任务不存在')

  const task = { ...tasks[idx], ...updates, updatedAt: Date.now() }
  tasks[idx] = task
  persistTasks(tasks)
  return task
}
