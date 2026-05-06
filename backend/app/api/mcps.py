"""MCP admin API — probe servers, refresh tool catalog, ad-hoc call.

Surface:
  POST  /mcps/probe                     — anonymous probe of an arbitrary URL (admin)
  POST  /mcps/{mcp_id}/probe            — probe a stored agent_mcps row (admin)
  POST  /mcps/{mcp_id}/refresh-tools    — list_tools and persist into the row.tools cache (admin)
  POST  /mcps/{mcp_id}/call             — ad-hoc tool call (admin) — useful for debugging
  GET   /mcps                           — list all stored MCP records (any logged-in user)

The actual binding (which agent uses which MCP) lives in `agent_mcps`
already and is managed by /agents/{id}/mcps in the existing CRUD layer.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.agent import AgentMcp
from ..models.user import User
from ..security import get_current_user, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mcps", tags=["mcps"])


class ProbeRequest(BaseModel):
    server_url: str = Field(..., description="MCP server endpoint URL")
    config: Optional[Dict[str, Any]] = Field(default=None, description="Auth headers, timeout, etc.")
    timeout: float = Field(default=10.0, ge=1.0, le=60.0)


class CallRequest(BaseModel):
    name: str = Field(..., description="Raw MCP tool name (NOT the mcp__server__tool prefix)")
    arguments: Dict[str, Any] = Field(default_factory=dict)


class McpCreate(BaseModel):
    agent_id: str = Field(..., description="seed_id of the agent to bind this MCP to")
    name: str = Field(..., min_length=1, max_length=200)
    server_url: str = Field(..., min_length=1)
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    auto_refresh: bool = Field(
        default=True,
        description="If true, immediately probe the server and cache its tool catalog",
    )


class McpUpdate(BaseModel):
    name: Optional[str] = None
    server_url: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


def _mcp_dict(r: AgentMcp) -> Dict[str, Any]:
    return {
        "id": str(r.id),
        "agent_id": r.agent_id,
        "name": r.name,
        "server_url": r.server_url,
        "tools": r.tools or [],
        "tool_count": len(r.tools or []),
        "config": r.config or {},
        "enabled": r.enabled,
    }


@router.get("")
async def list_mcps(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    agent_id: Optional[str] = None,
):
    stmt = select(AgentMcp)
    if agent_id:
        stmt = stmt.where(AgentMcp.agent_id == agent_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [_mcp_dict(r) for r in rows]


@router.get("/{mcp_id}")
async def get_mcp(
    mcp_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rec = await db.get(AgentMcp, mcp_id)
    if not rec:
        raise HTTPException(status_code=404, detail="MCP record not found")
    return _mcp_dict(rec)


@router.post("", status_code=201)
async def create_mcp(
    body: McpCreate,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Bind an MCP server to an agent. If `auto_refresh=true`, immediately
    probes the server and stores the tool catalog (so the very next agent
    run picks them up without an extra round-trip)."""
    from ..models.agent import AgentDefinition
    from ..services.mcp_client import list_tools as mcp_list_tools

    if not await db.get(AgentDefinition, body.agent_id):
        raise HTTPException(status_code=404, detail=f"agent {body.agent_id} not found")

    tools: list = []
    if body.auto_refresh:
        try:
            tools = await mcp_list_tools(body.server_url, body.config)
        except Exception as e:
            logger.warning(f"[mcps.create] auto-refresh failed: {e}")

    rec = AgentMcp(
        agent_id=body.agent_id,
        name=body.name,
        server_url=body.server_url,
        config=body.config,
        tools=tools,
        enabled=body.enabled,
    )
    db.add(rec)
    await db.flush()
    return _mcp_dict(rec)


@router.patch("/{mcp_id}")
async def update_mcp(
    mcp_id: str,
    body: McpUpdate,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rec = await db.get(AgentMcp, mcp_id)
    if not rec:
        raise HTTPException(status_code=404, detail="MCP record not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(rec, field, value)
    await db.flush()
    return _mcp_dict(rec)


@router.delete("/{mcp_id}")
async def delete_mcp(
    mcp_id: str,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rec = await db.get(AgentMcp, mcp_id)
    if not rec:
        raise HTTPException(status_code=404, detail="MCP record not found")
    await db.delete(rec)
    return {"ok": True}


@router.post("/probe")
async def probe_anonymous(
    body: ProbeRequest,
    admin: Annotated[User, Depends(require_admin)],
):
    """Probe any MCP URL without storing it — used by the 'Test' button in UI."""
    from ..services.mcp_client import probe
    return await probe(body.server_url, body.config, timeout=body.timeout)


@router.post("/{mcp_id}/probe")
async def probe_stored(
    mcp_id: str,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from ..services.mcp_client import probe
    rec = await db.get(AgentMcp, mcp_id)
    if not rec:
        raise HTTPException(status_code=404, detail="MCP record not found")
    return await probe(rec.server_url, rec.config or {})


@router.post("/{mcp_id}/refresh-tools")
async def refresh_tools(
    mcp_id: str,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Live `list_tools()` and persist the catalog into `agent_mcps.tools`."""
    from ..services.mcp_client import list_tools as mcp_list_tools
    rec = await db.get(AgentMcp, mcp_id)
    if not rec:
        raise HTTPException(status_code=404, detail="MCP record not found")
    tools = await mcp_list_tools(rec.server_url, rec.config or {})
    rec.tools = tools
    await db.flush()
    await db.commit()
    return {
        "ok": True,
        "mcp_id": str(rec.id),
        "tool_count": len(tools),
        "tools": [t.get("name") for t in tools if isinstance(t, dict)],
    }


@router.post("/{mcp_id}/call")
async def call_tool(
    mcp_id: str,
    body: CallRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from ..services.mcp_client import call_tool as mcp_call
    rec = await db.get(AgentMcp, mcp_id)
    if not rec:
        raise HTTPException(status_code=404, detail="MCP record not found")
    result = await mcp_call(rec.server_url, body.name, body.arguments, rec.config or {})
    return result
