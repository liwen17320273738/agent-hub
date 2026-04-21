"""Real-Redis dual-worker test for SandboxRule invalidation.

This is the integration test that the unit suite *can't* cover: it
spawns a second Python process, has both subscribe to the same Redis
channel (``sandbox:rule-changed``), and verifies that a write in
worker A is visible to worker B's in-memory cache within seconds —
proving that gunicorn's ``-w N`` deployment will actually stay
consistent under admin edits.

Skip rules
==========
The test is automatically skipped when:

* Redis is not reachable on ``REDIS_URL`` (default
  ``redis://localhost:6379/15``), so this file is safe to run in
  hermetic CI without breaking the suite.
* The ``redis`` Python package is missing.

When Redis IS available, this is the one test that catches a whole
class of "looks fine in dev, breaks in prod" multi-worker bugs:
forgotten ``await``, broken JSON wire format, listener-loop
dying-silently regressions, etc.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import time
import uuid

import pytest


# ─────────────────────────────────────────────────────────────────────
# Skip-if-no-redis guard.
# ─────────────────────────────────────────────────────────────────────


def _redis_reachable() -> bool:
    url = os.getenv("REDIS_URL", "redis://localhost:6379/15")
    host, port = "localhost", 6379
    try:
        if "://" in url:
            netloc = url.split("://", 1)[1].split("/", 1)[0]
            if ":" in netloc:
                host, port_str = netloc.rsplit(":", 1)
                port = int(port_str) if port_str.isdigit() else 6379
            else:
                host = netloc
    except Exception:
        return False
    try:
        s = socket.socket()
        s.settimeout(0.5)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_reachable(),
    reason="Redis not reachable on REDIS_URL; skipping cross-process integration test.",
)


# ─────────────────────────────────────────────────────────────────────
# The "worker B" subscriber lives in this script. We run the SAME file
# as a child process via ``python -m`` style invocation of an inline
# subprocess script (defined below as a multiline string) — this avoids
# the import-from-test-as-module trap and keeps the wire protocol
# explicit.
# ─────────────────────────────────────────────────────────────────────


_SUBSCRIBER_SCRIPT = r"""
"""
# (intentionally empty — we use ``-c`` with the SCRIPT_BODY constant)


SCRIPT_BODY = r'''
"""Child-process subscriber.

Mirrors what ``app.services.sandbox_overrides`` does on app startup:
  1. Set REDIS_URL / DATABASE_URL etc. so the module imports cleanly.
  2. Preload the (empty) cache.
  3. Start the invalidation listener.
  4. Poll ``override_decision`` until we see the expected change OR
     time out.
  5. Print a single JSON status line to stdout for the parent to read.
