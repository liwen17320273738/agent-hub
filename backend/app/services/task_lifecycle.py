"""
Task Lifecycle Cleanup — prevents zombie processes and leaked worktrees.

Handles cleanup when a pipeline task is cancelled, deleted, or fails
unexpectedly. Ensures:
    - Subprocesses (Claude CLI, Playwright) are terminated
    - Temporary worktrees are removed
    - Stale tasks are detected and cleaned up periodically
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# TTLs (configurable via env).
#
# `TASK_STALE_IDLE_MINUTES` is the watchdog threshold: if a task is in an
# in-flight state (running / active / plan_pending / awaiting_evidence) and
# its `updated_at` hasn't moved for this many minutes, we treat it as
# abandoned and mark it cancelled. Defaults to 60 min.
#
# Whenever a stage transitions or the scheduler touches a task, its
# `updated_at` is bumped, so a healthy long pipeline never trips this.
# A task created and then orphaned (seed scripts, crashed Playwright tests,
# killed workers) trips it within the window.
STALE_TASK_IDLE_MINUTES = int(os.environ.get("TASK_STALE_IDLE_MINUTES", "60"))

# Statuses considered "in-flight" by the watchdog. Pulled here so callers and
# tests share one source of truth.
INFLIGHT_TASK_STATUSES: tuple[str, ...] = (
    "running",
    "active",
    "plan_pending",
    "awaiting_evidence",
)

ORPHAN_WORKTREE_AGE_HOURS = int(os.environ.get("ORPHAN_WORKTREE_AGE_HOURS", "48"))

# How often the periodic cleanup loop runs (minutes). Independent from the
# staleness threshold above. Default 15 min so a zombie shows up in the Inbox
# for at most one window.
LIFECYCLE_SWEEP_MINUTES = int(os.environ.get("TASK_LIFECYCLE_SWEEP_MINUTES", "15"))

# Set to "1" to skip the lifecycle loop entirely (tests, CI smoke).
LIFECYCLE_DISABLE = os.environ.get("TASK_LIFECYCLE_DISABLE", "") == "1"


async def cleanup_cancelled_task(
    db: AsyncSession,
    task_id: str,
    *,
    kill_subprocesses: bool = True,
    remove_worktree: bool = False,  # default False — keep worktrees for audit
) -> dict:
    """Clean up resources associated with a cancelled/deleted task.

    Returns:
        ``{"subprocesses_cleaned": N, "worktree_removed": bool, "errors": [...]}``
    """
    errors: list[str] = []

    # 1. Terminate associated subprocesses
    subprocesses_cleaned = 0
    if kill_subprocesses:
        try:
            from .executor_bridge import kill_job_by_task_id
            subprocesses_cleaned = await kill_job_by_task_id(task_id)
        except Exception as e:
            errors.append(f"subprocess_cleanup: {e}")

    # 2. Remove orphan worktree (if requested)
    worktree_removed = False
    if remove_worktree:
        try:
            from .task_workspace import get_task_worktree
            wt = get_task_worktree(task_id)
            if wt and os.path.exists(str(wt)):
                shutil.rmtree(str(wt), ignore_errors=True)
                worktree_removed = True
                logger.info("[lifecycle] Removed worktree for task %s", task_id[:12])
        except Exception as e:
            errors.append(f"worktree_cleanup: {e}")

    return {
        "subprocesses_cleaned": subprocesses_cleaned,
        "worktree_removed": worktree_removed,
        "errors": errors,
    }


async def cleanup_stale_tasks(
    db: AsyncSession,
    *,
    idle_minutes: Optional[int] = None,
    dry_run: bool = False,
) -> dict:
    """Mark abandoned in-flight tasks as cancelled.

    A task is "abandoned" when it has been in any of
    :data:`INFLIGHT_TASK_STATUSES` (running / active / plan_pending /
    awaiting_evidence) and its ``updated_at`` hasn't advanced for
    ``idle_minutes`` (default :data:`STALE_TASK_IDLE_MINUTES`).

    Cancellation, not failure: an abandoned task has no diagnosed root
    cause — it simply has no one driving it. ``failed`` is reserved for
    pipelines that hit an explicit error and produced an RCA.

    Each cancellation also stamps ``last_error`` on the task's currently
    active stage (if any) so the audit trail captures *why* it was
    cancelled instead of silently flipping status.

    Returns:
        ``{"stale_tasks_found": N, "cancelled": N, "ids": [...],
           "dry_run": bool, "errors": [...]}``
    """
    from ..models.pipeline import PipelineStage, PipelineTask

    minutes = idle_minutes if idle_minutes is not None else STALE_TASK_IDLE_MINUTES
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)

    result = await db.execute(
        select(PipelineTask).where(
            PipelineTask.status.in_(INFLIGHT_TASK_STATUSES),
            PipelineTask.updated_at < cutoff,
        )
    )
    stale_tasks = result.scalars().all()

    cancelled = 0
    cancelled_ids: list[str] = []
    errors: list[str] = []
    audit_msg = (
        f"abandoned_no_progress: in-flight task idle > {minutes}m "
        "(no stage advancement, no scheduler heartbeat)"
    )

    for task in stale_tasks:
        try:
            if dry_run:
                cancelled_ids.append(str(task.id))
                continue

            task.status = "cancelled"
            task.current_stage_id = task.current_stage_id or "cancelled"

            # Stamp last_error on the active stage so operators can see why
            # the task was cancelled when they open the detail page.
            stage_rows = await db.execute(
                select(PipelineStage).where(
                    PipelineStage.task_id == task.id,
                    PipelineStage.status.in_(("active", "running")),
                )
            )
            for stage in stage_rows.scalars():
                stage.status = "cancelled"
                stage.last_error = audit_msg
                if stage.completed_at is None:
                    stage.completed_at = datetime.utcnow()

            await cleanup_cancelled_task(
                db, str(task.id), kill_subprocesses=True,
            )
            cancelled += 1
            cancelled_ids.append(str(task.id))
        except Exception as e:
            errors.append(f"stale_cleanup_{task.id}: {e}")

    if stale_tasks:
        logger.warning(
            "[lifecycle] watchdog found %d stale tasks (idle > %dm), "
            "cancelled %d%s",
            len(stale_tasks), minutes, cancelled,
            " (dry_run)" if dry_run else "",
        )
    if not dry_run and cancelled:
        await db.commit()

    return {
        "stale_tasks_found": len(stale_tasks),
        "cancelled": cancelled,
        "ids": cancelled_ids,
        "dry_run": dry_run,
        "errors": errors,
    }


async def cleanup_orphan_worktrees(workspace_root: Optional[Path] = None) -> dict:
    """Remove orphan worktree directories whose tasks no longer exist in DB.

    A worktree is considered orphaned if:
        - Its directory exists under the workspace root
        - Its corresponding task_id is not found in the pipeline_tasks table
        - The directory is older than ORPHAN_WORKTREE_AGE_HOURS
    """
    from ..database import async_session

    if workspace_root is None:
        from .task_workspace import ensure_global_workspace_dirs
        workspace_root = Path(ensure_global_workspace_dirs())

    if not workspace_root.exists():
        return {"orphans_found": 0, "removed": 0}

    # Get all valid task IDs from DB
    async with async_session() as db:
        from ..models.pipeline import PipelineTask
        result = await db.execute(select(PipelineTask.id))
        valid_ids = {str(r[0]) for r in result.all()}

    removed = 0
    errors: list[str] = []
    cutoff = time.time() - (ORPHAN_WORKTREE_AGE_HOURS * 3600)

    for child in workspace_root.iterdir():
        if not child.is_dir():
            continue
        if child.name in valid_ids:
            continue

        try:
            stat = child.stat()
            if stat.st_mtime < cutoff:
                shutil.rmtree(str(child), ignore_errors=True)
                removed += 1
                logger.info("[lifecycle] Removed orphan worktree: %s", child.name)
        except Exception as e:
            errors.append(f"orphan_{child.name}: {e}")

    if removed:
        logger.warning("[lifecycle] Removed %d orphan worktrees", removed)

    return {
        "orphans_found": removed,
        "removed": removed,
        "errors": errors,
    }


def schedule_periodic_cleanup(
    interval_minutes: Optional[int] = None,
) -> Optional[asyncio.Task]:
    """Start a background task that periodically runs the watchdog sweep.

    Runs in every environment (dev / staging / prod). Disable per-process
    via ``TASK_LIFECYCLE_DISABLE=1`` — useful for tests and CI smoke runs.

    Args:
        interval_minutes: Override the sweep interval. Defaults to
            :data:`LIFECYCLE_SWEEP_MINUTES` (env
            ``TASK_LIFECYCLE_SWEEP_MINUTES``, default 15).
    """
    if LIFECYCLE_DISABLE:
        logger.info("[lifecycle] watchdog disabled (TASK_LIFECYCLE_DISABLE=1)")
        return None

    interval = interval_minutes if interval_minutes is not None else LIFECYCLE_SWEEP_MINUTES

    async def _cleanup_loop() -> None:
        while True:
            try:
                await asyncio.sleep(interval * 60)
                from ..database import async_session
                async with async_session() as db:
                    stale = await cleanup_stale_tasks(db)
                    if stale["stale_tasks_found"] > 0:
                        logger.info("[lifecycle] watchdog sweep: %s", stale)
                orphan = await cleanup_orphan_worktrees()
                if orphan["orphans_found"] > 0:
                    logger.info("[lifecycle] orphan worktree sweep: %s", orphan)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[lifecycle] watchdog sweep failed: %s", e)

    return asyncio.create_task(_cleanup_loop())
