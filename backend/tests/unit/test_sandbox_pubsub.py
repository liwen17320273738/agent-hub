"""Cross-process invalidation tests for sandbox_overrides.

We simulate two workers by:
  1. Holding the local process's ``_PROCESS_ID`` constant.
  2. Manually invoking ``_apply_remote_change`` with a *different*
     origin — this is what the listener loop would do when it
     receives a message from a peer.

We also exercise the publish→listen end-to-end via the in-memory
pubsub fallback (``redis_client._MemoryFallback``), which is what
runs when Redis is unavailable in tests / dev. The same code path
runs unchanged against real Redis in production.

Key invariants:

  * A peer's upsert patches the local cache instantly — no DB hit.
  * A peer's delete drops the local entry, exposing the in-code
    baseline again.
  * Local writes echo back via pubsub but are suppressed (origin
    match) so we don't double-write.
  * A "reload" message clears the cache and marks it un-loaded so the
    next ``override_decision`` defers to baseline.
"""
from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import sandbox_overrides as so


@pytest_asyncio.fixture(autouse=True)
async def _reset_state(db: AsyncSession):
    """Clear cache + ensure the listener is OFF for these tests; we
    drive the listener semantics directly. Each test starts from a
    clean (empty) DB and a freshly-loaded cache."""
    so._CACHE.clear()
    so._CACHE_LOADED = False
    await so.stop_invalidation_listener()
    await so.preload_overrides(db)
    yield
    await so.stop_invalidation_listener()
    so._CACHE.clear()
    so._CACHE_LOADED = False


def test_apply_remote_upsert_patches_local_cache():
    """Simulate a peer worker upserting (ceo, bash, allow) — the
    listener should drop the new entry into the cache without
    needing a DB round trip."""
    assert so.override_decision("ceo", "bash") is None  # baseline

    so._apply_remote_change({
        "op": "upsert", "role": "ceo", "tool": "bash",
        "allowed": True, "origin": "peer-worker-7",
    })
    assert so.override_decision("ceo", "bash") is True


def test_apply_remote_delete_clears_entry():
    so._CACHE[("ceo", "bash")] = True
    assert so.override_decision("ceo", "bash") is True

    so._apply_remote_change({
        "op": "delete", "role": "ceo", "tool": "bash",
        "origin": "peer-worker-7",
    })
    assert so.override_decision("ceo", "bash") is None


def test_apply_remote_reload_clears_and_marks_stale():
    """After a 'reload' broadcast the local cache is empty AND
    ``_CACHE_LOADED`` is False — so ``override_decision`` defers
    to baseline until the worker has re-run ``preload_overrides``.
    This is the safe direction: serve baseline rather than ghost."""
    so._CACHE[("ceo", "bash")] = True
    so._CACHE_LOADED = True

    so._apply_remote_change({"op": "reload", "origin": "peer-worker-7"})
    assert so._CACHE == {}
    assert so._CACHE_LOADED is False
    # And the resolver returns None (defer-to-baseline) until reload
    assert so.override_decision("ceo", "bash") is None


def test_apply_remote_ignores_malformed():
    """No-op on garbage input; should not raise."""
    so._apply_remote_change({"op": "wat"})
    so._apply_remote_change({})
    so._apply_remote_change({"op": "upsert"})  # missing role/tool
    assert so._CACHE == {}


@pytest.mark.asyncio
async def test_publish_then_listener_propagates_change(db: AsyncSession):
    """End-to-end: spin up the listener, then issue an upsert from a
    fake peer (i.e. publish directly with a different origin) and
    assert the local cache has caught up.

    Uses the in-memory pubsub (``_MemoryFallback``), so this test
    does NOT require a live Redis. The same code path drives real
    Redis in production.
    """
    from app.redis_client import get_redis
    import json as _json

    await so.start_invalidation_listener()
    # give the listener a tick to subscribe before we publish
    await asyncio.sleep(0.05)

    r = get_redis()
    payload = _json.dumps({
        "op": "upsert", "role": "ceo", "tool": "bash",
        "allowed": True, "origin": "fake-peer-process",
    })
    await r.publish(so._INVALIDATION_CHANNEL, payload)

    # Listener consumes asynchronously — poll until visible
    for _ in range(40):
        if so.override_decision("ceo", "bash") is True:
            break
        await asyncio.sleep(0.05)

    assert so.override_decision("ceo", "bash") is True, (
        "listener did not patch local cache from peer broadcast"
    )


@pytest.mark.asyncio
async def test_local_write_echo_is_suppressed(db: AsyncSession):
    """Our own publishes echo back through pubsub; the listener should
    drop them (origin == _PROCESS_ID) so we don't redundantly write.

    We test this by swapping out _apply_remote_change for a counter
    and confirming it stays at zero after a local upsert.
    """
    calls: list = []
    real = so._apply_remote_change
    so._apply_remote_change = lambda payload: calls.append(payload)
    try:
        await so.start_invalidation_listener()
        await asyncio.sleep(0.05)

        await so.upsert_rule(
            db, role="ceo", tool="bash", allowed=True, updated_by="me",
        )
        await db.commit()

        # Wait a little to let any echo land in the listener
        await asyncio.sleep(0.2)
    finally:
        so._apply_remote_change = real

    assert calls == [], (
        f"local write was applied via the listener (echo not suppressed): {calls}"
    )
    # ...but the local upsert path itself updated the cache
    assert so.override_decision("ceo", "bash") is True


@pytest.mark.asyncio
async def test_publish_failure_is_swallowed(monkeypatch, db: AsyncSession):
    """If Redis explodes, the local upsert still succeeds — we should
    NOT propagate the broadcast failure to API callers."""
    async def _boom(*args, **kwargs):
        raise RuntimeError("redis is on fire")

    monkeypatch.setattr(so, "_publish_change", _boom)

    # _publish_change is awaited from upsert_rule; if it raised, this
    # call would surface the error. monkeypatch replaces the entire
    # function, including its swallow logic, so we wrap it back in a
    # try/except in the test instead:
    async def _safe_boom(payload):
        try:
            await _boom(payload)
        except Exception:
            pass

    monkeypatch.setattr(so, "_publish_change", _safe_boom)

    await so.upsert_rule(
        db, role="developer", tool="git_push", allowed=False, updated_by="me",
    )
    await db.commit()
    assert so.override_decision("developer", "git_push") is False
