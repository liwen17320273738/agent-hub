/**
 * Workflow builder serialization + topology helpers.
 *
 * The builder UI (Vue Flow) edits a graph of `BuilderNode`s. The
 * BACKEND speaks a different shape: `DAGStage(stage_id, label, role,
 * depends_on=[...])` lives in `dag_orchestrator.py`. These helpers
 * convert between the two and guard against the two non-obvious
 * failure modes a UI builder always hits:
 *
 *   1. The user draws a cycle (A → B → A). DAG orchestrator silently
 *      deadlocks — better to refuse the save with a clear error.
 *   2. Two nodes share a `stage_id`. The orchestrator picks one of
 *      them at random — refuse with "duplicate stage id".
 *
 * Keep this file pure (no Vue, no localStorage) so it's trivially
 * unit-testable and reusable from a future CLI / import script.
 */

/** Builder-side node shape. ``id`` is the Vue Flow node id (random)
 *  while ``data.stageId`` is the human-meaningful identifier the
 *  backend stores in PipelineStage rows. */
export interface BuilderNode {
  id: string
  position: { x: number; y: number }
  data: {
    stageId: string         // == DAGStage.stage_id (e.g. "development")
    label: string           // human-friendly title
    role: string            // == DAGStage.role  (e.g. "developer")
    model?: string | null
    qualityGateMin?: number // 0..1, optional
    rejectAction?: 'self-heal' | 'escalate' | 'manual'
    onFailure?: 'halt' | 'rollback' | 'skip'
    humanGate?: boolean
  }
}

/** Vue Flow edge subset we care about. Source/target are node ids. */
export interface BuilderEdge {
  id: string
  source: string
  target: string
}

/** Compact JSON shape we persist (localStorage / future backend).
 *  Forwards-compatible: unknown fields on import are kept. */
export interface WorkflowDoc {
  version: 1
  name: string
  nodes: BuilderNode[]
  edges: BuilderEdge[]
  /** Optional template lineage so we can show "based on: web_app". */
  baseTemplate?: string | null
  updatedAt: number
}

/** Backend DAG stage shape (mirror of `dag_orchestrator.DAGStage`). */
export interface BackendStage {
  stageId: string
  label: string
  role: string
  dependsOn: string[]
  model?: string | null
  qualityGateMin?: number
  rejectAction?: string
  onFailure?: string
  humanGate?: boolean
}

/** Snake-case API shape for ``POST /pipeline/tasks`` ``custom_stages``
 *  and ``POST /pipeline/tasks/{id}/dag-run`` ``custom_stages``. The
 *  backend's ``CustomStageSpec`` mirror lives in
 *  ``src/services/pipelineApi.ts``. */
export interface CustomStageApiSpec {
  stage_id: string
  label: string
  role: string
  depends_on: string[]
  max_retries?: number
  on_failure?: 'halt' | 'rollback' | 'skip'
  human_gate?: boolean
  model_override?: string | null
  quality_gate_min?: number | null
}

/** Convert ``builderToStages()`` output to the snake-case shape the
 *  ``/pipeline/tasks`` POST body expects. Map ``rejectAction`` to a
 *  ``max_retries`` heuristic: ``self-heal`` (default) → 1 retry budget
 *  for the orchestrator's reject loop; ``escalate`` / ``manual`` → 0. */
export function stagesToCustomApiPayload(
  stages: BackendStage[],
): CustomStageApiSpec[] {
  return stages.map((s) => ({
    stage_id: s.stageId,
    label: s.label,
    role: s.role,
    depends_on: s.dependsOn,
    max_retries:
      s.rejectAction === 'self-heal' || !s.rejectAction ? 1 : 0,
    on_failure: (s.onFailure as 'halt' | 'rollback' | 'skip') || 'halt',
    human_gate: !!s.humanGate,
    model_override: s.model || null,
    quality_gate_min:
      typeof s.qualityGateMin === 'number' ? s.qualityGateMin : null,
  }))
}

// ─────────────────────────────────────────────────────────────────────
// Cycle detection — Kahn's algorithm. We refuse to save (and to
// "Run") a graph with a cycle because the DAG orchestrator deadlocks
// on one (it's waiting for a dep that's waiting for itself). The
// returned list is a hint for the UI to highlight the offending nodes.
// ─────────────────────────────────────────────────────────────────────

export interface TopoCheck {
  ok: boolean
  /** Stage ids involved in the cycle, in arbitrary order. */
  cycleNodes: string[]
  /** Topological order if ``ok``; empty otherwise. */
  order: string[]
}

