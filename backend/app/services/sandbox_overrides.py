"""Cached resolver + admin helpers for the DB-backed sandbox overrides.

The table is small (typically << 1k rows even for big deployments) and
read on every tool call, so we cache the *entire* override map in
memory and bust on any write. Cache lookups are O(1).

Multi-process consistency
-------------------------
When the app is deployed with multiple workers (gunicorn ``-w N``),
each worker holds its own ``_CACHE``. To keep them in sync, every
``upsert_rule`` / ``delete_rule`` publishes a small event on the
``sandbox:rule-changed`` Redis channel. A background listener
(``start_invalidation_listener``, started from ``app.main.lifespan``)
patches the local cache when it sees a change made by another worker.

The publish is best-effort — if Redis is down we fall back to the
in-memory pubsub (``redis_client._MemoryFallback``) which only delivers
within the same process. That degrades multi-worker setups to
"changes are visible after a restart", same as before this feature
was added, but doesn't break single-process dev mode.

Public API
----------
* ``override_decision(role, tool)`` — synchronous lookup; returns
  ``True`` (force-allow), ``False`` (force-deny), or ``None`` (no
  override; caller falls back to the in-code baseline).
* ``preload_overrides(db)`` — eagerly populate the cache (called at
  app startup so the first tool call is fast).
* ``start_invalidation_listener()`` — start the Redis pubsub listener
  task; idempotent.
* ``upsert_rule(...)`` / ``delete_rule(...)`` / ``list_rules(...)``
  — admin CRUD used by ``app/api/sandbox.py``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
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


# ─────────────────────────────────────────────────────────────────────
# Cross-process invalidation via Redis pubsub.
# ─────────────────────────────────────────────────────────────────────
#
# Channel format: one event per write, fan-out to every subscribed
# worker. Each worker stamps its own ``origin`` so it can ignore its
# own echoes (otherwise we'd do a redundant cache patch right after
# every local write).
#
# Wire format (JSON):
#   {"op": "upsert", "role": "ceo", "tool": "bash", "allowed": true,
#    "origin": "<process-uuid>"}
#   {"op": "delete", "role": "ceo", "tool": "bash",
#    "origin": "<process-uuid>"}
#   {"op": "reload", "origin": "<process-uuid>"}   ← full resync trigger

_INVALIDATION_CHANNEL = "sandbox:rule-changed"
_PROCESS_ID = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
_listener_task: Optional[asyncio.Task] = None
_listener_lock = asyncio.Lock()


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
    cleanly without poisoning the in-memory state. After a successful
    write, broadcast a Redis pubsub event so peer workers can patch
    their caches.
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
    await _publish_change({
        "op": "upsert", "role": role, "tool": tool, "allowed": bool(allowed),
    })
    return _row_to_dict(row)


async def delete_rule(
    db: AsyncSession, *, role: str, tool: str,
) -> bool:
    """Drop one rule (revert to code default). Returns True if a row was
    removed, False if no such rule existed. Successful deletes broadcast
    an invalidation event."""
    res = await db.execute(
        delete(SandboxRule).where(
            SandboxRule.role == role, SandboxRule.tool == tool,
        )
    )
    _CACHE.pop((role, tool), None)
    removed = (res.rowcount or 0) > 0
    if removed:
        await _publish_change({"op": "delete", "role": role, "tool": tool})
    return removed


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


# ─────────────────────────────────────────────────────────────────────
# Cross-process invalidation: publisher + listener
# ─────────────────────────────────────────────────────────────────────


async def _publish_change(payload: Dict[str, Any]) -> None:
    """Best-effort broadcast. Failures (Redis down, etc.) are logged
    once and swallowed — the local cache update has already happened
    so this worker is correct, only peers might lag."""
    payload = dict(payload)
    payload["origin"] = _PROCESS_ID
    try:
        from ..redis_client import get_redis
        r = get_redis()
        await r.publish(_INVALIDATION_CHANNEL, json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        logger.debug("[sandbox] publish failed (single-worker mode?): %s", exc)


def _apply_remote_change(payload: Dict[str, Any]) -> None:
    """Patch the local cache from a peer worker's broadcast. Called
    from the listener loop. Defensive — if the message is malformed
    we just log and skip; no exception propagates."""
    op = payload.get("op")
    role = payload.get("role")
    tool = payload.get("tool")
    if op == "upsert" and role and tool:
        _CACHE[(role, tool)] = bool(payload.get("allowed", False))
    elif op == "delete" and role and tool:
        _CACHE.pop((role, tool), None)
    elif op == "reload":
        # Caller-requested full resync; the next ``preload_overrides``
        # call will rebuild. Until then we mark the cache as stale by
        # clearing it — safer to defer to baselines than to serve
        # ghost overrides.
        _CACHE.clear()
        global _CACHE_LOADED
        _CACHE_LOADED = False
    else:
        logger.warning("[sandbox] ignored malformed invalidation: %r", payload)


async def _invalidation_listener_loop() -> None:
    """Long-running coroutine that consumes ``sandbox:rule-changed``
    broadcasts. One per process. Reconnects on transient errors.

    We swallow our own echo by checking ``payload["origin"] ==
    _PROCESS_ID`` — otherwise every local write would trigger a
    redundant local cache write.
    """
    from ..redis_client import get_redis
    r = get_redis()
    backoff = 1.0
    while True:
        ps = None
        try:
            ps = r.pubsub()
            await ps.subscribe(_INVALIDATION_CHANNEL)
            logger.info(
                "[sandbox] invalidation listener subscribed (process=%s)",
                _PROCESS_ID,
            )
            backoff = 1.0
            async for msg in ps.listen():
                if msg.get("type") != "message":
                    continue
                raw = msg.get("data")
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                if not isinstance(raw, str):
                    continue
                try:
                    payload = json.loads(raw)
                except Exception:
                    logger.warning("[sandbox] non-JSON invalidation: %r", raw)
                    continue
                if payload.get("origin") == _PROCESS_ID:
                    continue  # ignore my own echo
                _apply_remote_change(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[sandbox] listener loop error: %s; reconnect in %.1fs", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
        finally:
            if ps is not None:
                # redis-py 5+ deprecates ``close()`` in favour of
                # ``aclose()``; fall through to the legacy name for
                # the in-memory pubsub stub which doesn't have aclose.
                try:
                    closer = getattr(ps, "aclose", None) or ps.close
                    await closer()
                except Exception:
                    pass


async def start_invalidation_listener() -> None:
    """Start the background listener exactly once per process. Idempotent
    — calling again is a no-op. Call from ``app.main.lifespan``."""
    global _listener_task
    async with _listener_lock:
        if _listener_task is not None and not _listener_task.done():
            return
        _listener_task = asyncio.create_task(
            _invalidation_listener_loop(),
            name="sandbox-invalidation-listener",
        )
        logger.info("[sandbox] invalidation listener task scheduled")


async def stop_invalidation_listener() -> None:
    """Cancel the listener task. Used by the test suite to keep things
    tidy and by graceful shutdown paths."""
    global _listener_task
    async with _listener_lock:
        if _listener_task is None or _listener_task.done():
            _listener_task = None
            return
        _listener_task.cancel()
        try:
            await _listener_task
        except (asyncio.CancelledError, Exception):
            pass
        _listener_task = None
