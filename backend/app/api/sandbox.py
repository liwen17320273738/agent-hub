"""Skill-sandbox introspection + audit + admin API.

Routes
------
GET    /api/sandbox/policy                     – full role → allowed-tools map
GET    /api/sandbox/policy/{role}              – inspector for one role
GET    /api/sandbox/denials?limit=N&task_id=…  – recent SANDBOX_DENIED audit rows

Admin (DB-backed override of the in-code baseline)::

    GET    /api/sandbox/rules
    PUT    /api/sandbox/rules/{role}/{tool}    body: {allowed, note?}
    DELETE /api/sandbox/rules/{role}/{tool}    – revert to code default

Each rule overrides the static ``ROLE_TOOL_WHITELIST`` for one
(role, tool) pair, hot-reloaded into the in-memory cache so the
next tool call uses the new policy. An empty rule table behaves
identically to the in-code baseline.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.observability import AuditLog
from ..security import get_current_user
from ..services.tools.registry import (
    COMMON_TOOLS,
    ROLE_TOOL_WHITELIST,
    TOOL_REGISTRY,
    role_tool_summary,
)
from ..services.sandbox_overrides import (
    delete_rule,
    list_rules,
    upsert_rule,
)

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])


@router.get("/policy")
async def get_policy(_user=Depends(get_current_user)):
    """Return the full whitelist matrix and the registered tool set.

    Frontend uses this to render a role × tool grid showing allow/deny.
    """
    return {
        "common_tools": sorted(COMMON_TOOLS & set(TOOL_REGISTRY.keys())),
        "all_tools": sorted(TOOL_REGISTRY.keys()),
        "roles": {
            role: role_tool_summary(role)
            for role in ROLE_TOOL_WHITELIST.keys()
        },
    }


@router.get("/policy/{role}")
async def get_policy_for_role(role: str, _user=Depends(get_current_user)):
    if role not in ROLE_TOOL_WHITELIST:
        raise HTTPException(
            status_code=404,
            detail=f"role '{role}' has no sandbox whitelist (treated as unrestricted)",
        )
    return role_tool_summary(role)


@router.get("/denials")
async def list_denials(
    task_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Most recent skill-sandbox denials. Sourced from AuditLog where
    `action LIKE 'tool.denied:%'` and `outcome = 'denied'`."""
    stmt = select(AuditLog).where(
        AuditLog.action.like("tool.denied:%"),
        AuditLog.outcome == "denied",
    )
    if task_id:
        stmt = stmt.where(AuditLog.task_id == task_id)
    stmt = stmt.order_by(desc(AuditLog.created_at)).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    return {
        "denials": [
            {
                "id": str(r.id),
                "task_id": r.task_id,
                "stage_id": r.stage_id,
                "tool": r.action.split(":", 1)[1] if ":" in r.action else r.action,
                "actor": r.actor,
                "details": r.details,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Admin: DB-backed sandbox rule overrides
# ─────────────────────────────────────────────────────────────────────────────

class _RuleBody(BaseModel):
    allowed: bool
    note: Optional[str] = None


def _require_admin(user) -> str:
    """Mutating sandbox endpoints are admin-only — the matrix decides
    what every other role can do, so we don't want non-admin agents
    re-writing it. Returns a string identifier for audit logs.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if getattr(user, "role", "") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Sandbox rule edits require an admin user",
        )
    uid = str(getattr(user, "id", "") or "")
    return f"user:{uid}" if uid else "user:admin"


@router.get("/rules")
async def get_rules(
    role: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """List every persisted sandbox override (optionally filtered by role).

    Read-only — every authenticated user can see the rules. Useful for
    the matrix UI to show "this cell is overridden by ops" badges.
    """
    return {"rules": await list_rules(db, role=role)}


@router.put("/rules/{role}/{tool}")
async def set_rule(
    role: str,
    tool: str,
    body: _RuleBody,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Upsert one (role, tool) override. Admin-only.

    Validation: ``role`` must exist in the in-code baseline (we don't
    let ops invent new roles via the API; that would silently bypass
    seed-time sanity checks). ``tool`` must be a known static tool.
    For dynamic MCP tools, use the future MCP metadata API.
    """
    actor = _require_admin(user)
    if role not in ROLE_TOOL_WHITELIST:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown role '{role}'; must be one of "
                f"{sorted(ROLE_TOOL_WHITELIST.keys())}"
            ),
        )
    if tool not in TOOL_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown tool '{tool}'; not registered in TOOL_REGISTRY. "
                f"Dynamic MCP tools are handled by the MCP sandbox layer."
            ),
        )
    rule = await upsert_rule(
        db, role=role, tool=tool,
        allowed=body.allowed, note=body.note,
        updated_by=actor,
    )
    await db.commit()
    return {"rule": rule, "effective": role_tool_summary(role)}


@router.delete("/rules/{role}/{tool}")
async def remove_rule(
    role: str,
    tool: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete one override (revert to in-code default). Admin-only."""
    _require_admin(user)
    removed = await delete_rule(db, role=role, tool=tool)
    await db.commit()
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"no override exists for role={role} tool={tool}",
        )
    return {"ok": True, "effective": role_tool_summary(role)}
