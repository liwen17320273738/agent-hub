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

from ..config import settings

logger = logging.getLogger(__name__)

# TTLs (configurable via env)
STALE_TASK_AGE_HOURS = int(os.environ.get("TASK_STALE_AGE_HOURS", "72"))
ORPHAN_WORKTREE_AGE_HOURS = int(os.environ.get("ORPHAN_WORKTREE_AGE_HOURS", "48"))


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


async def cleanup_stale_tasks(db: AsyncSession) -> dict:
    """Find and clean up tasks stuck in 'active' state for too long.

    Returns:
        ``{"stale_tasks_found": N, "cleaned": N, "errors": [...]}``
    """
    from ..models.pipeline import PipelineTask

    cutoff = datetime.utcnow() - timedelta(hours=STALE_TASK_AGE_HOURS)
    result = await db.execute(
        select(PipelineTask).where(
            PipelineTask.status == "active",
            PipelineTask.created_at < cutoff,
        )
    )
    stale_tasks = result.scalars().all()

    cleaned = 0
    errors: list[str] = []
    for task in stale_tasks:
        try:
            task.status = "failed"
            task.current_stage_id = None
            await cleanup_cancelled_task(db, str(task.id), kill_subprocesses=True)
            cleaned += 1
        except Exception as e:
            errors.append(f"stale_cleanup_{task.id}: {e}")

    if stale_tasks:
        logger.warning(
            "[lifecycle] Found %d stale tasks (>%dh), cleaned %d",
            len(stale_tasks), STALE_TASK_AGE_HOURS, cleaned,
        )
    await db.commit()

    return {
        "stale_tasks_found": len(stale_tasks),
        "cleaned": cleaned,
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


def schedule_periodic_cleanup(interval_minutes: int = 60) -> Optional[asyncio.Task]:
    """Start a background task that periodically runs cleanup.

    Args:
        interval_minutes: How often to run the cleanup sweep.
    """
    async def _cleanup_loop() -> None:
        while True:
            try:
                await asyncio.sleep(interval_minutes * 60)
                from ..database import async_session
                async with async_session() as db:
                    stale = await cleanup_stale_tasks(db)
                    if stale["stale_tasks_found"] > 0:
                        logger.info("[lifecycle] Periodic cleanup: %s", stale)
                orphan = await cleanup_orphan_worktrees()
                if orphan["orphans_found"] > 0:
                    logger.info("[lifecycle] Orphan cleanup: %s", orphan)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[lifecycle] Periodic cleanup failed: %s", e)

    if not settings.environment or settings.environment == "production":
        return asyncio.create_task(_cleanup_loop())
    return None
