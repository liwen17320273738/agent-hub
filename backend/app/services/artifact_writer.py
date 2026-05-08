"""
Artifact writer — bridge between pipeline engine stage output and v2 TaskArtifact DB.

Maps stage_id to artifact_type, creates/versions the TaskArtifact row,
and triggers manifest refresh. Controlled by config.artifact_store_v2 flag.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.task_artifact import TaskArtifact

logger = logging.getLogger(__name__)

STAGE_TO_ARTIFACT: dict[str, str] = {
    "planning":     "prd",
    "design":       "ui_spec",
    "architecture": "architecture",
    "development":  "code_link",
    "testing":      "test_report",
    "reviewing":    "acceptance",
    "deployment":   "ops_runbook",
}

AUX_STAGE_LABELS: dict[str, str] = {
    "security-review": "安全审查",
    "data-modeling": "数据建模",
    "marketing-launch": "上线运营",
    "finance-review": "财务评估",
    "legal-review": "法务审查",
}

STAGE_TO_DOC_FILE: dict[str, str] = {
    "planning":     "docs/01-prd.md",
    "design":       "docs/02-ui-spec.md",
    "architecture": "docs/03-architecture.md",
    "development":  "docs/04-implementation-notes.md",
    "testing":      "docs/05-test-report.md",
    "reviewing":    "docs/06-acceptance.md",
    "deployment":   "docs/07-ops-runbook.md",
}


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _brief_from_planning(title: str, content: str) -> str:
    """Short brief for requirements tab; PRD row holds full planning output."""
    head = (content or "").strip()
    cap = 4500
    if len(head) > cap:
        head = head[:cap] + "\n\n…(完整 PRD 见「PRD」工件与 docs/01-prd.md)"
    return f"# 需求简报 — {title}\n\n{head}\n"


async def _append_auxiliary_attachment(
    db: AsyncSession,
    task_id: str,
    stage_id: str,
    section_title: str,
    content: str,
    agent_name: Optional[str] = None,
) -> TaskArtifact:
    tid = uuid.UUID(task_id) if isinstance(task_id, str) else task_id
    existing = await db.execute(
        select(TaskArtifact).where(
            and_(
                TaskArtifact.task_id == tid,
                TaskArtifact.artifact_type == "attachment",
                TaskArtifact.is_latest.is_(True),
            )
        )
    )
    prev = existing.scalar_one_or_none()
    base = (prev.content if prev else "# 附属交付物（安全 / 数据 / 运营 / 财务 / 法务）\n")
    section = f"\n\n## {section_title} (`{stage_id}`)\n\n{(content or '').strip()}\n"
    return await _write_one_artifact(
        db, task_id, stage_id, "attachment", base + section,
        "docs/auxiliary-stages.md", agent_name,
    )


async def _write_one_artifact(
    db: AsyncSession,
    task_id: str,
    stage_id: str,
    artifact_type: str,
    content: str,
    storage_path: str,
    agent_name: Optional[str] = None,
    metadata_json: Optional[dict] = None,
) -> TaskArtifact:
    tid = uuid.UUID(task_id) if isinstance(task_id, str) else task_id

    existing = await db.execute(
        select(TaskArtifact).where(
            and_(
                TaskArtifact.task_id == tid,
                TaskArtifact.artifact_type == artifact_type,
                TaskArtifact.is_latest.is_(True),
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
        content_hash=_content_hash(content),
        storage_path=storage_path,
        metadata_json=metadata_json or {},
        version=new_version,
        is_latest=True,
        status="active",
        created_by_agent=agent_name,
    )
    db.add(art)
    await db.flush()
    logger.info(
        "[artifact_writer] Wrote %s v%d for task %s",
        artifact_type, new_version, task_id,
    )
    return art


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

    art = await _write_one_artifact(
        db, task_id, stage_id, artifact_type, content,
        STAGE_TO_DOC_FILE.get(stage_id, ""), agent_name,
    )
    try:
        from .manifest_sync import trigger_manifest_refresh
        await trigger_manifest_refresh(str(task_id))
    except Exception:
        pass
    return art


async def write_stage_artifacts_v2(
    db: AsyncSession,
    task_id: str,
    task_title: str,
    stage_id: str,
    content: str,
    agent_name: Optional[str] = None,
) -> list[TaskArtifact]:
    """Persist all v2 artifacts for a stage (planning→brief+prd, dev→implementation+code_link)."""
    if not settings.artifact_store_v2:
        return []

    written: list[TaskArtifact] = []

    if stage_id in AUX_STAGE_LABELS and (content or "").strip():
        written.append(await _append_auxiliary_attachment(
            db, task_id, stage_id, AUX_STAGE_LABELS[stage_id], content, agent_name,
        ))
        try:
            from .manifest_sync import trigger_manifest_refresh
            await trigger_manifest_refresh(str(task_id))
        except Exception:
            pass
        return written

    if not (content or "").strip():
        return []
    if stage_id == "planning":
        brief = _brief_from_planning(task_title or "任务", content)
        written.append(await _write_one_artifact(
            db, task_id, stage_id, "brief", brief, "docs/00-brief.md", agent_name,
        ))
        written.append(await _write_one_artifact(
            db, task_id, stage_id, "prd", content, STAGE_TO_DOC_FILE["planning"], agent_name,
        ))
    elif stage_id == "development":
        written.append(await _write_one_artifact(
            db, task_id, stage_id, "implementation", content,
            STAGE_TO_DOC_FILE["development"], agent_name,
        ))
        written.append(await _write_one_artifact(
            db, task_id, stage_id, "code_link", content,
            "docs/code-snapshot.md", agent_name,
        ))
    else:
        at = STAGE_TO_ARTIFACT.get(stage_id)
        if at:
            written.append(await _write_one_artifact(
                db, task_id, stage_id, at, content,
                STAGE_TO_DOC_FILE.get(stage_id, ""), agent_name,
            ))

    try:
        from .manifest_sync import trigger_manifest_refresh
        await trigger_manifest_refresh(str(task_id))
    except Exception:
        pass
    return written
