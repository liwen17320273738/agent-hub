"""Agent CRUD: dynamic agent definitions with skills, rules, hooks, plugins, MCP.

Phase 1: Agents are the single source of truth. The API enriches each agent
with its bound tools (from AGENT_TOOLS) so the frontend can render
full expert profiles.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from ..database import get_db
from ..models.agent import AgentDefinition, AgentSkill, AgentRule, AgentHook, AgentPlugin, AgentMcp
from ..models.user import User
from ..schemas.agent import AgentOut, AgentCreate, AgentUpdate, ToolBindingOut
from ..security import get_current_user, get_pipeline_auth, require_admin

logger = logging.getLogger(__name__)
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


# ─────────────────────────────────────────────────────────────────
# Prompt Optimizer — close the data loop on a single agent
# ─────────────────────────────────────────────────────────────────


class PromptOptimizeBody(BaseModel):
    run_id: Optional[str] = Field(default=None, description="Eval run to analyze; defaults to most recent for the role")
    score_threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class PromptApplyBody(BaseModel):
    new_prompt: str = Field(..., min_length=10, max_length=5000)
    note: str = ""


@router.post("/{agent_id}/optimize-prompt")
async def optimize_prompt(
    agent_id: str,
    body: PromptOptimizeBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Run an LLM critic over recent eval failures and propose a revised prompt (no apply)."""
    from ..services.prompt_optimizer import propose_revision

    result = await propose_revision(
        db, agent_id=agent_id, run_id=body.run_id, score_threshold=body.score_threshold
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "optimize failed")
    return result


