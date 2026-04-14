"""
Gateway API — unified message intake from Feishu, QQ, OpenClaw, and webhooks.

After creating a task, automatically triggers pipeline execution in the background.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from ..config import settings
from ..database import get_db, async_session_factory
from ..models.pipeline import PipelineTask, PipelineStage
from ..services.sse import emit_event
from ..services.collaboration import PIPELINE_STAGES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gateway", tags=["gateway"])


def _default_stages():
    return [
        {"stage_id": s["id"], "label": s["label"], "owner_role": s["role"], "sort_order": i}
        for i, s in enumerate(PIPELINE_STAGES)
    ]


async def _create_task_from_gateway(
    db: AsyncSession,
    title: str,
    description: str,
    source: str,
    source_message_id: str = "",
    source_user_id: str = "",
) -> PipelineTask:
    task = PipelineTask(
        title=title,
        description=description,
        source=source,
        source_message_id=source_message_id or None,
        source_user_id=source_user_id or None,
        created_by="gateway",
        current_stage_id="planning",
    )
    db.add(task)
    await db.flush()

    for stage_data in _default_stages():
        stage = PipelineStage(task_id=task.id, **stage_data)
        if stage_data["stage_id"] == "planning":
            stage.status = "active"
            stage.started_at = datetime.utcnow()
        db.add(stage)
    await db.flush()

    await emit_event("task:created", {
        "taskId": str(task.id), "title": title, "source": source,
    })
    return task


async def _run_pipeline_background(task_id: str, title: str, description: str):
    """Run FULL end-to-end flow: pipeline → codegen → build → deploy → preview."""
    from ..services.e2e_orchestrator import run_full_e2e

    try:
        async with async_session_factory() as db:
            async with db.begin():
                result = await run_full_e2e(
                    db,
                    task_id=task_id,
                    task_title=title,
                    task_description=description,
                    auto_deploy=True,
                    dag_template="full",
                )
                phases = {k: v.get("ok", False) for k, v in result.get("phases", {}).items()}
                logger.info(
                    f"[gateway] E2E completed for task {task_id}: "
                    f"ok={result.get('ok')} url={result.get('url', '')} phases={phases}"
                )
    except Exception as e:
        logger.error(f"[gateway] E2E failed for task {task_id}: {e}")


async def _try_parse_feedback(
    text: str,
    source: str,
    user_id: str,
) -> Optional[Dict[str, Any]]:
    """Check if message is feedback for an existing task (e.g. "通过", "修改：xxx").

    Feedback is detected by prefixes like "反馈:" or "task:xxx" or
    known approval keywords. Returns None if it's a new task.
    """
    import re

    task_match = re.match(r"(?:task|任务)[：:]\s*([a-f0-9-]{8,})\s*[,，\s]*(.*)", text, re.IGNORECASE)
    if task_match:
        task_id = task_match.group(1)
        content = task_match.group(2).strip() or "通过"
        from ..services.interaction.feedback import feedback_loop
        item = await feedback_loop.parse_im_feedback(task_id, content, source, user_id)
        result = await feedback_loop.process_feedback(item.id)
        return {"ok": True, "action": "feedback", "feedbackId": item.id, **result}

    return None


# --- OpenClaw Gateway ---

class OpenClawIntakeRequest(BaseModel):
    title: str
    description: str = ""
    source: str = "api"
    messageId: str = ""
    userId: str = ""


@router.post("/openclaw/intake")
async def openclaw_intake(
    body: OpenClawIntakeRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    secret = settings.pipeline_api_key
    if secret:
        auth = request.headers.get("authorization", "")
        token = auth.replace("Bearer ", "").strip() if auth.startswith("Bearer ") else ""
        if token != secret:
            raise HTTPException(status_code=403, detail="Invalid gateway secret")

    if not body.title.strip():
        raise HTTPException(status_code=400, detail="title is required")

    task = await _create_task_from_gateway(
        db, body.title, body.description, body.source,
        body.messageId, body.userId,
    )

    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages))
        .where(PipelineTask.id == task.id)
    )
    full_task = result.scalar_one()

    background_tasks.add_task(
        _run_pipeline_background, str(task.id), body.title, body.description,
    )

    return {"ok": True, "taskId": str(task.id), "pipelineTriggered": True, "task": full_task}


@router.get("/openclaw/status")
async def openclaw_status():
    return {"gateway": "openclaw", "status": "online"}


# --- Feishu Webhook ---

class FeishuWebhookBody(BaseModel):
    challenge: Optional[str] = None
    type: Optional[str] = None
    event: Optional[Dict[str, Any]] = None
    header: Optional[Dict[str, Any]] = None


@router.post("/feishu/webhook")
async def feishu_webhook(
    body: FeishuWebhookBody,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if body.challenge:
        return {"challenge": body.challenge}

    verify_token = getattr(settings, "feishu_verification_token", "")
    if verify_token and body.header:
        token = body.header.get("token", "")
        if token != verify_token:
            raise HTTPException(status_code=403, detail="Invalid Feishu verification token")

    event = body.event or {}
    msg = event.get("message", {})
    content_raw = msg.get("content", "{}")

    try:
        content_obj = json.loads(content_raw)
        text = content_obj.get("text", content_raw)
    except (json.JSONDecodeError, TypeError):
        text = str(content_raw)

    if not text.strip():
        return {"ok": True, "action": "ignored", "reason": "empty message"}

    sender = event.get("sender", {}).get("sender_id", {})
    user_id = sender.get("open_id", "")
    message_id = msg.get("message_id", "")

    feedback_result = await _try_parse_feedback(text, "feishu", user_id)
    if feedback_result:
        return feedback_result

    task = await _create_task_from_gateway(
        db, text[:200], text, "feishu", message_id, user_id,
    )

    background_tasks.add_task(
        _run_pipeline_background, str(task.id), text[:200], text,
    )

    return {"ok": True, "taskId": str(task.id), "pipelineTriggered": True}


# --- QQ Webhook ---

class QQWebhookBody(BaseModel):
    content: Optional[str] = None
    author: Optional[Dict[str, Any]] = None
    id: Optional[str] = None


@router.post("/qq/webhook")
async def qq_webhook(
    body: QQWebhookBody,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    text = (body.content or "").strip()
    if not text:
        return {"ok": True, "action": "ignored"}

    user_id = (body.author or {}).get("id", "")
    message_id = body.id or ""

    feedback_result = await _try_parse_feedback(text, "qq", user_id)
    if feedback_result:
        return feedback_result

    task = await _create_task_from_gateway(
        db, text[:200], text, "qq", message_id, user_id,
    )

    background_tasks.add_task(
        _run_pipeline_background, str(task.id), text[:200], text,
    )

    return {"ok": True, "taskId": str(task.id), "pipelineTriggered": True}
