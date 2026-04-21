/**
 * Unit coverage for the Workflow Builder pure helpers.
 *
 * Why these specific cases (one per "production-bug-shaped" failure
 * the orchestrator was likely to hit silently if not caught here):
 *
 *   1. empty graph              → Run button must refuse early
 *   2. duplicate stage_id       → silent overwrite in pipeline_stages
 *   3. cycle (A→B→A)            → DAG orchestrator deadlock
 *   4. valid topology           → stable depends_on order matches edges
 *   5. template round-trip      → templateToBuilder ⟶ builderToStages preserves shape
 *   6. import / export round-trip → JSON we save is JSON we can re-load
 *   7. stagesToCustomApiPayload → snake_case + max_retries heuristic
 */
import { describe, expect, it } from 'vitest'

import {
  builderToStages,
  checkTopology,
  exportDocAsJson,
  importDocFromJson,
  stagesToCustomApiPayload,
  templateToBuilder,
  type BackendStage,
  type BuilderEdge,
  type BuilderNode,
  type WorkflowDoc,
} from '../workflowBuilder'

function n(id: string, stageId: string, role = 'developer'): BuilderNode {
  return {
    id,
    position: { x: 0, y: 0 },
    data: { stageId, label: stageId, role },
  }
}
function e(source: string, target: string): BuilderEdge {
  return { id: `e_${source}_${target}`, source, target }
}

describe('workflowBuilder', () => {
  // ── 1. empty graph ─────────────────────────────────────────────
  it('rejects an empty graph at conversion time', () => {
    const r = builderToStages([], [])
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.error.code).toBe('empty')
    }
  })

  // ── 2. duplicate stage_id ──────────────────────────────────────
  it('rejects duplicate stage_ids before topology check', () => {
    // Two distinct nodes with the same stage_id — would silently
    // collide in pipeline_stages on the backend.
    const nodes = [
      n('node-a', 'planning'),
      n('node-b', 'planning'),
    ]
    const r = builderToStages(nodes, [])
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.error.code).toBe('duplicate-stage-id')
      expect(r.error.message).toContain('planning')
    }
  })

  // ── 3. cycle detection ─────────────────────────────────────────
  it('detects cycles via Kahn topology', () => {
    // A → B → C → A
    const nodes = [n('a', 'plan'), n('b', 'dev'), n('c', 'qa')]
    const edges = [e('a', 'b'), e('b', 'c'), e('c', 'a')]

    const t = checkTopology(nodes, edges)
    expect(t.ok).toBe(false)
    expect(t.cycleNodes.sort()).toEqual(['dev', 'plan', 'qa'])

    const r = builderToStages(nodes, edges)
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.error.code).toBe('cycle')
    }
  })

  // ── 4. valid graph: depends_on derived from edges ──────────────
  it('derives depends_on from edges in stable order', () => {
    // planning → development; design → development; testing depends on dev.
    const nodes = [
      n('np', 'planning', 'product-manager'),
      n('nd', 'design', 'designer'),
      n('nv', 'development', 'developer'),
      n('nq', 'testing', 'qa-lead'),
    ]
    const edges = [e('np', 'nv'), e('nd', 'nv'), e('nv', 'nq')]
    const r = builderToStages(nodes, edges)
    expect(r.ok).toBe(true)
    if (r.ok) {
      const dev = r.stages.find((s) => s.stageId === 'development')!
      expect(dev.dependsOn.sort()).toEqual(['design', 'planning'])
      const qa = r.stages.find((s) => s.stageId === 'testing')!
      expect(qa.dependsOn).toEqual(['development'])
      const plan = r.stages.find((s) => s.stageId === 'planning')!
      expect(plan.dependsOn).toEqual([])
    }
  })

  // ── 5. template hydration → conversion round-trip ──────────────
  it('preserves topology through templateToBuilder → builderToStages', () => {
    const tpl = {
      stages: [
        { id: 'planning',     label: 'Plan',  role: 'product-manager', dependsOn: [] },
        { id: 'design',       label: 'UI',    role: 'designer',        dependsOn: ['planning'] },
        { id: 'architecture', label: 'Arch',  role: 'architect',       dependsOn: ['planning'] },
        { id: 'development',  label: 'Build', role: 'developer',       dependsOn: ['design', 'architecture'] },
        { id: 'testing',      label: 'Test',  role: 'qa-lead',         dependsOn: ['development'] },
      ],
    }
    const { nodes, edges } = templateToBuilder(tpl)
    expect(nodes).toHaveLength(5)
    // Every depends_on must show up as an edge.
    expect(edges.length).toBe(
      tpl.stages.reduce((acc, s) => acc + s.dependsOn.length, 0),
    )

    const r = builderToStages(nodes, edges)
    expect(r.ok).toBe(true)
    if (r.ok) {
      const byId = new Map(r.stages.map((s) => [s.stageId, s]))
      expect(byId.get('development')!.dependsOn.sort()).toEqual([
        'architecture',
        'design',
      ])
      expect(byId.get('testing')!.dependsOn).toEqual(['development'])
    }
  })

  // ── 6. import/export round-trip ────────────────────────────────
  it('survives a JSON export → import round-trip', () => {
    const doc: WorkflowDoc = {
      version: 1,
      name: 'rt',
      nodes: [n('a', 'plan'), n('b', 'dev')],
      edges: [e('a', 'b')],
      baseTemplate: 'simple',
      updatedAt: 1234567890,
    }
    const json = exportDocAsJson(doc)
    const back = importDocFromJson(json)
    expect(back).not.toBeNull()
    expect(back!.nodes).toHaveLength(2)
    expect(back!.edges[0]).toMatchObject({ source: 'a', target: 'b' })
    expect(back!.baseTemplate).toBe('simple')

    // Garbage in → null out (don't crash the builder on a malformed paste).
    expect(importDocFromJson('{not json')).toBeNull()
    expect(importDocFromJson(JSON.stringify({ version: 99 }))).toBeNull()
  })

  // ── 7. snake_case API payload + max_retries heuristic ──────────
  it('maps BackendStage → snake_case CustomStageApiSpec for the backend', () => {
    const stages: BackendStage[] = [
      {
        stageId: 'planning', label: 'Plan', role: 'product-manager',
        dependsOn: [], rejectAction: 'self-heal', onFailure: 'halt',
      },
      {
        stageId: 'security', label: 'Sec', role: 'security',
        dependsOn: ['planning'], rejectAction: 'manual',
        humanGate: true, qualityGateMin: 0.9, model: 'anthropic/claude-sonnet-4',
        onFailure: 'rollback',
      },
    ]

    const payload = stagesToCustomApiPayload(stages)
    expect(payload[0]).toMatchObject({
      stage_id: 'planning',
      role: 'product-manager',
      depends_on: [],
      max_retries: 1,
      on_failure: 'halt',
      human_gate: false,
    })
    expect(payload[1]).toMatchObject({
      stage_id: 'security',
      depends_on: ['planning'],
      // manual reject means the orchestrator should NOT auto-retry on
      // its own (per the heuristic in stagesToCustomApiPayload).
      max_retries: 0,
      on_failure: 'rollback',
      human_gate: true,
      quality_gate_min: 0.9,
      model_override: 'anthropic/claude-sonnet-4',
    })
  })
})