@router.post("/{agent_id}/apply-prompt")
async def apply_prompt_revision(
    agent_id: str,
    body: PromptApplyBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Apply a previously-proposed (or hand-edited) prompt; previous prompt is kept for rollback."""
    from ..services.prompt_optimizer import apply_revision

    result = await apply_revision(db, agent_id=agent_id, new_prompt=body.new_prompt, note=body.note)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "apply failed")
    return result


@router.post("/{agent_id}/rollback-prompt")
async def rollback_prompt_revision(
    agent_id: str,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    steps: int = 1,
):
    """Restore the previous system prompt from history."""
    from ..services.prompt_optimizer import rollback_revision

    result = await rollback_revision(db, agent_id=agent_id, steps=steps)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "rollback failed")
    return result


# ─────────────────────────────────────────────────────────────────
# Agent Runtime — directly invoke any agent (single-shot or streaming)
# Lets web/CLI users call ANY agent without going through pipeline.
# ─────────────────────────────────────────────────────────────────

class AgentRunRequest(BaseModel):
    task: str = Field(..., description="The task / prompt to send to the agent")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Optional key-value context")
    max_steps: Optional[int] = Field(default=None, ge=1, le=20)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    tools_override: Optional[List[str]] = Field(default=None, description="Restrict to subset of bound tools")
    system_prompt_override: Optional[str] = Field(default=None, description="Replace the agent's system prompt entirely")
    model_override: Optional[str] = Field(default=None, description="Force a specific model id")


class AgentRunByRoleRequest(AgentRunRequest):
    role: str = Field(..., description="Role key: ceo, cto, developer, qa, designer, security, …")


class AgentRunResponse(BaseModel):
    ok: bool
    agent_id: str
    content: str = ""
    steps: int = 0
    observations: List[str] = []
    model: str = ""
    verification: Optional[str] = None
    error: Optional[str] = None
    elapsed_ms: int = 0
    mcp_tools_loaded: List[str] = []


def _resolve_seed_id(role_or_id: str) -> Optional[str]:
    """Accept either a `wayne-*` seed id or a role alias from ROLE_TO_SEED_ID."""
    from ..agents.seed import AGENT_TOOLS
    from ..services.agent_delegate import ROLE_TO_SEED_ID
    if role_or_id in AGENT_TOOLS:
        return role_or_id
    return ROLE_TO_SEED_ID.get(role_or_id.lower())


def _agent_system_prompt(agent: Optional[AgentDefinition], seed_id: str) -> str:
    """Pick the best system prompt: DB definition → built-in fallback."""
    if agent and agent.system_prompt:
        return agent.system_prompt
    from ..services.agent_delegate import _SHORT_PROMPTS
    return _SHORT_PROMPTS.get(seed_id, "你是一位资深领域专家。请严谨、专业地完成任务。")


async def _load_mcp_tools_for_agent(
    db: AsyncSession, seed_id: str
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """Load any MCP tools bound to this agent, returning (defs, handlers)."""
    from ..models.agent import AgentMcp
    from ..services.mcp_client import build_tool_handlers

    rows = (await db.execute(
        select(AgentMcp).where(AgentMcp.agent_id == seed_id, AgentMcp.enabled.is_(True))
    )).scalars().all()
    if not rows:
        return {}, {}
    records = [
        {
            "id": str(r.id),
            "name": r.name,
            "server_url": r.server_url,
            "tools": r.tools or [],
            "config": r.config or {},
            "enabled": r.enabled,
        }
        for r in rows
    ]
    try:
        return await build_tool_handlers(records, fetch_if_empty=True)
    except Exception as e:
        logger.warning(f"[agents/run] MCP tool loading failed for {seed_id}: {e}")
        return {}, {}


async def _run_agent_inner(
    db: AsyncSession,
    *,
    seed_id: str,
    body: AgentRunRequest,
) -> Dict[str, Any]:
    """Shared core for single-shot and streaming variants."""
    from ..agents.seed import AGENT_TOOLS
    from ..services.agent_runtime import AgentRuntime

    agent_def = await db.get(AgentDefinition, seed_id)

    bound_tools = list(AGENT_TOOLS.get(seed_id, []))
    if body.tools_override:
        bound_tools = [t for t in body.tools_override if t in bound_tools]
        if not bound_tools and body.tools_override:
            return {"ok": False, "error": "tools_override does not match any bound tool"}

    system_prompt = body.system_prompt_override or _agent_system_prompt(agent_def, seed_id)
    max_steps = body.max_steps or 5
    temperature = body.temperature if body.temperature is not None else (
        agent_def.temperature if agent_def and agent_def.temperature is not None else 0.7
    )

    model_pref: Dict[str, str] = {}
    if body.model_override:
        model_pref["execution"] = body.model_override
    elif agent_def and agent_def.preferred_model:
        model_pref["execution"] = agent_def.preferred_model

    mcp_defs, mcp_handlers = await _load_mcp_tools_for_agent(db, seed_id)

    runtime = AgentRuntime(
        agent_id=seed_id,
        system_prompt=system_prompt,
        tools=bound_tools,
        model_preference=model_pref or None,
        max_steps=max_steps,
        temperature=temperature,
        dynamic_tools=mcp_defs or None,
        dynamic_handlers=mcp_handlers or None,
    )

    started = time.monotonic()
    try:
        result = await runtime.execute(db, task=body.task, context=body.context)
    except Exception as e:
        logger.exception(f"[agents/run] runtime crashed for {seed_id}: {e}")
        return {"ok": False, "error": str(e)}
    elapsed_ms = int((time.monotonic() - started) * 1000)
    result["elapsed_ms"] = elapsed_ms
    result["agent_id"] = seed_id
    if mcp_defs:
        result["mcp_tools_loaded"] = list(mcp_defs.keys())
    return result


@router.post("/{agent_id}/run", response_model=AgentRunResponse)
async def run_agent(
    agent_id: str,
    body: AgentRunRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Run a single agent end-to-end (synchronous, returns final answer).

    `agent_id` accepts either a seed id (e.g. `wayne-developer`) or a role
    alias (e.g. `developer`, `security`, `architect`).
    """
    seed_id = _resolve_seed_id(agent_id)
    if not seed_id:
        raise HTTPException(status_code=404, detail=f"unknown agent or role: {agent_id}")

    if not body.task or not body.task.strip():
        raise HTTPException(status_code=422, detail="task must be non-empty")

    result = await _run_agent_inner(db, seed_id=seed_id, body=body)
    await db.commit()
    return AgentRunResponse(
        ok=bool(result.get("ok")),
        agent_id=result.get("agent_id", seed_id),
        content=result.get("content", "") or "",
        steps=int(result.get("steps", 0) or 0),
        observations=list(result.get("observations") or [])[:50],
        model=str(result.get("model", "") or ""),
        verification=result.get("verification"),
        error=result.get("error"),
        elapsed_ms=int(result.get("elapsed_ms", 0) or 0),
        mcp_tools_loaded=list(result.get("mcp_tools_loaded") or []),
    )


@router.post("/run-by-role", response_model=AgentRunResponse)
async def run_agent_by_role(
    body: AgentRunByRoleRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Convenience: pick agent by role key (ceo/cto/developer/qa/security/…)."""
    seed_id = _resolve_seed_id(body.role)
    if not seed_id:
        from ..services.agent_delegate import ROLE_TO_SEED_ID
        valid = ", ".join(sorted(set(ROLE_TO_SEED_ID.keys())))
        raise HTTPException(status_code=404, detail=f"unknown role '{body.role}'. valid: {valid}")
    if not body.task or not body.task.strip():
        raise HTTPException(status_code=422, detail="task must be non-empty")
    result = await _run_agent_inner(db, seed_id=seed_id, body=body)
    await db.commit()
    return AgentRunResponse(
        ok=bool(result.get("ok")),
        agent_id=result.get("agent_id", seed_id),
        content=result.get("content", "") or "",
        steps=int(result.get("steps", 0) or 0),
        observations=list(result.get("observations") or [])[:50],
        model=str(result.get("model", "") or ""),
        verification=result.get("verification"),
        error=result.get("error"),
        elapsed_ms=int(result.get("elapsed_ms", 0) or 0),
        mcp_tools_loaded=list(result.get("mcp_tools_loaded") or []),
    )


@router.get("/runtime/roles")
async def list_runtime_roles(
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    """List role aliases accepted by /agents/run-by-role and delegate_to_agent."""
    from ..services.agent_delegate import ROLE_TO_SEED_ID, _SHORT_PROMPTS
    rows = []
    seen_seeds = set()
    for role, seed in sorted(ROLE_TO_SEED_ID.items()):
        rows.append({
            "role": role,
            "seed_id": seed,
            "short_prompt": _SHORT_PROMPTS.get(seed, ""),
            "is_primary": seed not in seen_seeds,
        })
        seen_seeds.add(seed)
    return {"roles": rows, "count": len(rows)}


@router.get("/runtime/tools")
async def list_runtime_tools(
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    """List every tool registered in TOOL_REGISTRY (for UI dropdown / debug)."""
    from ..services.tools import TOOL_REGISTRY
    tools = []
    for name, defn in sorted(TOOL_REGISTRY.items()):
        tools.append({
            "name": name,
            "description": defn.get("description", ""),
            "permissions": defn.get("permissions", []),
            "parameters": defn.get("parameters", {}),
        })
    return {"tools": tools, "count": len(tools)}


# ─────────────────────────────────────────────────────────────────
# Streaming variant — returns SSE events: step, tool_call, observation, final
# ─────────────────────────────────────────────────────────────────

@router.post("/{agent_id}/run/stream")
async def run_agent_stream(
    agent_id: str,
    body: AgentRunRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """SSE-stream the agent's execution.

    Events emitted:
      - {"event": "started",   "agent_id": "..."}
      - {"event": "progress",  "phase": "thinking"|"tool"|"observation", ...}
      - {"event": "completed", "ok": bool, "content": "...", "steps": N, ...}
      - {"event": "error",     "error": "..."}
    """
    seed_id = _resolve_seed_id(agent_id)
    if not seed_id:
        raise HTTPException(status_code=404, detail=f"unknown agent or role: {agent_id}")
    if not body.task or not body.task.strip():
        raise HTTPException(status_code=422, detail="task must be non-empty")

    queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()
    progress_events = (
        "agent:execute-start", "agent:tool-call",
        "agent:execute-complete", "stage:processing",
    )

    async def _redis_listener(stop_evt: asyncio.Event) -> None:
        """Tail the global pipeline SSE channel, forward events for our agent only."""
        try:
            from ..redis_client import redis as redis_client
            from ..services.sse import CHANNEL
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(CHANNEL)
        except Exception as e:
            logger.debug(f"[agents/run/stream] pubsub unavailable, progress events disabled: {e}")
            return
        try:
            while not stop_evt.is_set():
                try:
                    msg = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
                if not msg or msg.get("type") != "message":
                    continue
                raw = msg.get("data")
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(raw)
                except Exception:
                    continue
                evt = parsed.get("event")
                data = parsed.get("data") or {}
                if evt not in progress_events:
                    continue
                if data.get("agentId") != seed_id:
                    continue
                await queue.put({"event": "progress", "phase": evt, "data": data})
        finally:
            try:
                await pubsub.unsubscribe(CHANNEL)
                await pubsub.close()
            except Exception:
                pass

    async def _runner() -> None:
        stop_evt = asyncio.Event()
        listener = asyncio.create_task(_redis_listener(stop_evt))
        try:
            await queue.put({"event": "started", "agent_id": seed_id, "task": body.task[:200]})
            result = await _run_agent_inner(db, seed_id=seed_id, body=body)
            await db.commit()
            await asyncio.sleep(0.2)
            await queue.put({
                "event": "completed",
                "ok": bool(result.get("ok")),
                "agent_id": seed_id,
                "content": result.get("content", "") or "",
                "steps": int(result.get("steps", 0) or 0),
                "model": result.get("model", ""),
                "verification": result.get("verification"),
                "elapsed_ms": int(result.get("elapsed_ms", 0) or 0),
                "error": result.get("error"),
                "mcp_tools_loaded": list(result.get("mcp_tools_loaded") or []),
            })
        except Exception as e:
            logger.exception(f"[agents/run/stream] runner crashed: {e}")
            await queue.put({"event": "error", "error": str(e)})
        finally:
            stop_evt.set()
            try:
                await asyncio.wait_for(listener, timeout=2.0)
            except (asyncio.TimeoutError, Exception):
                listener.cancel()
            await queue.put(None)

    asyncio.create_task(_runner())

    async def _generator():
        while True:
            item = await queue.get()
            if item is None:
                break
            yield {"data": json.dumps(item, ensure_ascii=False, default=str)}

    return EventSourceResponse(_generator())
