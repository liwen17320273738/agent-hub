"""
SSE Events endpoint — real-time pipeline event streaming.

Uses short-lived tickets (30s TTL) stored in Redis instead of passing JWT
in URL to avoid token leakage in logs, proxies, and browser history.
Redis handles ticket expiry automatically via TTL.
"""
from __future__ import annotations

import secrets
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from ..models.user import User
from ..redis_client import get_redis
from ..security import get_pipeline_auth
from ..services.sse import event_stream, get_sse_client_count

# User / get_pipeline_auth still used by POST /ticket and GET /health below

router = APIRouter(tags=["events"])

_TICKET_TTL = 30
_TICKET_PREFIX = "sse:ticket:"


@router.post("/pipeline/events/ticket")
async def create_sse_ticket(
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    """Issue a short-lived ticket for SSE connection (avoids JWT in URL)."""
    ticket = secrets.token_urlsafe(32)
    r = get_redis()
    await r.setex(f"{_TICKET_PREFIX}{ticket}", _TICKET_TTL, "1")
    return {"ticket": ticket}


@router.get("/pipeline/events")
async def pipeline_sse(
    ticket: Optional[str] = Query(None),
):
    """Server-Sent Events stream for real-time pipeline updates.

    EventSource cannot send Authorization headers, so SSE uses a
    short-lived ticket obtained from POST /pipeline/events/ticket.
    """
    if not ticket:
        raise HTTPException(status_code=401, detail="Missing SSE ticket parameter")
    r = get_redis()
    key = f"{_TICKET_PREFIX}{ticket}"
    val = await r.get(key)
    if not val:
        raise HTTPException(status_code=401, detail="Invalid or expired SSE ticket")
    await r.delete(key)
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
