"""Unit tests for the task lifecycle watchdog.

Covers ``cleanup_stale_tasks`` — the periodic sweep that cancels in-flight
pipeline tasks whose ``updated_at`` hasn't moved for too long.

Why this exists: the Inbox previously accumulated "执行中" zombies whenever a
worker crashed, an E2E test exited early, or a seed script forgot to set
``task.status='done'``. The watchdog catches all three in one pass.

Tests are deterministic — no sleeps, no real schedulers. We backdate
``updated_at`` via raw UPDATE because the ORM ``onupdate=datetime.utcnow``
would clobber any value we set through the model.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline import PipelineStage, PipelineTask
from app.models.user import User
from app.services.task_lifecycle import (
    INFLIGHT_TASK_STATUSES,
    cleanup_stale_tasks,
)


async def _make_task(
    db: AsyncSession,
    user: User,
    *,
    status: str,
    age_minutes: int,
    stage_id: str = "planning",
    stage_status: str = "active",
) -> str:
    """Insert a task + one stage, then backdate updated_at via raw SQL."""
    task = PipelineTask(
        id=uuid.uuid4(),
        title=f"watchdog-fixture-{status}-{age_minutes}m",
        description="x",
        status=status,
        current_stage_id=stage_id,
        org_id=user.org_id,
        created_by=str(user.id),
    )
    db.add(task)
    await db.flush()

    db.add(
        PipelineStage(
            task_id=task.id,
            stage_id=stage_id,
            label=stage_id,
            status=stage_status,
            sort_order=0,
            started_at=datetime.utcnow() - timedelta(minutes=age_minutes),
        )
    )
    await db.commit()

    # The ORM onupdate would override any value we set on the mapped object,
    # so we backdate via raw SQL instead. SQLite + Postgres both accept this.
    backdated = datetime.utcnow() - timedelta(minutes=age_minutes)
    await db.execute(
        text("UPDATE pipeline_tasks SET updated_at = :ts WHERE id = :id"),
        {"ts": backdated, "id": str(task.id)},
    )
    await db.commit()
    return str(task.id)


@pytest.mark.asyncio
async def test_watchdog_cancels_idle_running_task(db: AsyncSession, test_user: User):
    """A task in `running` idle longer than threshold is cancelled."""
    tid = await _make_task(db, test_user, status="running", age_minutes=90)

    result = await cleanup_stale_tasks(db, idle_minutes=60)

    assert result["stale_tasks_found"] == 1
    assert result["cancelled"] == 1
    assert tid in result["ids"]
    assert result["dry_run"] is False
    assert result["errors"] == []

    refreshed = await db.get(PipelineTask, uuid.UUID(tid))
    assert refreshed is not None
    assert refreshed.status == "cancelled"
    # current_stage_id is preserved so operators can see WHERE it died.
    assert refreshed.current_stage_id == "planning"

    stage_rows = await db.execute(
        text(
            "SELECT status, last_error FROM pipeline_stages "
            "WHERE task_id = :id"
        ),
        {"id": tid},
    )
    rows = stage_rows.all()
    assert len(rows) == 1
    assert rows[0][0] == "cancelled"
    assert "abandoned_no_progress" in (rows[0][1] or "")


@pytest.mark.asyncio
async def test_watchdog_leaves_fresh_task_alone(db: AsyncSession, test_user: User):
    """A task that updated recently must not be touched."""
    tid = await _make_task(db, test_user, status="running", age_minutes=2)

    result = await cleanup_stale_tasks(db, idle_minutes=60)

    assert result["stale_tasks_found"] == 0
    assert result["cancelled"] == 0
    assert tid not in result["ids"]

    refreshed = await db.get(PipelineTask, uuid.UUID(tid))
    assert refreshed is not None
    assert refreshed.status == "running"


@pytest.mark.asyncio
async def test_watchdog_leaves_terminal_task_alone(db: AsyncSession, test_user: User):
    """Tasks already in `done`/`cancelled`/`failed` are out of scope."""
    tid = await _make_task(db, test_user, status="done", age_minutes=999)

    result = await cleanup_stale_tasks(db, idle_minutes=1)

    assert result["stale_tasks_found"] == 0
    refreshed = await db.get(PipelineTask, uuid.UUID(tid))
    assert refreshed is not None
    assert refreshed.status == "done"


@pytest.mark.asyncio
async def test_watchdog_covers_all_inflight_statuses(
    db: AsyncSession, test_user: User
):
    """Every status listed in INFLIGHT_TASK_STATUSES is collected by one sweep."""
    ids: dict[str, str] = {}
    for status in INFLIGHT_TASK_STATUSES:
        ids[status] = await _make_task(
            db, test_user, status=status, age_minutes=120,
        )

    result = await cleanup_stale_tasks(db, idle_minutes=60)

    assert result["stale_tasks_found"] == len(INFLIGHT_TASK_STATUSES)
    assert result["cancelled"] == len(INFLIGHT_TASK_STATUSES)
    assert set(result["ids"]) == set(ids.values())

    for status, tid in ids.items():
        refreshed = await db.get(PipelineTask, uuid.UUID(tid))
        assert refreshed is not None, status
        assert refreshed.status == "cancelled", status


@pytest.mark.asyncio
async def test_watchdog_dry_run_reports_without_writing(
    db: AsyncSession, test_user: User
):
    """dry_run lets ops preview the blast radius before flipping switches."""
    tid = await _make_task(db, test_user, status="active", age_minutes=180)

    result = await cleanup_stale_tasks(db, idle_minutes=30, dry_run=True)

    assert result["stale_tasks_found"] == 1
    assert result["cancelled"] == 0
    assert result["dry_run"] is True
    assert tid in result["ids"]

    # Task must be untouched.
    refreshed = await db.get(PipelineTask, uuid.UUID(tid))
    assert refreshed is not None
    assert refreshed.status == "active"
