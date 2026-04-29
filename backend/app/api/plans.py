"""Plan Inbox API — web-side approve/reject/revise of pending IM plans.

The Plan/Act dual-mode (gateway.py) parks plans in Redis under
`gateway:plan:<source>:<user_id>` waiting for user approval via IM. This API
mirrors that workflow for ops-on-web who'd rather click than IM.

Endpoints:
  GET    /plans                                 — list all pending plans
  GET    /plans/{source}/{user_id}              — full plan detail
  POST   /plans/{source}/{user_id}/approve      — clear session + start pipeline
  POST   /plans/{source}/{user_id}/reject       — discard plan
  POST   /plans/{source}/{user_id}/revise       — re-generate with feedback

Approve uses the same `_create_task_from_gateway` + `_run_pipeline_background`
helpers the IM gateway uses, so behavior is identical regardless of channel.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.pipeline import PipelineTask
from ..models.user import User
from ..security import get_current_user, require_admin
from ..services import plan_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/plans", tags=["plans"])


# ───── Schemas ─────────────────────────────────────────────────────

class ReviseBody(BaseModel):
    feedback: str = Field(..., min_length=1, description="What to change in the plan")


# ───── Helpers ─────────────────────────────────────────────────────

def _summarize(entry: Dict[str, Any]) -> Dict[str, Any]:
    payload = entry.get("payload") or {}
    plan = payload.get("plan") or {}
    steps = plan.get("steps") or []
    options = _runtime_options(payload)
    return {
        "source": entry["source"],
        "user_id": entry["user_id"],
        "title": payload.get("title", ""),
        "description_snippet": (payload.get("description") or "")[:200],
        "step_count": len(steps),
        "rotation_count": int(payload.get("rotation_count") or 0),
        "started_at": payload.get("started_at"),
        "max_rotations": plan_session.MAX_ROTATIONS,
        "auto_final_accept": options["auto_final_accept"],
        "source_message_id": options["source_message_id"],
    }


def _full(entry: Dict[str, Any]) -> Dict[str, Any]:
    payload = entry.get("payload") or {}
    options = _runtime_options(payload)
    return {
        "source": entry["source"],
        "user_id": entry["user_id"],
        "title": payload.get("title", ""),
        "description": payload.get("description", ""),
        "plan": payload.get("plan") or {},
        "rotation_count": int(payload.get("rotation_count") or 0),
        "started_at": payload.get("started_at"),
        "max_rotations": plan_session.MAX_ROTATIONS,
        "auto_final_accept": options["auto_final_accept"],
        "source_message_id": options["source_message_id"],
    }


def _runtime_options(payload: Dict[str, Any]) -> Dict[str, Any]:
    meta = payload.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    return {
        "auto_final_accept": bool(meta.get("auto_final_accept", False)),
        "source_message_id": str(meta.get("source_message_id") or ""),
        "pending_task_id": str(meta.get("pending_task_id") or ""),
    }


# ───── Endpoints ───────────────────────────────────────────────────

@router.get("")
async def list_plans(user: Annotated[User, Depends(get_current_user)]):
    items = await plan_session.list_pending()
    return {"count": len(items), "items": [_summarize(e) for e in items]}


@router.get("/{source}/{user_id}")
async def get_plan(
    source: str,
    user_id: str,
    user: Annotated[User, Depends(get_current_user)],
):
    payload = await plan_session.load_plan(source, user_id)
    if not payload:
        raise HTTPException(status_code=404, detail="no pending plan for this user")
    return _full({"source": source, "user_id": user_id, "payload": payload})


@router.post("/{source}/{user_id}/approve")
async def approve_plan(
    source: str,
    user_id: str,
    background_tasks: BackgroundTasks,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Approve from web: identical effect to user replying '开干' on IM."""
    from . import gateway  # circular-import safe (lazy)

    payload = await plan_session.load_plan(source, user_id)
    if not payload:
        raise HTTPException(status_code=404, detail="no pending plan")
    title = str(payload.get("title") or "")
    description = str(payload.get("description") or "")
    if not title:
        raise HTTPException(status_code=400, detail="plan has no title; cannot create task")

    options = _runtime_options(payload)
    await plan_session.clear_plan(source, user_id)

    task = None
    pending_task_id = options.get("pending_task_id") or ""
    if pending_task_id:
        try:
            result = await db.execute(
                select(PipelineTask)
                .options(selectinload(PipelineTask.stages))
                .where(PipelineTask.id == uuid.UUID(pending_task_id))
            )
            task = result.scalar_one_or_none()
        except Exception:
            task = None

    if task:
        if admin.org_id and task.org_id is None:
            task.org_id = admin.org_id
        task.status = "active"
        task.current_stage_id = "planning"
        for stage in sorted(task.stages, key=lambda s: s.sort_order):
            if stage.stage_id == "planning":
                stage.status = "active"
                stage.started_at = datetime.utcnow()
            elif stage.status != "done":
                stage.status = "pending"
                stage.started_at = None
        await db.flush()
    else:
        task = await gateway._create_task_from_gateway(
            db,
            title,
            description,
            source,
            options.get("source_message_id") or "",
            user_id,
            org_id=admin.org_id,
        )
        await db.flush()

    if options["auto_final_accept"]:
        task.auto_final_accept = True
        await db.flush()

    await gateway._commit_task_before_background(db, task)

    background_tasks.add_task(
        gateway._run_pipeline_background,
        str(task.id),
        title,
        description,
        pause_for_acceptance=not options["auto_final_accept"],
    )

    try:
        from ..services.notify import notify_user_text
        await notify_user_text(
            source=source, user_id=user_id,
            title="🚀 已开干（web 审批）",
            body=f"任务已启动：{title}\nID: {task.id}",
        )
    except Exception as e:
        logger.debug(f"[plans.approve] IM notify failed: {e}")

    return {
        "ok": True,
        "action": "plan_approved",
        "taskId": str(task.id),
        "pipelineTriggered": True,
        "autoFinalAccept": options["auto_final_accept"],
    }