export function checkTopology(
  nodes: BuilderNode[],
  edges: BuilderEdge[],
): TopoCheck {
  const idToStage = new Map<string, string>()
  for (const n of nodes) idToStage.set(n.id, n.data.stageId)

  const indegree = new Map<string, number>()
  const adj = new Map<string, string[]>()
  for (const n of nodes) {
    indegree.set(n.id, 0)
    adj.set(n.id, [])
  }
  for (const e of edges) {
    if (!indegree.has(e.target) || !adj.has(e.source)) continue
    indegree.set(e.target, (indegree.get(e.target) || 0) + 1)
    adj.get(e.source)!.push(e.target)
  }

  const queue: string[] = []
  for (const [id, deg] of indegree) if (deg === 0) queue.push(id)

  const order: string[] = []
  while (queue.length) {
    const id = queue.shift()!
    order.push(idToStage.get(id) || id)
    for (const next of adj.get(id) || []) {
      const d = (indegree.get(next) || 0) - 1
      indegree.set(next, d)
      if (d === 0) queue.push(next)
    }
  }

  if (order.length === nodes.length) {
    return { ok: true, cycleNodes: [], order }
  }
  // Whatever still has indegree > 0 is part of (or downstream of) a cycle.
  const stuck: string[] = []
  for (const [id, deg] of indegree) {
    if (deg > 0) stuck.push(idToStage.get(id) || id)
  }
  return { ok: false, cycleNodes: stuck, order: [] }
}

// ─────────────────────────────────────────────────────────────────────
// Conversion: Vue Flow graph ↔ backend DAGStage list
// ─────────────────────────────────────────────────────────────────────

export interface ConversionError {
  code: 'cycle' | 'duplicate-stage-id' | 'empty'
  message: string
  details?: unknown
}

export function builderToStages(
  nodes: BuilderNode[],
  edges: BuilderEdge[],
): { ok: true; stages: BackendStage[] } | { ok: false; error: ConversionError } {
  if (nodes.length === 0) {
    return { ok: false, error: { code: 'empty', message: '至少需要一个阶段' } }
  }

  // Refuse duplicate stage_ids — backend would silently overwrite the
  // first one's progress with the second's, and the bug surfaces as
  // "the wrong stage just ran". Catch it here.
  const seen = new Set<string>()
  const dupes: string[] = []
  for (const n of nodes) {
    if (seen.has(n.data.stageId)) dupes.push(n.data.stageId)
    seen.add(n.data.stageId)
  }
  if (dupes.length) {
    return {
      ok: false,
      error: {
        code: 'duplicate-stage-id',
        message: `阶段 ID 重复: ${dupes.join(', ')}`,
        details: dupes,
      },
    }
  }

  const topo = checkTopology(nodes, edges)
  if (!topo.ok) {
    return {
      ok: false,
      error: {
        code: 'cycle',
        message: `检测到环依赖: ${topo.cycleNodes.join(' ↔ ')}`,
        details: topo.cycleNodes,
      },
    }
  }

  const idToStage = new Map<string, string>()
  for (const n of nodes) idToStage.set(n.id, n.data.stageId)

  // depends_on for stage X = source.stageId of every edge whose target == X.id
  const depsByStage = new Map<string, string[]>()
  for (const n of nodes) depsByStage.set(n.data.stageId, [])
  for (const e of edges) {
    const src = idToStage.get(e.source)
    const tgt = idToStage.get(e.target)
    if (src && tgt) depsByStage.get(tgt)!.push(src)
  }

  const stages: BackendStage[] = nodes.map((n) => ({
    stageId: n.data.stageId,
    label: n.data.label,
    role: n.data.role,
    dependsOn: depsByStage.get(n.data.stageId) || [],
    model: n.data.model || null,
    qualityGateMin: n.data.qualityGateMin,
    rejectAction: n.data.rejectAction,
    onFailure: n.data.onFailure,
    humanGate: n.data.humanGate,
  }))

  return { ok: true, stages }
}

/** Hydrate the builder from a backend template (the shape returned by
 *  `GET /api/pipeline/templates`). Auto-lays out nodes left-to-right
 *  by topological depth so the first paint isn't a tangled mess. */
