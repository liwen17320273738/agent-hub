"""
Manifest sync service — rebuild manifest.json from DB after artifact writes.

The manifest is a cache file in each task's directory. DB is the source of truth
(issuse21 D2). If manifest is missing or stale, the API falls back to DB query.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.task_artifact import TaskArtifact
from ..models.pipeline import PipelineTask
from ..services.task_workspace import get_task_root

logger = logging.getLogger(__name__)


async def rebuild_manifest(task_id: str, db: AsyncSession) -> Dict[str, Any]:
    """Rebuild manifest.json for a task from DB records."""
    task = await db.get(PipelineTask, task_id)
    title = task.title if task else "untitled"

    result = await db.execute(
        select(TaskArtifact)
        .where(TaskArtifact.task_id == task_id)
        .where(TaskArtifact.is_latest.is_(True))
        .order_by(TaskArtifact.artifact_type)
    )
    artifacts = result.scalars().all()

    from .artifact_contract import build_task_contract_report

    contract_report = await build_task_contract_report(db, str(task_id))

    manifest = {
        "task_id": str(task_id),
        "title": title,
        "rebuilt_at": datetime.now(timezone.utc).isoformat(),
        "artifact_count": len(artifacts),
        "artifacts": {},
        "contract": contract_report,
    }

    for art in artifacts:
        manifest["artifacts"][art.artifact_type] = {
            "version": art.version,
            "status": art.status,
            "has_content": bool(art.content),
            "mime_type": art.mime_type,
            "updated_at": art.updated_at.isoformat() if art.updated_at else None,
        }

    task_root = get_task_root(str(task_id), title)
    manifest_path = task_root / "manifest.json"
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("Failed to write manifest for task %s: %s", task_id, e)

    return manifest


async def trigger_manifest_refresh(
    task_id: str,
    db: Optional[AsyncSession] = None,
) -> None:
    """Rebuild manifest cache for a task (best-effort).

    When ``db`` is provided (same request transaction), reuse it so nested
    sessions do not break SQLite / test overrides that share one connection.
    """
    try:
        if db is not None:
            await rebuild_manifest(task_id, db)
            return
        from ..database import async_session
        async with async_session() as session:
            await rebuild_manifest(task_id, session)
    except Exception as e:
        logger.warning("Manifest refresh failed for task %s: %s", task_id, e)