@router.post("/{source}/{user_id}/reject")
async def reject_plan(
    source: str,
    user_id: str,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    payload = await plan_session.load_plan(source, user_id)
    if not payload:
        raise HTTPException(status_code=404, detail="no pending plan")
    options = _runtime_options(payload)
    pending_task_id = options.get("pending_task_id") or ""
    await plan_session.clear_plan(source, user_id)

    if pending_task_id:
        try:
            result = await db.execute(
                select(PipelineTask).where(PipelineTask.id == uuid.UUID(pending_task_id))
            )
            t = result.scalar_one_or_none()
            if t:
                t.status = "cancelled"
                await db.flush()
        except Exception as e:
            logger.warning("[plans.reject] pending task cancel failed: %s", e)

    try:
        from ..services.notify import notify_user_text
        await notify_user_text(
            source=source, user_id=user_id,
            title="🛑 计划已被取消（web）",
            body="管理员在控制台取消了此次计划，可以重新发送新需求。",
        )
    except Exception as e:
        logger.debug(f"[plans.reject] IM notify failed: {e}")

    return {"ok": True, "action": "plan_rejected"}


@router.post("/{source}/{user_id}/revise")
async def revise_plan(
    source: str,
    user_id: str,
    body: ReviseBody,
    admin: Annotated[User, Depends(require_admin)],
):
    """Regenerate plan with web-supplied feedback. Same MAX_ROTATIONS cap as IM."""
    from . import gateway

    payload = await plan_session.load_plan(source, user_id)
    if not payload:
        raise HTTPException(status_code=404, detail="no pending plan")

    rotation = int(payload.get("rotation_count") or 0)
    if rotation >= plan_session.MAX_ROTATIONS:
        await plan_session.clear_plan(source, user_id)
        raise HTTPException(
            status_code=400,
            detail=f"max rotations reached ({plan_session.MAX_ROTATIONS}); please re-submit a new requirement",
        )

    title = str(payload.get("title") or "")
    description = str(payload.get("description") or "")
    options = _runtime_options(payload)

    result = await gateway._present_plan_and_wait(
        source=source,
        source_user_id=user_id,
        title=title,
        description=description,
        feedback_addendum=body.feedback,
        metadata={
            "auto_final_accept": options["auto_final_accept"],
            "source_message_id": options["source_message_id"],
        },
    )

    new_pending = await plan_session.load_plan(source, user_id)
    if new_pending:
        new_pending["rotation_count"] = rotation + 1
        await plan_session.save_plan(source, user_id, new_pending)
    result["rotation_count"] = rotation + 1
    return result
