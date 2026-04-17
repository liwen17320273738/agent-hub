"""Agent message bus REST endpoints.

Thin wrapper around ``services.agent_bus`` so the frontend (and external
operators) can:

* ``POST /api/agent-bus/publish`` — drop a message on a topic
* ``GET  /api/agent-bus/recent`` — replay persisted messages
* ``GET  /api/agent-bus/stream`` — SSE live tail (filtered by topic / task)

Authentication: requires a logged-in user (any role); the bus is an
internal collaboration channel, not user-facing.
"""
from __future__ import annotations

import json
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..security import get_current_user
from ..services import agent_bus

router = APIRouter(prefix="/agent-bus", tags=["agent-bus"])


class PublishBody(BaseModel):
    topic: str
    sender: str = "user"
    task_id: Optional[str] = None
    payload: dict = {}


@router.post("/publish")
async def publish_message(
    body: PublishBody,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not body.topic.strip():
        raise HTTPException(status_code=400, detail="topic is required")
    msg = await agent_bus.publish(
        db,
        topic=body.topic.strip(),
        sender=body.sender or user.email,
        task_id=body.task_id,
        payload=body.payload or {},
    )
    await db.commit()
    return {"ok": True, "message": msg}


@router.get("/recent")
async def list_recent(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    topic: Optional[str] = None,
    task_id: Optional[str] = None,
    limit: int = 50,
):
    rows = await agent_bus.get_recent(db, topic=topic, task_id=task_id, limit=limit)
    return {"ok": True, "messages": rows}


@router.get("/stream")
async def stream_messages(
    user: Annotated[User, Depends(get_current_user)],
    topic: Optional[str] = None,
    task_id: Optional[str] = None,
):
    async def _gen():
        yield 'data: {"event":"connected"}\n\n'
        async for body in agent_bus.stream(topic=topic, task_id=task_id):
            yield f"data: {json.dumps(body, ensure_ascii=False, default=str)}\n\n"
    return StreamingResponse(_gen(), media_type="text/event-stream")
