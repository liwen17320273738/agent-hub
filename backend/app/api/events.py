"""
SSE Events endpoint — real-time pipeline event streaming.

Replaces Node.js server/events.mjs SSE with FastAPI StreamingResponse
backed by Redis Pub/Sub (works across multiple Uvicorn workers).
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from ..models.user import User
from ..security import get_pipeline_auth
from ..services.sse import event_stream, get_sse_client_count

router = APIRouter(tags=["events"])


@router.get("/pipeline/events")
async def pipeline_sse(
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    """Server-Sent Events stream for real-time pipeline updates."""
    return EventSourceResponse(event_stream())


@router.get("/pipeline/health")
async def pipeline_health():
    from ..config import settings
    import shutil

    return {
        "pipeline": "online",
        "sseClients": await get_sse_client_count(),
        "feishu": bool(getattr(settings, "feishu_app_id", "")),
        "qq": bool(getattr(settings, "qq_bot_endpoint", "")),
        "executor": shutil.which("claude") is not None,
    }
