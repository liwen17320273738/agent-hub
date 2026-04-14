"""Conversations API with optimistic locking."""
from __future__ import annotations

import uuid
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.conversation import Conversation
from ..models.user import User
from ..security import get_current_user

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    agent_id: str
    title: str = "新对话"


class ConversationUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    messages: Optional[List[Dict[str, Any]]] = None
    expected_revision: int


class ConversationOut(BaseModel):
    id: str
    agent_id: str
    title: str
    messages: list[dict]
    summary: Optional[str] = None
    revision: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


@router.get("/")
async def list_conversations(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    stmt = (
        select(Conversation)
        .where(Conversation.org_id == user.org_id)
        .order_by(Conversation.updated_at.desc())
    )
    result = await db.execute(stmt)
    convos = result.scalars().all()
    return [_to_out(c) for c in convos]


@router.post("/", status_code=201)
async def create_conversation(
    body: ConversationCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not body.agent_id.strip():
        raise HTTPException(status_code=400, detail="缺少 agent_id")

    convo = Conversation(
        org_id=user.org_id,
        agent_id=body.agent_id.strip(),
        title=body.title.strip() or "新对话",
        messages=[],
        created_by=user.id,
    )
    db.add(convo)
    await db.flush()
    return _to_out(convo)


@router.patch("/{convo_id}")
async def update_conversation(
    convo_id: str,
    body: ConversationUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == uuid.UUID(convo_id),
            Conversation.org_id == user.org_id,
        )
    )
    convo = result.scalar_one_or_none()
    if not convo:
        raise HTTPException(status_code=404, detail="会话不存在")

    if convo.revision != body.expected_revision:
        raise HTTPException(
            status_code=409,
            detail="会话已被其他成员或另一窗口更新",
        )

    if body.title is not None:
        convo.title = body.title
    if body.summary is not None:
        convo.summary = body.summary if body.summary else None
    if body.messages is not None:
        convo.messages = body.messages
    convo.revision += 1

    await db.flush()
    return _to_out(convo)


@router.delete("/{convo_id}")
async def delete_conversation(
    convo_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == uuid.UUID(convo_id),
            Conversation.org_id == user.org_id,
        )
    )
    convo = result.scalar_one_or_none()
    if not convo:
        raise HTTPException(status_code=404, detail="会话不存在")
    await db.delete(convo)
    return {"ok": True}


def _to_out(c: Conversation) -> dict:
    return {
        "id": str(c.id),
        "agent_id": c.agent_id,
        "title": c.title,
        "messages": c.messages or [],
        "summary": c.summary,
        "revision": c.revision,
        "created_at": c.created_at.isoformat() if c.created_at else "",
        "updated_at": c.updated_at.isoformat() if c.updated_at else "",
    }
