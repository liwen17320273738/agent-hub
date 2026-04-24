"""
Task Artifacts API — versioned artifact CRUD (issuse21 Phase 2).
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.task_artifact import TaskArtifact, ArtifactTypeRegistry, BUILTIN_ARTIFACT_TYPES
from ..models.pipeline import PipelineTask
from ..security import get_pipeline_auth, get_pipeline_auth_optional
from ..models.user import User

router = APIRouter(prefix="/tasks", tags=["task-artifacts"])


class CreateArtifactRequest(BaseModel):
    title: Optional[str] = ""
    content: str = ""
    stage_id: Optional[str] = None
    mime_type: str = "text/markdown"
    storage_path: str = ""
    created_by_agent: Optional[str] = None


@router.get("/artifact-types")
async def list_artifact_types(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ArtifactTypeRegistry).order_by(ArtifactTypeRegistry.sort_order)
    )
    rows = result.scalars().all()
    return [
        {
            "type_key": r.type_key,
            "category": r.category,
            "display_name": r.display_name,
            "icon": r.icon,
            "tab_group": r.tab_group,
            "sort_order": r.sort_order,
        }
        for r in rows
    ]


@router.get("/{task_id}/artifacts")
async def list_task_artifacts(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_pipeline_auth_optional),
):
    result = await db.execute(
        select(TaskArtifact)
        .where(TaskArtifact.task_id == uuid.UUID(task_id))
        .where(TaskArtifact.is_latest == True)
        .order_by(TaskArtifact.artifact_type)
    )
    artifacts = result.scalars().all()

    type_result = await db.execute(
        select(ArtifactTypeRegistry).order_by(ArtifactTypeRegistry.sort_order)
    )
    all_types = {r.type_key: r for r in type_result.scalars().all()}

    items = []
    for t_key, t_reg in all_types.items():
        art = next((a for a in artifacts if a.artifact_type == t_key), None)
        items.append({
            "type_key": t_key,
            "display_name": t_reg.display_name,
            "icon": t_reg.icon,
            "tab_group": t_reg.tab_group,
            "category": t_reg.category,
            "has_content": bool(art and art.content),
            "version": art.version if art else 0,
            "status": art.status if art else "empty",
            "artifact_id": str(art.id) if art else None,
            "updated_at": art.updated_at.isoformat() if art and art.updated_at else None,
        })

    return {"task_id": task_id, "artifacts": items}


@router.get("/{task_id}/artifacts/{artifact_type}")
async def get_artifact(
    task_id: str,
    artifact_type: str,
    version: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_pipeline_auth_optional),
):
    filters = [
        TaskArtifact.task_id == uuid.UUID(task_id),
        TaskArtifact.artifact_type == artifact_type,
    ]
    if version:
        filters.append(TaskArtifact.version == version)
    else:
        filters.append(TaskArtifact.is_latest == True)

    result = await db.execute(select(TaskArtifact).where(and_(*filters)))
    art = result.scalar_one_or_none()
    if not art:
        return {
            "id": "",
            "task_id": task_id,
            "artifact_type": artifact_type,
            "title": "",
            "content": "",
            "version": 0,
            "is_latest": True,
            "status": "empty",
            "mime_type": "text/markdown",
            "storage_path": "",
            "created_by_agent": None,
            "created_by_user": None,
            "metadata": None,
            "created_at": None,
            "updated_at": None,
            "versions": [],
        }

    versions_result = await db.execute(
        select(TaskArtifact.version, TaskArtifact.status, TaskArtifact.created_at)
        .where(TaskArtifact.task_id == uuid.UUID(task_id))
        .where(TaskArtifact.artifact_type == artifact_type)
        .order_by(TaskArtifact.version.desc())
    )
    version_history = [
        {"version": v, "status": s, "created_at": c.isoformat() if c else None}
        for v, s, c in versions_result.all()
    ]

    return {
        "id": str(art.id),
        "task_id": task_id,
        "artifact_type": art.artifact_type,
        "title": art.title,
        "content": art.content,
        "version": art.version,
        "is_latest": art.is_latest,
        "status": art.status,
        "mime_type": art.mime_type,
        "storage_path": art.storage_path,
        "created_by_agent": art.created_by_agent,
        "created_by_user": art.created_by_user,
        "metadata": art.metadata_json,
        "created_at": art.created_at.isoformat() if art.created_at else None,
        "updated_at": art.updated_at.isoformat() if art.updated_at else None,
        "versions": version_history,
    }


@router.post("/{task_id}/artifacts/{artifact_type}", status_code=201)
async def create_or_update_artifact(
    task_id: str,
    artifact_type: str,
    body: CreateArtifactRequest,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_pipeline_auth),
):
    type_check = await db.execute(
        select(ArtifactTypeRegistry).where(ArtifactTypeRegistry.type_key == artifact_type)
    )
    if not type_check.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"未注册的工件类型: {artifact_type}")

    existing = await db.execute(
        select(TaskArtifact)
        .where(TaskArtifact.task_id == uuid.UUID(task_id))
        .where(TaskArtifact.artifact_type == artifact_type)
        .where(TaskArtifact.is_latest == True)
    )
    current = existing.scalar_one_or_none()

    new_version = (current.version + 1) if current else 1

    if current:
        current.is_latest = False
        await db.flush()

    art = TaskArtifact(
        task_id=uuid.UUID(task_id),
        artifact_type=artifact_type,
        stage_id=body.stage_id,
        title=body.title or artifact_type,
        content=body.content,
        mime_type=body.mime_type,
        storage_path=body.storage_path,
        version=new_version,
        is_latest=True,
        status="active",
        created_by_agent=body.created_by_agent,
        created_by_user=str(user.id) if user else None,
    )
    db.add(art)
    await db.flush()

    from ..services.manifest_sync import trigger_manifest_refresh
    try:
        await trigger_manifest_refresh(task_id)
    except Exception:
        pass

    return {
        "id": str(art.id),
        "artifact_type": artifact_type,
        "version": new_version,
        "status": "active",
    }


@router.post("/{task_id}/artifacts/{artifact_type}/supersede")
async def supersede_artifact(
    task_id: str,
    artifact_type: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_pipeline_auth),
):
    """Mark the latest version of an artifact as superseded (e.g. on reject)."""
    result = await db.execute(
        select(TaskArtifact)
        .where(TaskArtifact.task_id == uuid.UUID(task_id))
        .where(TaskArtifact.artifact_type == artifact_type)
        .where(TaskArtifact.is_latest == True)
    )
    art = result.scalar_one_or_none()
    if not art:
        raise HTTPException(status_code=404, detail="工件不存在")

    art.status = "superseded"
    await db.flush()
    return {"ok": True, "version": art.version, "status": "superseded"}
