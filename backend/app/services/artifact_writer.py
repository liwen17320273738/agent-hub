"""
Artifact writer — bridge between pipeline engine stage output and v2 TaskArtifact DB.

Maps stage_id to artifact_type, creates/versions the TaskArtifact row,
and triggers manifest refresh. Controlled by config.artifact_store_v2 flag.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.task_artifact import TaskArtifact

logger = logging.getLogger(__name__)

STAGE_TO_ARTIFACT: dict[str, str] = {
    "planning":     "brief",
    "design":       "ui_spec",
    "architecture": "architecture",
    "development":  "code_link",
    "testing":      "test_report",
    "reviewing":    "acceptance",
    "deployment":   "ops_runbook",
}


async def write_artifact_v2(
    db: AsyncSession,
    task_id: str,
    stage_id: str,
    content: str,
    agent_name: Optional[str] = None,
) -> Optional[TaskArtifact]:
    if not settings.artifact_store_v2:
        return None

    artifact_type = STAGE_TO_ARTIFACT.get(stage_id)
    if not artifact_type:
        return None

    tid = uuid.UUID(task_id) if isinstance(task_id, str) else task_id

    existing = await db.execute(
        select(TaskArtifact).where(
            and_(
                TaskArtifact.task_id == tid,
                TaskArtifact.artifact_type == artifact_type,
                TaskArtifact.is_latest == True,
            )
        )
    )
    current = existing.scalar_one_or_none()
    new_version = (current.version + 1) if current else 1

    if current:
        current.is_latest = False
        await db.flush()

    art = TaskArtifact(
        task_id=tid,
        stage_id=stage_id,
        artifact_type=artifact_type,
        title=artifact_type,
        content=content,
        version=new_version,
        is_latest=True,
        status="active",
        created_by_agent=agent_name,
    )
    db.add(art)
    await db.flush()

    try:
        from .manifest_sync import trigger_manifest_refresh
        await trigger_manifest_refresh(str(task_id))
    except Exception:
        pass

    logger.info(
        "[artifact_writer] Wrote %s v%d for task %s",
        artifact_type, new_version, task_id,
    )
    return art
