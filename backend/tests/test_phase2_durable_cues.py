"""Phase 2 — durable cues: scheduler DB lifecycle + stage input_snapshot."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.database import async_session
from app.models.pipeline import PipelineTask
from app.services.task_scheduler import TaskScheduler, get_scheduler


async def _wait_for_finished_increment(before_finished: int, *, timeout_s: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        st = get_scheduler().status()
        if st["lifetime"]["finished"] > before_finished:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(
        f"scheduler lifetime.finished did not exceed {before_finished} within {timeout_s}s"
    )


@pytest.mark.asyncio
async def test_scheduler_marks_finished_at_after_successful_run(client, auth_headers, monkeypatch):
    async def _noop_smart_pipeline(db_session, task_id, title, description):
        return {"ok": True, "task_id": task_id}

    monkeypatch.setattr(
        "app.services.lead_agent.run_smart_pipeline",
        _noop_smart_pipeline,
    )

    before = get_scheduler().status()["lifetime"]["finished"]

    t = await client.post(
        "/api/pipeline/tasks",
        json={"title": "Phase2 scheduler success", "description": ""},
        headers=auth_headers,
    )
    assert t.status_code == 201
    task_id = t.json()["task"]["id"]

    r = await client.post(
        f"/api/pipeline/tasks/{task_id}/smart-run",
        headers=auth_headers,
    )
    assert r.status_code == 200

    await _wait_for_finished_increment(before)

    tid = uuid.UUID(task_id)
    async with async_session() as s:
        row = (
            await s.execute(select(PipelineTask).where(PipelineTask.id == tid))
        ).scalar_one()

    assert row.scheduler_run_submission_id is None
    assert row.scheduler_run_finished_at is not None
    assert row.scheduler_last_error is None


@pytest.mark.asyncio
async def test_scheduler_records_last_error_on_pipeline_failure(client, auth_headers, monkeypatch):
    async def _boom(_db_session, *_a, **_k):
        raise RuntimeError("phase2_scheduler_test_intentional_failure")

    monkeypatch.setattr(
        "app.services.lead_agent.run_smart_pipeline",
        _boom,
    )

    before_failed = get_scheduler().status()["lifetime"]["failed"]

    t = await client.post(
        "/api/pipeline/tasks",
        json={"title": "Phase2 scheduler fail", "description": ""},
        headers=auth_headers,
    )
    assert t.status_code == 201
    task_id = t.json()["task"]["id"]

    r = await client.post(
        f"/api/pipeline/tasks/{task_id}/smart-run",
        headers=auth_headers,
    )
    assert r.status_code == 200

    deadline = asyncio.get_running_loop().time() + 5.0
    while asyncio.get_running_loop().time() < deadline:
        if get_scheduler().status()["lifetime"]["failed"] > before_failed:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("scheduler did not record failed lifetime increment")

    tid = uuid.UUID(task_id)
    async with async_session() as s:
        row = (
            await s.execute(select(PipelineTask).where(PipelineTask.id == tid))
        ).scalar_one()

    assert row.scheduler_run_submission_id is None
    assert row.scheduler_last_error
    assert "phase2_scheduler_test_intentional_failure" in row.scheduler_last_error


@pytest.mark.asyncio
async def test_advance_sets_input_snapshot_on_next_stage(client, auth_headers):
    t = await client.post(
        "/api/pipeline/tasks",
        json={"title": "Phase2 input snapshot", "description": "handoff test"},
        headers=auth_headers,
    )
    assert t.status_code == 201
    task_id = t.json()["task"]["id"]

    adv = await client.post(
        f"/api/pipeline/tasks/{task_id}/advance",
        json={"output": "## planning done\nmock"},
        headers=auth_headers,
    )
    assert adv.status_code == 200
    task = adv.json()["task"]
    design = next(s for s in task["stages"] if s["stage_id"] == "design")
    assert design.get("status") == "active"
    snap = design.get("input_snapshot")
    assert snap is not None
    assert snap.get("source") == "advance"
    assert snap.get("after_stage_id") == "planning"
    assert "description_preview" in snap


@pytest.mark.asyncio
async def test_orphan_scan_clears_stale_scheduler_marker(db, test_user):
    task = PipelineTask(
        title="Phase2 stale scheduler marker",
        description="simulates a process crash after mark-start",
        org_id=test_user.org_id,
        created_by=str(test_user.id),
        status="active",
        scheduler_run_submission_id="stale-submission",
        scheduler_run_kind="smart-run",
        scheduler_run_started_at=datetime.utcnow(),
    )
    db.add(task)
    await db.commit()
    task_id = task.id

    scheduler = TaskScheduler(max_concurrent=1)
    await scheduler._scan_orphan_tasks()

    async with async_session() as s:
        row = (
            await s.execute(select(PipelineTask).where(PipelineTask.id == task_id))
        ).scalar_one()

    assert row.scheduler_run_submission_id is None
    assert row.scheduler_run_kind is None
    assert row.scheduler_run_finished_at is not None
    assert row.scheduler_last_error
    assert "Scheduler process restarted" in row.scheduler_last_error


@pytest.mark.asyncio
async def test_cancel_scheduler_queue_endpoint(client, auth_headers, monkeypatch):
    captured: list[str] = []

    class _StubScheduler:
        async def cancel_queued_for_task(self, uid: str) -> dict[str, object]:
            captured.append(uid)
            return {"ok": True, "removed": 2, "submissionIds": ["a", "b"], "stillRunning": []}

    stub_sched = _StubScheduler()
    monkeypatch.setattr("app.api.pipeline.get_scheduler", lambda: stub_sched)

    t = await client.post(
        "/api/pipeline/tasks",
        json={"title": "phase2 cancel api", "description": "-"},
        headers=auth_headers,
    )
    assert t.status_code == 201
    task_id = t.json()["task"]["id"]

    r = await client.post(f"/api/pipeline/tasks/{task_id}/cancel-queue", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["removed"] == 2
    assert captured == [task_id]


@pytest.mark.asyncio
async def test_retry_dag_stage_endpoint(client, auth_headers, monkeypatch):
    captured: list[dict[str, object]] = []

    class _StubScheduler:
        async def submit(self, **kwargs: object) -> str:
            captured.append(dict(kwargs))
            return "sub-dag-retry"

    stub_sched = _StubScheduler()
    monkeypatch.setattr("app.api.pipeline.get_scheduler", lambda: stub_sched)

    t = await client.post(
        "/api/pipeline/tasks",
        json={"title": "phase2 retry dag stage", "description": "-"},
        headers=auth_headers,
    )
    assert t.status_code == 201
    task_id = t.json()["task"]["id"]
    first_stage = t.json()["task"]["stages"][0]["stage_id"]

    r = await client.post(
        f"/api/pipeline/tasks/{task_id}/retry-dag-stage/{first_stage}",
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["queued"] is True
    assert body["submissionId"] == "sub-dag-retry"
    assert len(captured) == 1
    assert captured[0]["kind"] == "dag-run"
    params = captured[0]["params"]
    assert isinstance(params, dict)
    assert params.get("resume") is True
    assert params.get("task_id") == task_id
