"""Persist TaskScheduler lifecycle on PipelineTask rows (Phase 2 durable cues).

Lets the UI / operators see ``running`` vs ``idle`` scheduler work and recover
crash signals via ``scheduler_last_error``, without resurrecting orphaned
coroutines (still unsafe → see task_scheduler docs).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional, Sequence
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.pipeline import PipelineTask

logger = logging.getLogger(__name__)


def _parse_tid(task_id: str) -> Optional[UUID]:
    if not task_id or not isinstance(task_id, str):
        return None
    try:
        return UUID(task_id.strip())
    except ValueError:
        logger.warning("[scheduler-state] invalid task_id %r", task_id)
        return None


async def mark_scheduler_started(
    db: AsyncSession, task_id: str, *, meta: Dict[str, Any]
) -> None:
    tid = _parse_tid(task_id)
    if not tid:
        return
    row = await db.get(PipelineTask, tid)
    if not row:
        return
    row.scheduler_run_submission_id = meta.get("submission_id")
    row.scheduler_run_kind = meta.get("kind") or None
    row.scheduler_run_started_at = datetime.utcnow()
    row.scheduler_run_finished_at = None
    row.scheduler_last_error = None


async def mark_scheduler_finished_success(
    db: AsyncSession, task_id: str, *, submission_id: str
) -> None:
    tid = _parse_tid(task_id)
    if not tid:
        return
    row = await db.get(PipelineTask, tid)
    if not row:
        return
    # Only clear if this finish matches the tracked run (no stale overwrite).
    if row.scheduler_run_submission_id != submission_id:
        return
    row.scheduler_run_submission_id = None
    row.scheduler_run_kind = None
    row.scheduler_run_finished_at = datetime.utcnow()
    row.scheduler_last_error = None


async def mark_scheduler_finished_failure(
    db: AsyncSession, task_id: str, *, submission_id: str, error: str
) -> None:
    tid = _parse_tid(task_id)
    if not tid:
        return
    row = await db.get(PipelineTask, tid)
    if not row:
        return
    if row.scheduler_run_submission_id != submission_id:
        return
    row.scheduler_run_submission_id = None
    row.scheduler_run_kind = None
    row.scheduler_run_finished_at = datetime.utcnow()
    row.scheduler_last_error = (error or "")[:8000]
    # 调度器崩溃意味着流水线未正常完成，将任务标记为 failed
    if row.status not in ("done", "cancelled", "failed"):
        row.status = "failed"


async def mark_scheduler_orphaned(
    db: AsyncSession, task_ids: Sequence[str], *, error: str
) -> int:
    """Clear stale scheduler markers left by a previous crashed process."""
    tids = [tid for raw in task_ids if (tid := _parse_tid(raw))]
    if not tids:
        return 0

    result = await db.execute(
        update(PipelineTask)
        .where(PipelineTask.id.in_(tids))
        .where(PipelineTask.scheduler_run_submission_id.is_not(None))
        .values(
            scheduler_run_submission_id=None,
            scheduler_run_kind=None,
            scheduler_run_finished_at=datetime.utcnow(),
            scheduler_last_error=(error or "")[:8000],
        )
    )
    return int(result.rowcount or 0)