"""
import asyncio
import json
import os
import sys
import time

REDIS_URL = sys.argv[1]
DATABASE_URL = sys.argv[2]
EXPECTED_ROLE = sys.argv[3]
EXPECTED_TOOL = sys.argv[4]
EXPECTED_ALLOWED = sys.argv[5] == "true"
DEADLINE_SEC = float(sys.argv[6])

os.environ["REDIS_URL"] = REDIS_URL
os.environ["DATABASE_URL"] = DATABASE_URL
os.environ.setdefault("JWT_SECRET", "test-secret-must-be-at-least-32-characters-long!")
os.environ.setdefault("ADMIN_EMAIL", "test@test.com")
os.environ.setdefault("ADMIN_PASSWORD", "testpassword")
os.environ.setdefault("DEBUG", "true")


async def main():
    # Imports must happen AFTER env so config/redis pick the right values.
    from app.services import sandbox_overrides as so
    from app.database import async_session, engine, Base

    # Build the schema once on this child too — we use the same
    # in-memory SQLite (cache=shared) URL so workers share state.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as db:
        n = await so.preload_overrides(db)

    await so.start_invalidation_listener()

    deadline = time.time() + DEADLINE_SEC
    seen = None
    while time.time() < deadline:
        seen = so.override_decision(EXPECTED_ROLE, EXPECTED_TOOL)
        if seen == EXPECTED_ALLOWED:
            break
        await asyncio.sleep(0.05)

    await so.stop_invalidation_listener()

    print(json.dumps({
        "ok": seen == EXPECTED_ALLOWED,
        "seen": seen,
        "expected": EXPECTED_ALLOWED,
        "preload_count": n,
        "process_id": so._PROCESS_ID,
    }), flush=True)


asyncio.run(main())
'''


@pytest.mark.asyncio
async def test_dual_worker_real_redis_propagation():
    """Worker A publishes a rule change → worker B sees it via cache.

    Concretely:
      * Both workers point to the same Redis (real, not in-memory
        fallback) and the same in-memory shared SQLite.
      * Worker B is a subprocess that subscribes to
        ``sandbox:rule-changed`` and polls ``override_decision``.
      * Worker A (this process) publishes ONE message simulating a
        peer's upsert.
      * Worker B must catch it within DEADLINE_SEC.
    """
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/15")
    # Use a private SQLite shared-cache name per test run so we don't
    # collide with other concurrent runs.
    db_name = f"sandbox_dualworker_{uuid.uuid4().hex[:8]}"
    database_url = f"sqlite+aiosqlite:///file:{db_name}?mode=memory&cache=shared&uri=true"

    role = "ceo"
    tool = "bash"
    deadline_sec = 5.0

    # ── Spawn worker B (subprocess) ───────────────────────────────
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", SCRIPT_BODY,
        redis_url, database_url, role, tool, "true", str(deadline_sec),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    )

    # ── Give worker B time to subscribe before we publish ─────────
    # The listener loop calls ``ps.subscribe()`` which is async over
    # the network — if we publish too early, our message lands before
    # the subscription is active and is dropped.
    await asyncio.sleep(1.0)

    # ── Publish from worker A (this process) ──────────────────────
    # We import here, AFTER setting REDIS_URL on this side too, so we
    # hit the same Redis instance.
    os.environ["REDIS_URL"] = redis_url
    from app.redis_client import get_redis, _init_redis
    # Force re-init so the module-level singleton picks up REDIS_URL
    # if a previous test left a fallback in place.
    import app.redis_client as rc
    rc._redis_instance = None
    rc._fallback_mode = False
    _init_redis()

    if rc._fallback_mode:
        proc.kill()
        await proc.wait()
        pytest.skip(
            "Redis client fell back to in-memory mode — real Redis "
            "needed for cross-process test."
        )

    r = get_redis()
    payload = {
        "op": "upsert",
        "role": role, "tool": tool,
        "allowed": True,
        "origin": f"worker-A-{uuid.uuid4().hex[:8]}",
    }
    n_subs = await r.publish("sandbox:rule-changed", json.dumps(payload))
    # If no subscriber received the message, worker B never made it
    # to ``ps.subscribe()`` in time — bump the sleep above.
    assert n_subs >= 1, (
        f"no subscribers when worker A published — worker B didn't "
        f"subscribe in time (publish returned {n_subs})"
    )

    # ── Wait for worker B's verdict ───────────────────────────────
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=deadline_sec + 5.0,
        )
    except asyncio.TimeoutError:
        proc.kill()
        stdout, stderr = await proc.communicate()
        pytest.fail(
            f"worker B did not exit in time. stdout={stdout!r} stderr={stderr!r}"
        )

    assert proc.returncode == 0, (
        f"worker B crashed: exit={proc.returncode}\n"
        f"stdout={stdout.decode(errors='replace')[-1000:]}\n"
        f"stderr={stderr.decode(errors='replace')[-1000:]}"
    )

    # The script prints exactly one JSON line at the end. Parse it.
    last_line = stdout.decode(errors="replace").strip().splitlines()[-1]
    try:
        verdict = json.loads(last_line)
    except Exception:
        pytest.fail(
            f"worker B produced un-parseable output: {stdout.decode()!r} "
            f"stderr={stderr.decode()!r}"
        )

    assert verdict["ok"], (
        f"worker B did NOT see the broadcast within {deadline_sec}s.\n"
        f"  expected override_decision({role!r}, {tool!r}) == True\n"
        f"  saw: {verdict['seen']!r}\n"
        f"  worker B process_id: {verdict.get('process_id')}\n"
        f"  worker B preload_count: {verdict.get('preload_count')}\n"
        f"  worker A subscribers at publish: {n_subs}\n"
        f"  stderr tail: {stderr.decode(errors='replace')[-500:]}"
    )
