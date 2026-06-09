"""Startup orphan reconciliation — stuck stages and mid-run tasks."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models.pipeline import PipelineStage, PipelineTask
from app.services.orphan_reconciliation import (
    reconcile_interrupted_orphan,
    reconcile_terminal_tasks_with_stuck_stages,
    task_had_mid_run,
)
from app.services.task_scheduler import TaskScheduler


@pytest.mark.asyncio
async def test_orphan_scan_reconciles_mid_run_task_to_paused(db, test_user):
    task = PipelineTask(
        title="mid-run orphan",
        description="",
        org_id=test_user.org_id,
        created_by=str(test_user.id),
        status="active",
        current_stage_id="deployment",
        scheduler_run_submission_id="stale-submission",
        scheduler_run_kind="dag-run",
        scheduler_run_started_at=datetime.utcnow(),
    )
    db.add(task)
    await db.flush()
    db.add(
        PipelineStage(
            task_id=task.id,
            stage_id="deployment",
            label="部署",
            status="active",
            sort_order=6,
            started_at=datetime.utcnow(),
        )
    )
    await db.commit()
    task_id = task.id

    scheduler = TaskScheduler(max_concurrent=1)
    await scheduler._scan_orphan_tasks()

    async with async_session() as s:
        row = (
            await s.execute(
                select(PipelineTask)
                .options(selectinload(PipelineTask.stages))
                .where(PipelineTask.id == task_id)
            )
        ).scalar_one()
        stage = next(st for st in row.stages if st.stage_id == "deployment")

    assert row.status == "paused"
    assert row.scheduler_run_submission_id is None
    assert row.scheduler_last_error
    assert "restarted" in row.scheduler_last_error.lower()
    assert stage.status == "error"
    assert stage.last_error


@pytest.mark.asyncio
async def test_orphan_scan_skips_bare_inbox_task(db, test_user):
    """Fresh active task never queued must survive startup scan."""
    task = PipelineTask(
        title="inbox draft",
        description="waiting for user to click run",
        org_id=test_user.org_id,
        created_by=str(test_user.id),
        status="active",
        current_stage_id="planning",
    )
    db.add(task)
    await db.flush()
    db.add(
        PipelineStage(
            task_id=task.id,
            stage_id="planning",
            label="规划",
            status="pending",
            sort_order=0,
        )
    )
    await db.commit()
    task_id = task.id

    scheduler = TaskScheduler(max_concurrent=1)
    await scheduler._scan_orphan_tasks()

    async with async_session() as s:
        row = (await s.execute(select(PipelineTask).where(PipelineTask.id == task_id))).scalar_one()

    assert row.status == "active"
    assert row.scheduler_last_error is None


@pytest.mark.asyncio
async def test_orphan_scan_fixes_stuck_stage_without_submission_id(db, test_user):
    """deployment 永久 active — stage started but scheduler marker already cleared."""
    task = PipelineTask(
        title="stuck deployment stage",
        description="",
        org_id=test_user.org_id,
        created_by=str(test_user.id),
        status="active",
        current_stage_id="deployment",
        scheduler_run_started_at=datetime.utcnow(),
    )
    db.add(task)
    await db.flush()
    db.add(
        PipelineStage(
            task_id=task.id,
            stage_id="deployment",
            label="部署",
            status="active",
            sort_order=6,
            started_at=datetime.utcnow(),
        )
    )
    await db.commit()
    task_id = task.id

    scheduler = TaskScheduler(max_concurrent=1)
    await scheduler._scan_orphan_tasks()

    async with async_session() as s:
        row = (
            await s.execute(
                select(PipelineTask)
                .options(selectinload(PipelineTask.stages))
                .where(PipelineTask.id == task_id)
            )
        ).scalar_one()
        stage = next(st for st in row.stages if st.stage_id == "deployment")

    assert row.status == "paused"
    assert stage.status == "error"


@pytest.mark.asyncio
async def test_terminal_failed_task_gets_stuck_stage_fixed(db, test_user):
    task = PipelineTask(
        title="failed task stuck stage",
        description="",
        org_id=test_user.org_id,
        created_by=str(test_user.id),
        status="failed",
        current_stage_id="development",
    )
    db.add(task)
    await db.flush()
    db.add(
        PipelineStage(
            task_id=task.id,
            stage_id="development",
            label="开发",
            status="active",
            sort_order=4,
            started_at=datetime.utcnow(),
        )
    )
    await db.commit()

    async with async_session() as s:
        fixed = await reconcile_terminal_tasks_with_stuck_stages(s)
        row = (
            await s.execute(
                select(PipelineTask)
                .options(selectinload(PipelineTask.stages))
                .where(PipelineTask.id == task.id)
            )
        ).scalar_one()
        stage = row.stages[0]

    assert fixed
    assert stage.status == "error"


def test_task_had_mid_run_detects_started_stage_only():
    task = PipelineTask(title="t", description="", status="active")
    stages = [
        PipelineStage(
            task_id=task.id,
            stage_id="deployment",
            label="部署",
            status="active",
            started_at=datetime.utcnow(),
        ),
    ]
    assert task_had_mid_run(task, stages) is True


@pytest.mark.asyncio
async def test_reconcile_interrupted_orphan_noop_for_inbox_row(db, test_user):
    task = PipelineTask(
        title="noop",
        description="",
        org_id=test_user.org_id,
        created_by=str(test_user.id),
        status="active",
    )
    db.add(task)
    await db.commit()

    outcome = await reconcile_interrupted_orphan(db, task, [])
    assert outcome["reconciled"] is False
