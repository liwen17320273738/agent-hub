/**
 * Server CRUD for the Workflow Builder save slot.
 *
 * Mirrors backend ``/api/workflows`` (see backend/app/api/workflows.py).
 * The doc body is the verbatim WorkflowDoc shape from
 * ``./workflowBuilder.ts`` — no transformation, no schema split.
 */
import type { WorkflowDoc } from './workflowBuilder'
import { getAuthToken } from './api'

export interface SavedWorkflow {
  id: string
  name: string
  description: string
  doc: WorkflowDoc
  createdBy: string
  orgId: string | null
  createdAt: string | null
  updatedAt: string | null
}

function getBaseUrl(): string {
  return import.meta.env.VITE_API_BASE || '/api'
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getAuthToken()
  const isEnterprise = import.meta.env.VITE_ENTERPRISE === 'true'
  const authHeaders: Record<string, string> = token
    ? { Authorization: `Bearer ${token}` }
    : {}

  const res = await fetch(`${getBaseUrl()}${path}`, {
    credentials: isEnterprise ? 'include' : 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders,
      ...(options?.headers || {}),
    },
    ...options,
  })

  if (res.status === 204) {
    return undefined as unknown as T
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }))
    throw new Error(body.detail || body.error || `HTTP ${res.status}`)
  }
  return res.json()
}

export async function listWorkflows(): Promise<SavedWorkflow[]> {
  const data = await apiFetch<{ workflows: SavedWorkflow[] }>('/workflows/')
  return data.workflows ?? []
}

export async function fetchWorkflow(id: string): Promise<SavedWorkflow> {
  const data = await apiFetch<{ workflow: SavedWorkflow }>(
    `/workflows/${id}`,
  )
  return data.workflow
}

export async function createWorkflow(payload: {
  name: string
  description?: string
  doc: WorkflowDoc
}): Promise<SavedWorkflow> {
  const data = await apiFetch<{ workflow: SavedWorkflow }>('/workflows/', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return data.workflow
}

export async function updateWorkflow(
  id: string,
  patch: Partial<{ name: string; description: string; doc: WorkflowDoc }>,
): Promise<SavedWorkflow> {
  const data = await apiFetch<{ workflow: SavedWorkflow }>(
    `/workflows/${id}`,
    { method: 'PATCH', body: JSON.stringify(patch) },
  )
  return data.workflow
}

export async function deleteWorkflow(id: string): Promise<void> {
  await apiFetch<void>(`/workflows/${id}`, { method: 'DELETE' })
}
