"""Unit tests for the global TaskScheduler.

What's covered:

  * ``register_kind`` / ``list_kinds`` — module-level registry
  * Concurrency cap is enforced (semaphore = N → only N running)
  * Submitting via ``coro_factory`` (legacy escape hatch) works
  * Submitting via ``kind+params`` reconstructs the coroutine via the
    builder and runs it
  * Submitting an unknown kind without a coro_factory raises
  * Lifetime counters tick on submit / finish / fail
  * ``status()`` shape stays stable for the API contract

We deliberately do NOT exercise the Redis persistence path here — that
needs a live Redis and is covered by the ``smoke`` script. The
in-memory scheduler is what the API contracts on.
"""
from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio

from app.services import task_scheduler as ts_mod


@pytest.fixture(autouse=True)
def _reset_registry():
    """Each test starts with a clean registry — these tests register
    test-specific kinds that would otherwise leak across cases."""
    saved = dict(ts_mod._KIND_BUILDERS)
    ts_mod._KIND_BUILDERS.clear()
    yield
    ts_mod._KIND_BUILDERS.clear()
    ts_mod._KIND_BUILDERS.update(saved)


@pytest_asyncio.fixture
async def fresh_scheduler():
    """A brand-new scheduler instance — bypassing the singleton — so
    lifetime counters and queue state are isolated per test.

    Constructed inside an async fixture so the embedded
    ``asyncio.Semaphore`` binds to the test's event loop (Python 3.9
    captures the loop at construction time).
    """
    return ts_mod.TaskScheduler(max_concurrent=2)


def test_register_kind_idempotent_and_listed():
    def builder(params):
        async def _run(db):
            return None
        return _run

    ts_mod.register_kind("smoke-kind", builder)
    assert "smoke-kind" in ts_mod.list_kinds()

    # re-register overwrites silently (no exception)
    ts_mod.register_kind("smoke-kind", builder)
    assert ts_mod.list_kinds().count("smoke-kind") == 1


@pytest.mark.asyncio
async def test_submit_legacy_coro_factory_runs(fresh_scheduler):
    """The legacy ``coro_factory=`` path still works for callers that
    can't be made resumable."""
    ran = asyncio.Event()

    async def _factory(db):
        ran.set()

    sid = await fresh_scheduler.submit(
        task_id="t1", label="legacy", coro_factory=_factory,
    )
    assert isinstance(sid, str) and len(sid) >= 16

    await asyncio.wait_for(ran.wait(), timeout=2.0)
    # let the finalisation block in _run() finish
    for _ in range(20):
        if fresh_scheduler.status()["lifetime"]["finished"] >= 1:
            break
        await asyncio.sleep(0.05)

    st = fresh_scheduler.status()
    assert st["lifetime"]["submitted"] == 1
    assert st["lifetime"]["finished"] == 1
    assert st["lifetime"]["failed"] == 0


@pytest.mark.asyncio
async def test_submit_via_registered_kind_runs(fresh_scheduler):
    """Submitting with ``kind+params`` (the resumable path) reconstructs
    the coroutine via the registered builder."""
    captured: dict = {}

    def builder(params):
        async def _run(db):
            captured["params"] = params
        return _run

    ts_mod.register_kind("kind-a", builder)

    sid = await fresh_scheduler.submit(
        task_id="t2", label="via-kind",
        kind="kind-a", params={"hello": "world"},
    )
    assert sid

    for _ in range(20):
        if "params" in captured:
            break
        await asyncio.sleep(0.05)

    assert captured.get("params") == {"hello": "world"}


@pytest.mark.asyncio
async def test_submit_unknown_kind_without_factory_raises(fresh_scheduler):
    """Caller forgot to register the kind AND didn't pass a coro_factory
    — this is a programmer error, surface it."""
    with pytest.raises(ValueError, match="needs either coro_factory"):
        await fresh_scheduler.submit(
            task_id="t3", label="bad",
            kind="never-registered", params={"x": 1},
        )


@pytest.mark.asyncio
async def test_concurrency_cap_enforced(fresh_scheduler):
    """With max_concurrent=2 and 4 long-running submissions, exactly 2
    should be running at any given moment, the rest queued."""
    enter_gate = asyncio.Event()
    exit_gate = asyncio.Event()
    entered_count = 0
    lock = asyncio.Lock()

    def builder(params):
        async def _run(db):
            nonlocal entered_count
            async with lock:
                entered_count += 1
                if entered_count >= 2:
                    enter_gate.set()
            await exit_gate.wait()
        return _run

    ts_mod.register_kind("blocker", builder)

    # submit 4 jobs at once
    for i in range(4):
        await fresh_scheduler.submit(
            task_id=f"t{i}", label=f"blk-{i}",
            kind="blocker", params={"i": i},
        )

    # wait for the first 2 to grab the semaphore
    await asyncio.wait_for(enter_gate.wait(), timeout=2.0)
    # tiny breath so the run loop can settle queued state
    await asyncio.sleep(0.05)

    st = fresh_scheduler.status()
    assert st["runningCount"] == 2, f"cap not enforced: {st}"
    assert st["queueDepth"] == 2, f"backpressure missing: {st}"
    assert st["lifetime"]["submitted"] == 4

    exit_gate.set()
    # let everything drain
    for _ in range(40):
        if fresh_scheduler.status()["lifetime"]["finished"] >= 4:
            break
        await asyncio.sleep(0.05)
    assert fresh_scheduler.status()["lifetime"]["finished"] == 4


@pytest.mark.asyncio
async def test_failed_task_increments_failed_counter(fresh_scheduler):
    def builder(params):
        async def _run(db):
            raise RuntimeError("boom")
        return _run

    ts_mod.register_kind("crasher", builder)

    await fresh_scheduler.submit(
        task_id="tx", label="will-crash",
        kind="crasher", params={"sentinel": True},
    )
    for _ in range(20):
        if fresh_scheduler.status()["lifetime"]["failed"] >= 1:
            break
        await asyncio.sleep(0.05)

    st = fresh_scheduler.status()
    assert st["lifetime"]["failed"] == 1
    assert st["lifetime"]["finished"] == 0


@pytest.mark.asyncio
async def test_status_shape_is_stable(fresh_scheduler):
    """The /api/scheduler/status endpoint contracts on these keys —
    breaking the shape would break the dashboard."""
    st = fresh_scheduler.status()
    for key in ("maxConcurrent", "running", "queued",
                "runningCount", "queueDepth", "registeredKinds", "lifetime"):
        assert key in st, f"missing key: {key}"
    for key in ("submitted", "finished", "failed", "resumed_from_restart"):
        assert key in st["lifetime"], f"missing lifetime.{key}"
