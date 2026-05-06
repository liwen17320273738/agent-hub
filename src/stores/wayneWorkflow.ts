import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  createAgentStages,
  inferPrimaryStageByAgent,
  nextAgentStage,
  stageMetaById,
  type AgentHandoffRecord,
  type AgentStageId,
  type AgentStageStatus,
  type AgentWorkflow,
} from '@/services/wayneWorkflow'

const STORAGE_KEY = 'Agent-stack-workflow'

function loadWorkflow(): AgentWorkflow | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    return JSON.parse(raw) as AgentWorkflow
  } catch {
    return null
  }
}

function persistWorkflow(workflow: AgentWorkflow | null) {
  if (!workflow) {
    localStorage.removeItem(STORAGE_KEY)
    return
  }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(workflow))
}

export const useAgentWorkflowStore = defineStore('Agent-workflow', () => {
  const workflow = ref<AgentWorkflow | null>(loadWorkflow())

  const hasWorkflow = computed(() => !!workflow.value)
  const currentStage = computed(() =>
    workflow.value?.stages.find((stage) => stage.id === workflow.value?.currentStageId) ?? null,
  )

  function startWorkflow(title: string, goal: string) {
    const now = Date.now()
    workflow.value = {
      id: crypto.randomUUID(),
      title: title.trim() || '新工作流',
      goal: goal.trim(),
      currentStageId: 'discovery',
      stages: createAgentStages(now),
      handoffs: [],
      createdAt: now,
      updatedAt: now,
    }
    persistWorkflow(workflow.value)
  }

  function updateMetadata(partial: { title?: string; goal?: string }) {
    if (!workflow.value) return
    if (typeof partial.title === 'string') workflow.value.title = partial.title
    if (typeof partial.goal === 'string') workflow.value.goal = partial.goal
    workflow.value.updatedAt = Date.now()
    persistWorkflow(workflow.value)
  }

  function setStageStatus(stageId: AgentStageId, status: AgentStageStatus) {
    if (!workflow.value) return
    const stage = workflow.value.stages.find((item) => item.id === stageId)
    if (!stage) return
    stage.status = status
    stage.updatedAt = Date.now()
    workflow.value.updatedAt = Date.now()
    persistWorkflow(workflow.value)
  }

  function setCurrentStage(stageId: AgentStageId) {
    if (!workflow.value) return
    workflow.value.currentStageId = stageId
    workflow.value.stages.forEach((stage) => {
      if (stage.id === stageId && stage.status === 'pending') {
        stage.status = 'active'
        stage.updatedAt = Date.now()
      }
    })
    workflow.value.updatedAt = Date.now()
    persistWorkflow(workflow.value)
  }

  function completeCurrentStage(note?: string) {
    if (!workflow.value) return
    const stageId = workflow.value.currentStageId
    setStageStatus(stageId, 'done')
    const next = nextAgentStage(stageId)
    if (next) {
      setCurrentStage(next)
      if (note?.trim()) {
        addHandoff(stageId, stageMetaById(next).ownerAgentId, note.trim())
      }
    }
  }

  function blockCurrentStage(note?: string) {
    if (!workflow.value) return
    const stageId = workflow.value.currentStageId
    setStageStatus(stageId, 'blocked')
    if (note?.trim()) {
      addHandoff(stageId, stageMetaById(stageId).ownerAgentId, `阻塞：${note.trim()}`)
    }
  }

  function addHandoff(stageId: AgentStageId, toAgentId: string, note: string) {
    if (!workflow.value) return
    const stage = stageMetaById(stageId)
    const record: AgentHandoffRecord = {
      id: crypto.randomUUID(),
      fromAgentId: stage.ownerAgentId,
      toAgentId,
      stageId,
      note: note.trim(),
      recommendedModel: stage.recommendedModel,
      createdAt: Date.now(),
    }
    workflow.value.handoffs.unshift(record)
    workflow.value.updatedAt = Date.now()
    persistWorkflow(workflow.value)
  }

  function handoffToAgent(agentId: string, note: string) {
    if (!workflow.value) return
    addHandoff(workflow.value.currentStageId, agentId, note)
  }

  function inferStageForAgent(agentId: string): AgentStageId | null {
    return inferPrimaryStageByAgent(agentId)
  }

  function resetWorkflow() {
    workflow.value = null
    persistWorkflow(null)
  }

  return {
    workflow,
    hasWorkflow,
    currentStage,
    startWorkflow,
    updateMetadata,
    setStageStatus,
    setCurrentStage,
    completeCurrentStage,
    blockCurrentStage,
    addHandoff,
    handoffToAgent,
    inferStageForAgent,
    resetWorkflow,
  }
})