export function templateToBuilder(template: {
  stages: Array<{ id: string; label: string; role: string; dependsOn: string[] }>
}): { nodes: BuilderNode[]; edges: BuilderEdge[] } {
  const stages = template.stages
  // Compute depth = longest path from any root to this node.
  // Simple BFS: depth = max(deps.depth) + 1, roots = 0.
  const depth = new Map<string, number>()
  const byId = new Map<string, typeof stages[number]>()
  for (const s of stages) byId.set(s.id, s)

  const resolve = (id: string, stack: Set<string>): number => {
    if (depth.has(id)) return depth.get(id)!
    if (stack.has(id)) return 0 // cyclic input — shouldn't happen but be safe
    stack.add(id)
    const s = byId.get(id)
    const d = !s || s.dependsOn.length === 0
      ? 0
      : 1 + Math.max(...s.dependsOn.map((d) => resolve(d, stack)))
    depth.set(id, d)
    stack.delete(id)
    return d
  }
  for (const s of stages) resolve(s.id, new Set())

  // Bucket stages by depth so we can stack siblings vertically.
  const buckets = new Map<number, string[]>()
  for (const s of stages) {
    const d = depth.get(s.id) || 0
    if (!buckets.has(d)) buckets.set(d, [])
    buckets.get(d)!.push(s.id)
  }

  const COL_W = 240
  const ROW_H = 130
  const idMap = new Map<string, string>() // stageId → node id
  const nodes: BuilderNode[] = stages.map((s) => {
    const d = depth.get(s.id) || 0
    const siblings = buckets.get(d) || []
    const row = siblings.indexOf(s.id)
    const colHeight = siblings.length
    const id = `n_${s.id}_${Math.random().toString(36).slice(2, 8)}`
    idMap.set(s.id, id)
    return {
      id,
      position: {
        x: 60 + d * COL_W,
        y: 60 + row * ROW_H - ((colHeight - 1) * ROW_H) / 2 + 220,
      },
      data: {
        stageId: s.id,
        label: s.label,
        role: s.role,
        rejectAction: 'self-heal',
        onFailure: 'halt',
      },
    }
  })

  const edges: BuilderEdge[] = []
  for (const s of stages) {
    for (const dep of s.dependsOn) {
      const src = idMap.get(dep)
      const tgt = idMap.get(s.id)
      if (src && tgt) {
        edges.push({ id: `e_${src}_${tgt}`, source: src, target: tgt })
      }
    }
  }
  return { nodes, edges }
}

// ─────────────────────────────────────────────────────────────────────
// Persistence (localStorage for now; same shape as future backend POST)
// ─────────────────────────────────────────────────────────────────────

const STORAGE_KEY = 'agent-hub:workflow-builder:doc:v1'

export function saveDocLocal(doc: WorkflowDoc): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(doc))
  } catch {
    // Storage full / disabled — silent; the user can still export JSON.
  }
}

export function loadDocLocal(): WorkflowDoc | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (parsed && parsed.version === 1) return parsed as WorkflowDoc
    return null
  } catch {
    return null
  }
}

export function exportDocAsJson(doc: WorkflowDoc): string {
  return JSON.stringify(doc, null, 2)
}

export function importDocFromJson(raw: string): WorkflowDoc | null {
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || parsed.version !== 1) return null
    if (!Array.isArray(parsed.nodes) || !Array.isArray(parsed.edges)) return null
    return parsed as WorkflowDoc
  } catch {
    return null
  }
}

// ─────────────────────────────────────────────────────────────────────
// Role catalogue — mirrors the agent roles known to the orchestrator.
// Keeping this client-side for now (matches the static set in
// `dag_orchestrator.PIPELINE_TEMPLATES`); when we add custom roles
// per-org we'll fetch from a `/api/agents/roles` endpoint instead.
// ─────────────────────────────────────────────────────────────────────

export interface RoleDef {
  value: string
  label: string
  emoji: string
}

export const KNOWN_ROLES: RoleDef[] = [
  { value: 'product-manager', label: '产品经理', emoji: '📋' },
  { value: 'designer',        label: 'UI/UX 设计', emoji: '🎨' },
  { value: 'architect',       label: '架构师',     emoji: '🏛️' },
  { value: 'developer',       label: '开发',       emoji: '💻' },
  { value: 'qa-lead',         label: 'QA',         emoji: '🧪' },
  { value: 'security',        label: '安全审计',   emoji: '🛡️' },
  { value: 'legal',           label: '法务合规',   emoji: '⚖️' },
  { value: 'finance',         label: '财务评估',   emoji: '💰' },
  { value: 'data',            label: '数据建模',   emoji: '📊' },
  { value: 'marketing',       label: '增长营销',   emoji: '📣' },
  { value: 'acceptance',      label: '验收评审',   emoji: '✅' },
  { value: 'devops',          label: 'DevOps',     emoji: '🚀' },
]

export function roleLabel(value: string): string {
  return KNOWN_ROLES.find((r) => r.value === value)?.label || value
}

export function roleEmoji(value: string): string {
  return KNOWN_ROLES.find((r) => r.value === value)?.emoji || '🤖'
}
