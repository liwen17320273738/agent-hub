"""Pipeline checkpoint & resume support.

Lets a long-running E2E task be interrupted (timeout, crash, manual stop)
and picked up later without rerunning successful stages.

How it works:
- After every DAG iteration we snapshot stage statuses + outputs into
  a `PipelineArtifact` of type `checkpoint` (one row, overwrite each save).
- On resume, `load_checkpoint()` returns the snapshot; the DAG orchestrator
  marks any DONE stages as skipped-rerun (their output is reused as input).
- Stages in BLOCKED / FAILED / RUNNING are reset to PENDING so they get
  another shot.

The PipelineArtifact table is reused (no new migration); only its
`metadata_extra` JSON column carries the snapshot.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.pipeline import PipelineArtifact

logger = logging.getLogger(__name__)

ARTIFACT_TYPE = "checkpoint"


def _parse_uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)


async def save_checkpoint(
    db: AsyncSession,
    *,
    task_id: str,
    template: str,
    stage_states: List[Dict[str, Any]],
    outputs: Dict[str, str],
    iteration: int,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist (or overwrite) the checkpoint row for `task_id`."""
    try:
        task_uuid = _parse_uuid(task_id)
    except (ValueError, TypeError):
        logger.debug(f"[checkpoint] invalid task_id={task_id!r}, skipping")
        return

    payload: Dict[str, Any] = {
        "template": template,
        "iteration": iteration,
        "saved_at": datetime.utcnow().isoformat(),
        "stage_states": stage_states,
        "outputs": outputs,
    }
    if extra:
        payload["extra"] = extra

    try:
        existing = await db.execute(
            select(PipelineArtifact).where(
                PipelineArtifact.task_id == task_uuid,
                PipelineArtifact.artifact_type == ARTIFACT_TYPE,
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            row = PipelineArtifact(
                task_id=task_uuid,
                artifact_type=ARTIFACT_TYPE,
                name="dag_checkpoint",
                content="",
                stage_id="__checkpoint__",
                metadata_extra=payload,
            )
            db.add(row)
        else:
            row.metadata_extra = payload
        await db.flush()
    except Exception as e:
        logger.warning(f"[checkpoint] save failed for task {task_id}: {e}")


async def load_checkpoint(db: AsyncSession, task_id: str) -> Optional[Dict[str, Any]]:
    try:
        task_uuid = _parse_uuid(task_id)
    except (ValueError, TypeError):
        return None
    try:
        existing = await db.execute(
            select(PipelineArtifact).where(
                PipelineArtifact.task_id == task_uuid,
                PipelineArtifact.artifact_type == ARTIFACT_TYPE,
            )
        )
        row = existing.scalar_one_or_none()
        if row is None or not row.metadata_extra:
            return None
        return dict(row.metadata_extra)
    except Exception as e:
        logger.warning(f"[checkpoint] load failed for task {task_id}: {e}")
        return None


async def clear_checkpoint(db: AsyncSession, task_id: str) -> None:
    try:
        task_uuid = _parse_uuid(task_id)
    except (ValueError, TypeError):
        return
    try:
        existing = await db.execute(
            select(PipelineArtifact).where(
                PipelineArtifact.task_id == task_uuid,
                PipelineArtifact.artifact_type == ARTIFACT_TYPE,
            )
        )
        row = existing.scalar_one_or_none()
        if row is not None:
            await db.delete(row)
            await db.flush()
    except Exception as e:
        logger.debug(f"[checkpoint] clear failed: {e}")
