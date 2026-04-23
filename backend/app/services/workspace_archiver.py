"""
Workspace archiver — compress old task worktrees to save disk (issuse21 Phase 4).

Rules:
  - Accepted tasks older than 30 days: worktree → tar.gz → _archive/
  - Cancelled tasks older than 7 days: same
  - docs/ directory is NEVER archived (always accessible)
  - Archive before confirming worktree pushed to git remote
"""
from __future__ import annotations

import logging
import shutil
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.pipeline import PipelineTask
from ..services.task_workspace import get_task_root, _workspace_root

logger = logging.getLogger(__name__)

ACCEPTED_AGE_DAYS = 30
CANCELLED_AGE_DAYS = 7


async def archive_stale_tasks(db: AsyncSession) -> List[str]:
    """Find and archive eligible task worktrees. Returns list of archived task IDs."""
    now = datetime.now(timezone.utc)
    cutoff_accepted = now - timedelta(days=ACCEPTED_AGE_DAYS)
    cutoff_cancelled = now - timedelta(days=CANCELLED_AGE_DAYS)

    result = await db.execute(
        select(PipelineTask).where(
            or_(
                and_(
                    PipelineTask.status == "done",
                    PipelineTask.final_acceptance_status == "accepted",
                    PipelineTask.updated_at < cutoff_accepted,
                ),
                and_(
                    PipelineTask.status == "cancelled",
                    PipelineTask.updated_at < cutoff_cancelled,
                ),
            )
        )
    )
    tasks = result.scalars().all()
    archived: List[str] = []

    archive_root = _workspace_root() / "_archive"
    archive_root.mkdir(parents=True, exist_ok=True)

    for task in tasks:
        task_id = str(task.id)
        task_root = get_task_root(task_id, task.title or "untitled")
        worktree = task_root

        if not worktree.exists():
            continue

        month_dir = archive_root / now.strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)
        archive_path = month_dir / f"{task_id}.tar.gz"

        if archive_path.exists():
            continue

        try:
            docs_dir = worktree / "docs"
            dirs_to_archive = [
                d for d in worktree.iterdir()
                if d.is_dir() and d.name not in ("docs",)
            ]

            if not dirs_to_archive:
                continue

            with tarfile.open(str(archive_path), "w:gz") as tar:
                for d in dirs_to_archive:
                    tar.add(str(d), arcname=d.name)

            for d in dirs_to_archive:
                shutil.rmtree(str(d), ignore_errors=True)

            archived.append(task_id)
            logger.info("Archived task %s → %s", task_id, archive_path)

        except Exception as e:
            logger.error("Failed to archive task %s: %s", task_id, e)
            if archive_path.exists():
                archive_path.unlink(missing_ok=True)

    return archived
