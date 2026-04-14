import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { PipelineTask, PipelineEvent } from '@/agents/types'
import * as api from '@/services/pipelineApi'

export const usePipelineStore = defineStore('pipeline', () => {
  const tasks = ref<PipelineTask[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const eventLog = ref<PipelineEvent[]>([])
  let unsubscribe: (() => void) | null = null

  const activeTasks = computed(() => tasks.value.filter((t) => t.status === 'active'))
  const doneTasks = computed(() => tasks.value.filter((t) => t.status === 'done'))

  const tasksByStage = computed(() => {
    const map: Record<string, PipelineTask[]> = {}
    for (const task of tasks.value) {
      const stage = task.currentStageId
      if (!map[stage]) map[stage] = []
      map[stage].push(task)
    }
    return map
  })

  async function loadTasks(filters?: { status?: string; stage?: string; source?: string }) {
    loading.value = true
    error.value = null
    try {
      tasks.value = await api.fetchTasks(filters)
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function createTask(payload: { title: string; description?: string; source?: string }) {
    const task = await api.createTask(payload)
    tasks.value.unshift(task)
    return task
  }

  async function advanceTask(id: string, output?: string) {
    const task = await api.advanceTask(id, output)
    replaceTask(task)
    return task
  }

  async function rejectTask(id: string, targetStageId: string, reason?: string) {
    const task = await api.rejectTask(id, targetStageId, reason)
    replaceTask(task)
    return task
  }

  async function removeTask(id: string) {
    await api.deleteTask(id)
    tasks.value = tasks.value.filter((t) => t.id !== id)
  }

  function replaceTask(updated: PipelineTask) {
    const idx = tasks.value.findIndex((t) => t.id === updated.id)
    if (idx >= 0) {
      tasks.value[idx] = updated
    } else {
      tasks.value.unshift(updated)
    }
  }

  function startEventStream() {
    if (unsubscribe) return
    unsubscribe = api.subscribePipelineEvents((event) => {
      eventLog.value.push(event)
      if (eventLog.value.length > 200) eventLog.value = eventLog.value.slice(-100)

      if (
        event.event === 'task:created' ||
        event.event === 'task:updated' ||
        event.event === 'task:stage-advanced' ||
        event.event === 'task:rejected'
      ) {
        const taskData = (event.data as Record<string, unknown>)?.task as PipelineTask | undefined
        if (taskData) replaceTask(taskData)
      }

      if (event.event === 'task:deleted') {
        const deletedId = (event.data as Record<string, unknown>)?.id as string
        if (deletedId) tasks.value = tasks.value.filter((t) => t.id !== deletedId)
      }
    })
  }

  function stopEventStream() {
    unsubscribe?.()
    unsubscribe = null
  }

  return {
    tasks,
    loading,
    error,
    eventLog,
    activeTasks,
    doneTasks,
    tasksByStage,
    loadTasks,
    createTask,
    advanceTask,
    rejectTask,
    removeTask,
    startEventStream,
    stopEventStream,
  }
})
