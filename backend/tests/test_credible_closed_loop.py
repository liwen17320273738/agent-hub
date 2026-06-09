"""Credible closed-loop smoke test.

This is the regression guard for the three deterministic bugs found by running
the *real* authenticated pipeline (login → create task → auto-run) and watching
it silently hang while the dashboard stayed at ``planning/pending`` forever:

  1. ``TraceSpan.set_metadata`` did not exist, yet ``pipeline_engine`` called it
     on every design/architecture stage (latent AttributeError).
  2. A fictitious model id (``google/gemma-4-26b-a4b``) was hard-coded as a
     default, so misconfigured runs hit the provider with an invalid name.
  3. ``force_continue=True`` swallowed hard stage failures AND the whole pipeline
     committed to the DB only once at the very end — so a mid-run hang left
     every stage stuck at ``pending`` and the run masqueraded as a clean success.

These tests run WITHOUT any live LLM / network: ``execute_stage`` is monkeypatched.
Run on every commit:  ``python3 -m pytest tests/test_credible_closed_loop.py -v``
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.context import TraceSpan
from app.models.pipeline import PipelineTask, PipelineStage
from app.services import execute_full_pipeline as efp


# ── Bug 1: TraceSpan.set_metadata must exist and mutate in place ──────────

def test_trace_span_set_metadata_exists_and_stores():
    span = TraceSpan(trace_id="t", span_id="s")
    span.set_metadata("resource_check", {"ok": True})
    assert span.metadata["resource_check"] == {"ok": True}
    # children inherit committed metadata
    child = span.new_child()
    assert child.metadata["resource_check"] == {"ok": True}


# ── Bug 2: no fictitious model id may be a code-level default ──────────────

def test_no_fictitious_model_as_code_default():
    from app.services import planner_worker

    # The bogus local-model fallback must not resurface.
    assert planner_worker._LOCAL_BASE != "google/gemma-4-26b-a4b"
    # resolve_model must always hand back a non-empty model name.
    info = planner_worker.resolve_model(role="product-manager", stage_id="planning")
    assert info.get("model")


# ── Bug 3: force_continue is honest + progress is persisted per-stage ──────

@pytest.mark.asyncio
async def test_force_continue_reports_degraded_and_persists(db, monkeypatch):
    # A task with a single planning stage row (mirrors the e2e_intake template).
    task = PipelineTask(
        title="Closed-loop smoke",
        description="待办看板",
        org_id=None,
        created_by=None,
        current_stage_id="planning",
        status="active",
    )
    db.add(task)
    await db.flush()
    stage = PipelineStage(
        task_id=task.id,
        stage_id="planning",
        label="规划",
        status="pending",
        sort_order=0,
    )
    db.add(stage)
    await db.commit()

    # Make the planning stage hard-fail, hermetically (no LLM / network).
    async def _failing_stage(*args, **kwargs):
        return {"ok": False, "error": "simulated planning failure"}

    monkeypatch.setattr(efp, "execute_stage", _failing_stage)

    async def _noop_workspace(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.services.task_workspace.ensure_task_workspace", _noop_workspace
    )

    result = await efp.execute_full_pipeline(
        db,
        task_id=str(task.id),
        task_title=task.title,
        task_description=task.description,
        stages=["planning"],
        force_continue=True,
    )

    # (a) It does not raise and (b) it honestly reports degradation rather
    # than masquerading as a clean success.
    assert result["degraded"] is True
    assert any(f["stage_id"] == "planning" for f in result["failed_stages"])

    # (c) The failure was committed per-stage — a separate read sees "error",
    # not the stale "pending" the dashboard used to be stuck on.
    fresh = await db.execute(
        select(PipelineStage).where(PipelineStage.task_id == task.id)
    )
    row = fresh.scalars().first()
    assert row.status == "error"

    refreshed_task = await db.get(PipelineTask, task.id)
    assert refreshed_task.scheduler_last_error
    assert "planning" in refreshed_task.scheduler_last_error


# ── §7: a stage executed without a template row must be auto-created ───────

@pytest.mark.asyncio
async def test_missing_stage_row_is_auto_created(db, monkeypatch):
    # Template created only the planning row; auto-run executes design too.
    task = PipelineTask(
        title="Auto-row smoke",
        description="待办看板",
        org_id=None,
        created_by=None,
        current_stage_id="planning",
        status="active",
    )
    db.add(task)
    await db.flush()
    db.add(PipelineStage(
        task_id=task.id, stage_id="planning", label="规划",
        status="pending", sort_order=0,
    ))
    await db.commit()

    async def _failing_stage(*args, **kwargs):
        return {"ok": False, "error": "irrelevant — we only assert row creation"}

    monkeypatch.setattr(efp, "execute_stage", _failing_stage)

    async def _noop_workspace(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.services.task_workspace.ensure_task_workspace", _noop_workspace
    )

    await efp.execute_full_pipeline(
        db,
        task_id=str(task.id),
        task_title=task.title,
        task_description=task.description,
        stages=["planning", "design"],
        force_continue=True,
    )

    rows = (await db.execute(
        select(PipelineStage).where(PipelineStage.task_id == task.id)
    )).scalars().all()
    by_id = {r.stage_id: r for r in rows}
    # The design row never existed in the template — it must now exist so the
    # dashboard can show it (instead of silently swallowing every write).
    assert "design" in by_id
    assert by_id["design"].label  # human-readable, not blank
    # And the per-stage commit landed the error on the newly-created row.
    assert by_id["design"].status == "error"


# ── §7: a hung stage must be aborted by the watchdog, not hang forever ─────

@pytest.mark.asyncio
async def test_stage_watchdog_aborts_hang(db, monkeypatch):
    task = PipelineTask(
        title="Watchdog smoke",
        description="待办看板",
        org_id=None,
        created_by=None,
        current_stage_id="planning",
        status="active",
    )
    db.add(task)
    await db.flush()
    db.add(PipelineStage(
        task_id=task.id, stage_id="planning", label="规划",
        status="pending", sort_order=0,
    ))
    await db.commit()

    import asyncio

    # A stage that would hang forever (the real-world 0% CPU symptom).
    async def _hanging_stage(*args, **kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(efp, "execute_stage", _hanging_stage)

    # Force the watchdog to fire fast without waiting the production floor.
    _real_wait_for = asyncio.wait_for

    async def _fast_wait_for(coro, timeout=None):
        return await _real_wait_for(coro, timeout=0.3)

    monkeypatch.setattr(efp.asyncio, "wait_for", _fast_wait_for)

    async def _noop_workspace(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.services.task_workspace.ensure_task_workspace", _noop_workspace
    )

    result = await efp.execute_full_pipeline(
        db,
        task_id=str(task.id),
        task_title=task.title,
        task_description=task.description,
        stages=["planning"],
        force_continue=True,
    )

    # It returns (does not hang) and reports the timeout honestly.
    assert result["degraded"] is True
    assert any(f["stage_id"] == "planning" for f in result["failed_stages"])

    row = (await db.execute(
        select(PipelineStage).where(PipelineStage.task_id == task.id)
    )).scalars().first()
    assert row.status == "error"


# ── §8.2: DAG path must also auto-create a missing stage row ───────────────

@pytest.mark.asyncio
async def test_dag_persist_state_auto_creates_missing_row(db):
    from app.services import dag_orchestrator as dag

    task = PipelineTask(
        title="DAG auto-row smoke",
        description="待办看板",
        org_id=None,
        created_by=None,
        current_stage_id="planning",
        status="active",
    )
    db.add(task)
    await db.flush()
    db.add(PipelineStage(
        task_id=task.id, stage_id="planning", label="规划",
        status="pending", sort_order=0,
    ))
    await db.commit()

    # A DAG stage with no matching pipeline_stages row — previously this made
    # the stage invisible (the helper silently returned).
    stage = dag.DAGStage("design", "UI/UX 设计", "designer")
    await dag._persist_stage_state(db, str(task.id), stage, db_status="active")

    rows = (await db.execute(
        select(PipelineStage).where(PipelineStage.task_id == task.id)
    )).scalars().all()
    by_id = {r.stage_id: r for r in rows}
    assert "design" in by_id
    assert by_id["design"].status == "active"
    assert by_id["design"].label == "UI/UX 设计"
    assert by_id["design"].owner_role == "designer"
    # Appended after the existing planning row (sort_order 0 → new row 1).
    assert by_id["design"].sort_order == 1
