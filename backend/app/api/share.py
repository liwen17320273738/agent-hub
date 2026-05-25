"""
Public share API — unauthenticated access to task deliverables via signed token.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..database import get_db
from ..models.pipeline import PipelineTask
from ..models.task_artifact import TaskArtifact
from ..services.share_token import create_share_token, verify_share_token
from ..services.task_workspace import list_task_docs, read_task_doc
from ..security import get_current_user

router = APIRouter(prefix="/share", tags=["share"])


class GenerateLinkRequest(BaseModel):
    task_id: str
    ttl_days: int = 7


class GenerateLinkResponse(BaseModel):
    token: str
    url: str
    expires_in_days: int
    draft: bool = False
    evidence: Optional[Dict[str, Any]] = None


@router.post("/generate", response_model=GenerateLinkResponse)
async def generate_share_link(
    body: GenerateLinkRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.execute(
        select(PipelineTask).where(PipelineTask.id == uuid.UUID(body.task_id))
    )
    task = row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # Trustworthy-delivery gate: real test + real preview + real evidence
    # must exist before a share link goes out. Workspace can opt in to
    # "draft delivery" — link is still issued but the task status flips to
    # awaiting_evidence so downstream UI can render a draft banner.
    from ..services.delivery_contract import verify_delivery_evidence
    check = await verify_delivery_evidence(db, task)
    draft = False
    if not check.ok:
        if not check.workspace_allows_draft:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "evidence_missing",
                    "message": check.summary,
                    "evidence": check.to_dict(),
                },
            )
        draft = True
        if task.status != "awaiting_evidence":
            task.status = "awaiting_evidence"
            await db.commit()

    ttl = max(1, min(body.ttl_days, 365))
    token = create_share_token(body.task_id, ttl_days=ttl)
    return GenerateLinkResponse(
        token=token,
        url=f"/share/{token}",
        expires_in_days=ttl,
        draft=draft,
        evidence=check.to_dict() if draft else None,
    )


@router.get("/{token}")
async def get_shared_task(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    task_id = verify_share_token(token)
    if not task_id:
        raise HTTPException(status_code=403, detail="分享链接无效或已过期")

    row = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages))
        .where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    docs = await list_task_docs(task_id, task.title or "untitled")
    artifact_rows = await db.execute(
        select(TaskArtifact)
        .where(TaskArtifact.task_id == uuid.UUID(task_id))
        .where(TaskArtifact.is_latest.is_(True))
        .order_by(TaskArtifact.artifact_type)
    )
    artifacts = artifact_rows.scalars().all()

    stages_data = []
    for s in sorted(task.stages, key=lambda x: x.sort_order):
        stages_data.append({
            "stage_id": s.stage_id,
            "label": s.label,
            "status": s.status,
            "owner_role": s.owner_role,
        })

    # Evidence summary — exposed to SharePage so external customers can see
    # a "draft delivery" banner when the workspace shipped without real
    # test/preview proof.
    from ..services.delivery_contract import verify_delivery_evidence
    evidence = await verify_delivery_evidence(db, task)

    artifacts_data = []
    for art in artifacts:
        artifacts_data.append({
            "id": str(art.id),
            "artifact_type": art.artifact_type,
            "type_key": art.artifact_type,
            "title": art.title,
            "content": art.content,
            "stage_id": art.stage_id,
            "status": art.status,
            "mime_type": art.mime_type,
            "storage_path": art.storage_path,
            "version": art.version,
            "is_latest": art.is_latest,
            "created_at": art.created_at.isoformat() if art.created_at else None,
            "updated_at": art.updated_at.isoformat() if art.updated_at else None,
            "metadata_json": art.metadata_json or {},
        })

    return {
        "task_id": str(task.id),
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "final_acceptance_status": task.final_acceptance_status,
        "final_acceptance_at": task.final_acceptance_at.isoformat() if task.final_acceptance_at else None,
        "final_acceptance_feedback": task.final_acceptance_feedback,
        "owner_email": task.created_by,
        "expires_at": None,
        "stages": stages_data,
        "docs": docs,
        "artifacts": artifacts_data,
        "evidence": evidence.to_dict(),
        "is_draft_delivery": (not evidence.ok),
    }


@router.get("/{token}/artifact-contract")
async def get_shared_artifact_contract(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    task_id = verify_share_token(token)
    if not task_id:
        raise HTTPException(status_code=403, detail="分享链接无效或已过期")

    row = await db.execute(
        select(PipelineTask).where(PipelineTask.id == uuid.UUID(task_id)),
    )
    if row.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    from ..services.artifact_contract import build_task_contract_report

    return await build_task_contract_report(db, task_id)


@router.get("/{token}/worktree/raw/{file_path:path}")
async def get_shared_worktree_file_raw(
    token: str,
    file_path: str,
    db: AsyncSession = Depends(get_db),
):
    """Public raw file preview for share-page iframe/img (token-gated)."""
    task_id = verify_share_token(token)
    if not task_id:
        raise HTTPException(status_code=403, detail="分享链接无效或已过期")

    from .worktree import _guess_media_type, _resolve_worktree_file
    from ..services.visual_asset_repair import is_visual_asset_path, repair_visual_asset

    try:
        target = _resolve_worktree_file(task_id, file_path)
    except HTTPException as exc:
        if exc.status_code == 404 and is_visual_asset_path(file_path):
            repaired = await repair_visual_asset(db, task_id, file_path)
            if repaired:
                target = repaired
            else:
                raise
        else:
            raise
    # NOTE: see backend/app/api/worktree.py for why we omit `filename=` — passing
    # it forces `Content-Disposition: attachment`, which makes the iframe on
    # the public SharePage trigger downloads instead of rendering inline.
    return FileResponse(target, media_type=_guess_media_type(target))


@router.get("/{token}/doc/{doc_name}")
async def get_shared_doc(token: str, doc_name: str, db: AsyncSession = Depends(get_db)):
    task_id = verify_share_token(token)
    if not task_id:
        raise HTTPException(status_code=403, detail="分享链接无效或已过期")

    row = await db.execute(
        select(PipelineTask).where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    doc_key = doc_name if doc_name.endswith(".md") else f"{doc_name}.md"
    content = await read_task_doc(task_id, task.title or "untitled", doc_key)
    if content is None:
        content = await read_task_doc(task_id, task.title or "untitled", doc_name)
    if content is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"doc_name": doc_name, "content": content}


@router.post("/{token}/accept")
async def share_accept(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    task_id = verify_share_token(token)
    if not task_id:
        raise HTTPException(status_code=403, detail="分享链接无效或已过期")

    row = await db.execute(
        select(PipelineTask).where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status != "awaiting_final_acceptance":
        raise HTTPException(status_code=400, detail=f"任务状态不允许验收: {task.status}")

    # Evidence gate before accepting: even if a draft share link was issued,
    # external customers cannot mark "delivered" unless the workspace opted
    # into draft delivery.
    from ..services.delivery_contract import verify_delivery_evidence
    check = await verify_delivery_evidence(db, task)
    if not check.ok and not check.workspace_allows_draft:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "evidence_missing",
                "message": check.summary,
                "evidence": check.to_dict(),
            },
        )

    from datetime import datetime
    task.status = "done"
    task.current_stage_id = "done"
    task.final_acceptance_status = "accepted"
    task.final_acceptance_by = "share_link"
    task.final_acceptance_at = datetime.utcnow()
    await db.commit()

    from ..services.sse import emit_event
    await emit_event("pipeline:final-accepted", {
        "taskId": task_id, "by": "share_link", "via": "share",
    })

    return {"ok": True, "action": "accepted", "task_id": task_id}


@router.post("/{token}/reject")
async def share_reject(
    token: str,
    body: dict = {},
    db: AsyncSession = Depends(get_db),
):
    task_id = verify_share_token(token)
    if not task_id:
        raise HTTPException(status_code=403, detail="分享链接无效或已过期")

    row = await db.execute(
        select(PipelineTask).where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status != "awaiting_final_acceptance":
        raise HTTPException(status_code=400, detail=f"任务状态不允许打回: {task.status}")

    reason = str(body.get("reason", "客户通过分享链接打回"))[:1000]
    task.status = "paused"
    task.final_acceptance_status = "rejected"
    task.final_acceptance_by = "share_link"
    task.final_acceptance_feedback = reason
    await db.commit()

    from ..services.sse import emit_event
    await emit_event("pipeline:final-rejected", {
        "taskId": task_id, "by": "share_link", "via": "share", "reason": reason,
    })

    return {"ok": True, "action": "rejected", "task_id": task_id}
