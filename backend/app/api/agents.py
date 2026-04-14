"""Agent CRUD: dynamic agent definitions with skills, rules, hooks, plugins, MCP."""
from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models.agent import AgentDefinition, AgentSkill, AgentRule, AgentHook, AgentPlugin, AgentMcp
from ..models.user import User
from ..schemas.agent import AgentOut, AgentCreate, AgentUpdate
from ..security import get_current_user, require_admin

router = APIRouter(prefix="/agents", tags=["agents"])


def _load_options():
    return [
        selectinload(AgentDefinition.skills),
        selectinload(AgentDefinition.rules),
        selectinload(AgentDefinition.hooks),
        selectinload(AgentDefinition.plugins),
        selectinload(AgentDefinition.mcps),
    ]


@router.get("/", response_model=List[AgentOut])
async def list_agents(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category: Optional[str] = None,
    active_only: bool = True,
):
    stmt = select(AgentDefinition).options(*_load_options()).order_by(AgentDefinition.sort_order)
    if category:
        stmt = stmt.where(AgentDefinition.category == category)
    if active_only:
        stmt = stmt.where(AgentDefinition.is_active.is_(True))
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(AgentDefinition).options(*_load_options()).where(AgentDefinition.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="智能体不存在")
    return agent


@router.post("/", response_model=AgentOut, status_code=201)
async def create_agent(
    body: AgentCreate,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    existing = await db.get(AgentDefinition, body.id)
    if existing:
        raise HTTPException(status_code=409, detail="智能体 ID 已存在")

    agent = AgentDefinition(**body.model_dump())
    db.add(agent)
    await db.flush()
    return agent


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: str,
    body: AgentUpdate,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    agent = await db.get(AgentDefinition, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="智能体不存在")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    await db.flush()

    result = await db.execute(
        select(AgentDefinition).options(*_load_options()).where(AgentDefinition.id == agent_id)
    )
    return result.scalar_one()


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    agent = await db.get(AgentDefinition, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="智能体不存在")
    await db.delete(agent)
    return {"ok": True}
