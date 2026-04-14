let store = null

export function initTaskStore(dbStore) {
  store = dbStore
}

export async function getAllTasks(filters = {}) {
  if (!store) return []
  return store.listPipelineTasks(filters)
}

export async function getTask(id) {
  if (!store) return null
  return store.getPipelineTask(id)
}

export async function saveTask(task) {
  if (!store) return task
  const existing = await store.getPipelineTask(task.id)
  if (existing) {
    return store.updatePipelineTask(task)
  }
  return store.insertPipelineTask(task)
}

export async function deleteTask(id) {
  if (!store) return false
  return store.deletePipelineTask(id)
}
