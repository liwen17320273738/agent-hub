"""Agent CRUD: dynamic agent definitions with skills, rules, hooks, plugins, MCP.

Phase 1: Agents are the single source of truth. The API enriches each agent
with its bound tools (from AGENT_TOOLS) so the frontend can render
full expert profiles.
"""
from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models.agent import AgentDefinition, AgentSkill, AgentRule, AgentHook, AgentPlugin, AgentMcp
from ..models.user import User
from ..schemas.agent import AgentOut, AgentCreate, AgentUpdate, ToolBindingOut
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


def _enrich_with_tools(agent: AgentDefinition) -> dict:
    """Convert ORM agent to dict and inject tool bindings from AGENT_TOOLS."""
    from ..agents.seed import AGENT_TOOLS
    from ..services.tools import TOOL_REGISTRY

    data = {
        "id": agent.id,
        "name": agent.name,
        "title": agent.title,
        "icon": agent.icon,
        "color": agent.color,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "quick_prompts": agent.quick_prompts or [],
        "category": agent.category,
        "pipeline_role": agent.pipeline_role,
        "capabilities": agent.capabilities or {},
        "preferred_model": agent.preferred_model,
        "max_tokens": agent.max_tokens,
        "temperature": agent.temperature,
        "is_active": agent.is_active,
        "skills": agent.skills or [],
        "rules": agent.rules or [],
        "hooks": agent.hooks or [],
        "plugins": agent.plugins or [],
        "mcps": agent.mcps or [],
    }

    tool_names = AGENT_TOOLS.get(agent.id, [])
    tools = []
    for t_name in tool_names:
        t_def = TOOL_REGISTRY.get(t_name)
        if t_def:
            tools.append(ToolBindingOut(
                name=t_def["name"],
                description=t_def["description"],
                permissions=t_def.get("permissions", []),
            ))
    data["tools"] = tools
    return data


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
    agents = result.scalars().all()
    return [_enrich_with_tools(a) for a in agents]


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
    return _enrich_with_tools(agent)


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
