"""Cached resolver + admin helpers for the DB-backed sandbox overrides.

The table is small (typically << 1k rows even for big deployments) and
read on every tool call, so we cache the *entire* override map in
memory and bust on any write. Cache lookups are O(1).

Public API
----------
* ``override_decision(role, tool)`` — synchronous lookup; returns
  ``True`` (force-allow), ``False`` (force-deny), or ``None`` (no
  override; caller falls back to the in-code baseline).
* ``preload_overrides(db)`` — eagerly populate the cache (called at
  app startup so the first tool call is fast).
* ``upsert_rule(...)`` / ``delete_rule(...)`` / ``list_rules(...)``
  — admin CRUD used by ``app/api/sandbox.py``.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.sandbox_rule import SandboxRule

logger = logging.getLogger(__name__)


# In-memory cache: {(role, tool): allowed_bool}
# A missing key = no override; defer to in-code whitelist.
_CACHE: Dict[Tuple[str, str], bool] = {}
_CACHE_LOADED = False


def override_decision(role: Optional[str], tool: str) -> Optional[bool]:
    """Return True/False if a DB override applies, or None to defer.

    Synchronous so we don't pay for a DB hit on every tool call. The
    cache is loaded eagerly at startup (``preload_overrides``) and
    refreshed on every write through ``upsert_rule`` / ``delete_rule``.
    If the cache hasn't been loaded yet (e.g. during a test) we
    conservatively return None — i.e. defer to the in-code default.
    """
    if not role:
        return None
    if not _CACHE_LOADED:
        return None
    return _CACHE.get((role, tool))


async def preload_overrides(db: AsyncSession) -> int:
    """Slurp the entire sandbox_rules table into the cache. Call this
    once at app startup; thereafter the cache is kept consistent by
    upsert/delete writers. Returns the number of rules loaded.
    """
    global _CACHE_LOADED
    try:
        res = await db.execute(select(SandboxRule.role, SandboxRule.tool, SandboxRule.allowed))
        rules = res.all()
        _CACHE.clear()
        for role, tool, allowed in rules:
            _CACHE[(role, tool)] = bool(allowed)
        _CACHE_LOADED = True
        logger.info("[sandbox] loaded %d override rules", len(_CACHE))
        return len(_CACHE)
    except Exception as exc:
        # Most likely cause: table doesn't exist yet (alembic not run).
        # Mark cache as "loaded but empty" so we don't keep retrying.
        logger.warning("[sandbox] preload skipped (%s); using in-code defaults", exc)
        _CACHE_LOADED = True
        return 0


async def upsert_rule(
    db: AsyncSession,
    *,
    role: str,
    tool: str,
    allowed: bool,
    note: Optional[str] = None,
    updated_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert-or-update one (role, tool) rule. Updates cache atomically.

    The cache update happens AFTER the DB flush so a failure rolls back
    cleanly without poisoning the in-memory state.
    """
    res = await db.execute(
        select(SandboxRule).where(
            SandboxRule.role == role, SandboxRule.tool == tool,
        )
    )
    row = res.scalar_one_or_none()
    if row:
        row.allowed = allowed
        row.note = note
        row.updated_by = updated_by
        row.updated_at = datetime.utcnow()
    else:
        row = SandboxRule(
            role=role, tool=tool, allowed=allowed,
            note=note, updated_by=updated_by,
        )
        db.add(row)
    await db.flush()
    _CACHE[(role, tool)] = bool(allowed)
    return _row_to_dict(row)


async def delete_rule(
    db: AsyncSession, *, role: str, tool: str,
) -> bool:
    """Drop one rule (revert to code default). Returns True if a row was
    removed, False if no such rule existed."""
    res = await db.execute(
        delete(SandboxRule).where(
            SandboxRule.role == role, SandboxRule.tool == tool,
        )
    )
    _CACHE.pop((role, tool), None)
    return (res.rowcount or 0) > 0


async def list_rules(
    db: AsyncSession, *, role: Optional[str] = None,
) -> List[Dict[str, Any]]:
    stmt = select(SandboxRule)
    if role:
        stmt = stmt.where(SandboxRule.role == role)
    stmt = stmt.order_by(SandboxRule.role, SandboxRule.tool)
    res = await db.execute(stmt)
    return [_row_to_dict(r) for r in res.scalars().all()]


def cached_rules() -> List[Dict[str, Any]]:
    """Return the current in-memory cache as a flat list — used by the
    public ``/api/sandbox/policy`` so the matrix view sees overrides
    even when the caller doesn't supply ``include_overrides=true``."""
    return [
        {"role": role, "tool": tool, "allowed": allowed}
        for (role, tool), allowed in sorted(_CACHE.items())
    ]


def _row_to_dict(r: SandboxRule) -> Dict[str, Any]:
    return {
        "id": str(r.id),
        "role": r.role,
        "tool": r.tool,
        "allowed": bool(r.allowed),
        "note": r.note,
        "updated_by": r.updated_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }
