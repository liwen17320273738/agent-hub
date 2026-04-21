"""Tests for the cross-process dedup primitive (``app.services.dedup``).

Two callers depend on this:

* Webhook delivery-UUID dedup — same GitHub delivery retried under
  network blip ⇒ second hit must be a no-op.
* Escalation throttle — same ``(task_id, reject_count)`` seen across
  workers ⇒ only the first one fires the IM blast.

Because we patch ``redis-py`` to its in-memory fallback for hermetic
tests, these tests double as a sanity check that
``_MemoryFallback.set(..., nx=True, ex=ttl)`` matches real Redis
semantics (returns ``True`` on first set, ``None`` on conflict).
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.services.dedup import claim_dedup_token, release_dedup_token


@pytest_asyncio.fixture(autouse=True)
async def _purge_keys():
    """Drop our test keys from BOTH the in-memory fallback AND a real
    Redis (when reachable). Without the real-Redis purge, leftovers
    from a previous run survive 24h and silently invert this file's
    "first claim succeeds" assertions."""
    from app.redis_client import _memory_store, _memory_expiry, get_redis
    prefix_marks = ("dedup-test:", "webhook:test:", "escalation:test:")

    def _purge_memory():
        for k in list(_memory_store.keys()):
            if isinstance(k, str) and k.startswith(prefix_marks):
                _memory_store.pop(k, None)
                _memory_expiry.pop(k, None)

    async def _purge_real():
        try:
            r = get_redis()
            scan = getattr(r, "scan_iter", None)
            if scan is None:
                return
            for prefix in prefix_marks:
                async for k in r.scan_iter(match=f"{prefix}*"):
                    try:
                        await r.delete(k)
                    except Exception:
                        pass
        except Exception:
            pass

    _purge_memory()
    await _purge_real()
    yield
    _purge_memory()
    await _purge_real()


@pytest.mark.asyncio
async def test_first_claim_succeeds():
    assert await claim_dedup_token("dedup-test:1", ttl_seconds=60) is True


@pytest.mark.asyncio
async def test_second_claim_returns_false():
    key = "dedup-test:repeat"
    assert await claim_dedup_token(key, ttl_seconds=60) is True
    assert await claim_dedup_token(key, ttl_seconds=60) is False
    # And again, just to confirm it's stable.
    assert await claim_dedup_token(key, ttl_seconds=60) is False


@pytest.mark.asyncio
async def test_release_allows_reclaim():
    key = "dedup-test:release"
    assert await claim_dedup_token(key, ttl_seconds=60) is True
    assert await claim_dedup_token(key, ttl_seconds=60) is False
    await release_dedup_token(key)
    assert await claim_dedup_token(key, ttl_seconds=60) is True


@pytest.mark.asyncio
async def test_failure_falls_open(monkeypatch):
    """When Redis raises, the dedup must fail OPEN (return True so the
    caller proceeds). Suppressing a real event during a Redis outage
    would silently lose escalations / feedback — worse than a duplicate.
    """
    import app.services.dedup as dedup_mod

    class _Boom:
        async def set(self, *a, **kw):
            raise RuntimeError("redis down")

    def _broken_get_redis():
        return _Boom()

    monkeypatch.setattr(
        "app.redis_client.get_redis", _broken_get_redis,
    )
    # First call would normally claim; with broken Redis it returns
    # True so the operation proceeds (intentional fail-open).
    assert await dedup_mod.claim_dedup_token("dedup-test:broken") is True
    # Second call also returns True for the same reason — the caller
    # accepts that outage = duplicate, not silent drop.
    assert await dedup_mod.claim_dedup_token("dedup-test:broken") is True
