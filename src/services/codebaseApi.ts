/**
 * Codebase semantic-index API — wraps `/api/codebase/*`.
 *
 * Workflow:
 *   1. reindexProject({ project_dir })  → walks tree, embeds, upserts
 *   2. searchCodebase({ project_id, query }) → top-K hits with cosine score
 *   3. getStats(project_id) → quick counters (chunks / files / model)
 *   4. dropProject(project_id) → purge before a fresh reindex
 *
 * `project_id` defaults to `project_dir` server-side, so for single-snapshot
 * projects you can omit it everywhere except `getStats` / `dropProject`.
 */
import { apiFetch } from './api'

export interface ReindexPayload {
  project_dir: string
  project_id?: string
  max_files?: number
  embedding_model?: string
  embedding_provider?: string
  drop_first?: boolean
}

export interface ReindexResult {
  ok: boolean
  project_id: string
  files_scanned: number
  files_skipped: number
  chunks_new: number
  chunks_skipped_unchanged?: boolean
  embedding_model?: string
  embedding_dim?: number
  tokens_used?: number
  elapsed_ms: number
  error?: string
}

export interface SearchPayload {
  project_id?: string
  project_dir?: string
  query: string
  top_k?: number
  embedding_model?: string
  embedding_provider?: string
}

export interface SearchHit {
  rel_path: string
  start_line: number
  end_line: number
  score: number
  language: string
  symbols: string[]
  preview: string
}

export interface SearchResult {
  ok: boolean
  project_id: string
  query: string
  hits: SearchHit[]
  scanned_chunks?: number
  elapsed_ms?: number
  reason?: string
}

export interface CodebaseStats {
  ok: boolean
  project_id: string
  chunks: number
  files: number
  embedding_model: string
  embedding_dim: number
}

export async function reindexProject(payload: ReindexPayload): Promise<ReindexResult> {
  return apiFetch<ReindexResult>('/codebase/reindex', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function searchCodebase(payload: SearchPayload): Promise<SearchResult> {
  return apiFetch<SearchResult>('/codebase/search', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function getStats(projectId: string): Promise<CodebaseStats> {
  const qs = new URLSearchParams({ project_id: projectId }).toString()
  return apiFetch<CodebaseStats>(`/codebase/stats?${qs}`)
}

export async function dropProject(projectId: string): Promise<{ ok: boolean; deleted: number }> {
  return apiFetch<{ ok: boolean; deleted: number }>(`/codebase/${encodeURIComponent(projectId)}`, {
    method: 'DELETE',
  })
}
