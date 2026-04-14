"""Interaction API — preview, feedback, and post-launch monitoring."""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..security import get_pipeline_auth

router = APIRouter(prefix="/interaction", tags=["interaction"])


# ── Preview ─────────────────────────────────────────────────────────

class CapturePreviewRequest(BaseModel):
    task_id: str
    url: str
    channel: str = ""
    webhook_url: str = ""


@router.post("/preview")
async def capture_preview(
    body: CapturePreviewRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    from ..services.interaction.preview import PreviewService

    svc = PreviewService()
    return await svc.capture_and_notify(
        task_id=body.task_id,
        preview_url=body.url,
        channel=body.channel,
        webhook_url=body.webhook_url,
    )


# ── Feedback ────────────────────────────────────────────────────────

class SubmitFeedbackRequest(BaseModel):
    task_id: str
    content: str
    source: str = "api"
    user_id: str = ""
    feedback_type: str = "revision"


@router.post("/feedback")
async def submit_feedback(
    body: SubmitFeedbackRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    from ..services.interaction.feedback import feedback_loop

    item = await feedback_loop.submit_feedback(
        task_id=body.task_id,
        content=body.content,
        source=body.source,
        user_id=body.user_id or (str(user.id) if user else ""),
        feedback_type=body.feedback_type,
    )
    return {"ok": True, "feedback": item.to_dict()}


class ProcessFeedbackRequest(BaseModel):
    feedback_id: str


@router.post("/feedback/process")
async def process_feedback(
    body: ProcessFeedbackRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from ..services.interaction.feedback import feedback_loop

    result = await feedback_loop.process_feedback(body.feedback_id, db)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Not found"))

    if result.get("action") == "iterate" and result.get("stagesToRerun"):
        from ..services.pipeline_engine import execute_stage
        from sqlalchemy import select
        from ..models.pipeline import PipelineTask
        from sqlalchemy.orm import selectinload
        import uuid

        task_id = result["taskId"]
        task_result = await db.execute(
            select(PipelineTask)
            .options(selectinload(PipelineTask.stages))
            .where(PipelineTask.id == uuid.UUID(task_id))
        )
        task = task_result.scalar_one_or_none()
        if task:
            previous_outputs = {}
            for stage in task.stages:
                if stage.output:
                    previous_outputs[stage.stage_id] = stage.output

            extra_context = f"\n\n## 用户反馈（第 {result['iteration']} 轮）\n{result['feedbackContent']}"

            for stage_id in result["stagesToRerun"]:
                stage_result = await execute_stage(
                    db,
                    task_id=task_id,
                    task_title=task.title,
                    task_description=task.description + extra_context,
                    stage_id=stage_id,
                    previous_outputs=previous_outputs,
                )
                if stage_result.get("ok"):
                    previous_outputs[stage_id] = stage_result.get("content", "")

            result["iterationComplete"] = True

    return result


@router.get("/feedback/{task_id}")
async def get_task_feedback(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    from ..services.interaction.feedback import feedback_loop

    items = feedback_loop.get_task_feedback(task_id)
    return {
        "taskId": task_id,
        "feedback": [item.to_dict() for item in items],
    }


# ── Monitoring ──────────────────────────────────────────────────────

class StartMonitorRequest(BaseModel):
    task_id: str
    url: str
    interval: int = 60


@router.post("/monitor/start")
async def start_monitoring(
    body: StartMonitorRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    from ..services.interaction.monitor import post_launch_monitor

    return await post_launch_monitor.start_monitoring(
        task_id=body.task_id,
        url=body.url,
        interval=body.interval,
    )


class StopMonitorRequest(BaseModel):
    task_id: str
    url: str


@router.post("/monitor/stop")
async def stop_monitoring(
    body: StopMonitorRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    from ..services.interaction.monitor import post_launch_monitor

    return await post_launch_monitor.stop_monitoring(body.task_id, body.url)


@router.get("/monitor/{task_id}")
async def get_monitor_status(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    from ..services.interaction.monitor import post_launch_monitor

    return {
        "taskId": task_id,
        "monitors": post_launch_monitor.get_status(task_id),
    }


@router.get("/monitor")
async def get_all_monitors(
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    from ..services.interaction.monitor import post_launch_monitor

    return {"monitors": post_launch_monitor.get_all_status()}
