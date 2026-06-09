"""Startup reconciliation for pipeline tasks orphaned by process reload/crash.

When uvicorn --reload or a worker crash kills in-flight coroutines, DB rows
can remain ``active`` / ``reviewing`` forever with no scheduler backing them.
This module marks those rows honestly so the UI can offer resume instead of
lying "执行中".
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models.pipeline import PipelineStage, PipelineTask

logger = logging.getLogger(__name__)

STUCK_STAGE_STATUSES: Tuple[str, ...] = ("active", "reviewing", "running")

ORPHAN_INTERRUPT_MSG = (
    "Scheduler process restarted while this pipeline was in flight; "
    "marked paused so you can resume from the dashboard."
)

STAGE_INTERRUPT_MSG = (
    "Stage interrupted: scheduler process restarted before this step finished."
)


def task_had_mid_run(
    task: PipelineTask,
    stages: Sequence[PipelineStage],
    *,
    had_scheduler_submission: Optional[bool] = None,
) -> bool:
    """True when the task was executing (not a fresh inbox row waiting for Run)."""
    if had_scheduler_submission is True:
        return True
    if task.scheduler_run_submission_id:
        return True
    if task.scheduler_run_started_at is not None:
        return True
    if (task.scheduler_last_error or "").strip():
        return True
    return any(
        s.status in STUCK_STAGE_STATUSES and s.started_at is not None
        for s in stages
    )


def reconcile_stuck_stages(
    stages: Iterable[PipelineStage],
    *,
    reason: str = STAGE_INTERRUPT_MSG,
    now: Optional[datetime] = None,
) -> int:
    """Mark in-flight stages as ``error`` and stamp ``last_error``."""
    ts = now or datetime.utcnow()
    fixed = 0
    for stage in stages:
        if stage.status not in STUCK_STAGE_STATUSES:
            continue
        stage.status = "error"
        stage.last_error = (reason or STAGE_INTERRUPT_MSG)[:8000]
        if stage.completed_at is None:
            stage.completed_at = ts
        fixed += 1
    return fixed


async def reconcile_interrupted_orphan(
    db: AsyncSession,
    task: PipelineTask,
    stages: Sequence[PipelineStage],
    *,
    task_reason: str = ORPHAN_INTERRUPT_MSG,
    stage_reason: str = STAGE_INTERRUPT_MSG,
    had_scheduler_submission: Optional[bool] = None,
) -> Dict[str, Any]:
    """Pause an orphaned mid-run task and fix stuck stage rows."""
    if not task_had_mid_run(
        task, stages, had_scheduler_submission=had_scheduler_submission,
    ):
        return {"taskId": str(task.id), "reconciled": False, "stagesFixed": 0}

    stages_fixed = reconcile_stuck_stages(stages, reason=stage_reason)
    if task.status == "active":
        task.status = "paused"
    task.scheduler_last_error = (task_reason or ORPHAN_INTERRUPT_MSG)[:8000]

    return {
        "taskId": str(task.id),
        "reconciled": True,
        "stagesFixed": stages_fixed,
        "taskStatus": task.status,
    }


async def reconcile_terminal_tasks_with_stuck_stages(
    db: AsyncSession,
    *,
    stage_reason: str = STAGE_INTERRUPT_MSG,
) -> List[Dict[str, Any]]:
    """Fix stages still ``active`` when parent task already reached a terminal state."""
    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages))
        .where(PipelineTask.status.in_(("failed", "done", "cancelled")))
    )
    tasks = result.scalars().all()
    outcomes: List[Dict[str, Any]] = []
    now = datetime.utcnow()

    for task in tasks:
        fixed = reconcile_stuck_stages(task.stages, reason=stage_reason, now=now)
        if fixed:
            outcomes.append({
                "taskId": str(task.id),
                "taskStatus": task.status,
                "stagesFixed": fixed,
            })

    if outcomes:
        await db.commit()
        logger.info(
            "[orphan-reconcile] fixed stuck stages on %d terminal tasks",
            len(outcomes),
        )
    return outcomes


async def emit_reconciliation_events(
    outcomes: Sequence[Dict[str, Any]],
    *,
    reason: str = ORPHAN_INTERRUPT_MSG,
) -> None:
    from .sse import emit_event

    for row in outcomes:
        if not row.get("reconciled"):
            continue
        tid = row["taskId"]
        await emit_event("pipeline:auto-paused", {
            "taskId": tid,
            "stoppedAt": "orphan-reconcile",
            "reason": reason,
            "stagesFixed": row.get("stagesFixed", 0),
        })
        if row.get("stagesFixed"):
            await emit_event("stage:error", {
                "taskId": tid,
                "stageId": "orphan-reconcile",
                "error": reason,
            })
