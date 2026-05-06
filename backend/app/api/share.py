"""
Public share API — unauthenticated access to task deliverables via signed token.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models.pipeline import PipelineTask
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

    ttl = max(1, min(body.ttl_days, 365))
    token = create_share_token(body.task_id, ttl_days=ttl)
    return GenerateLinkResponse(
        token=token,
        url=f"/share/{token}",
        expires_in_days=ttl,
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

    stages_data = []
    for s in sorted(task.stages, key=lambda x: x.sort_order):
        stages_data.append({
            "stage_id": s.stage_id,
            "label": s.label,
            "status": s.status,
            "owner_role": s.owner_role,
        })

    return {
        "task_id": str(task.id),
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "final_acceptance_status": task.final_acceptance_status,
        "stages": stages_data,
        "docs": docs,
    }


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
