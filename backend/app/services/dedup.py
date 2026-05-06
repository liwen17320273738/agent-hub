"""Cross-process dedup primitives backed by Redis ``SET NX EX``.

Two real callers as of today:

* ``escalation.maybe_escalate`` — fires once per ``(task_id, reject_count)``
  crossing across every gunicorn worker. Without this, ``-w 4`` would
  send 4 IM pings + 4 escalation comments per crossing.
* Inbound webhook handlers — GitHub auto-retries deliveries on network
  blips; without delivery-ID dedup the same reviewer comment can be
  iterated multiple times, burning tokens.

The Redis fallback (``_MemoryFallback``) is a no-cross-process mock,
so when there's no real Redis the dedup is per-process — same trade-off
as the rest of our state. Tests rely on this fallback shape.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def claim_dedup_token(
    key: str,
    *,
    ttl_seconds: int = 86400,
    value: str = "1",
) -> bool:
    """Atomically claim a one-shot token. Returns ``True`` if newly
    acquired (the caller should proceed), ``False`` if the token
    already existed (the caller should skip).

    Backed by ``SET key value NX EX ttl`` — atomic on real Redis,
    handled by ``_MemoryFallback.set`` for dev / tests.

    On any Redis error we **fail open** (return True). Dropping a
    legitimate event (false negative) is worse than the noise of one
    extra escalation comment, especially during a Redis outage when
    operators most need the visibility.
    """
    try:
        from ..redis_client import get_redis
        r = get_redis()
        result = await r.set(key, value, nx=True, ex=ttl_seconds)
        return bool(result)
    except Exception as exc:
        logger.warning("[dedup] claim failed for %s; failing open: %s", key, exc)
        return True


async def release_dedup_token(key: str) -> None:
    """Best-effort release. Almost always you want the TTL to expire
    naturally; only call this if you need to retry a one-shot
    operation."""
    try:
        from ..redis_client import get_redis
        r = get_redis()
        await r.delete(key)
    except Exception as exc:
        logger.debug("[dedup] release failed for %s: %s", key, exc)
