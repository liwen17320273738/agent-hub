"""Tests for the RateLimitMiddleware contract.

Two regressions we explicitly guard against:
1. Returning 500 instead of 429 (the old `raise HTTPException` bug — Starlette's
   BaseHTTPMiddleware doesn't route framework exceptions through FastAPI's
   exception handlers, so they surface as ASGI errors → 500).
2. Rate-limiting localhost requests in dev (the dashboard polls 7+ endpoints
   per refresh; a 60/min cap froze the UI within ~10s).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.rate_limit import RateLimitMiddleware
from app.config import settings


@pytest.fixture(autouse=True)
def _force_local_counters_and_clear(monkeypatch):
    """Tests need deterministic counter state. Real Redis carries timestamps
    across test runs (sliding-window ZSET) AND the redis-py async client gets
    bound to TestClient's event loop, making cleanup unreliable. So we make
    the middleware's Redis pipeline raise, which falls through to the in-
    process ``_local_counters`` dict — perfect for assertions, zero leakage
    between tests once we clear it."""
    from app.middleware import rate_limit as rl_mod

    class _FailingPipeline:
        def zremrangebyscore(self, *a, **kw): return self
        def zadd(self, *a, **kw): return self
        def zcard(self, *a, **kw): return self
        def expire(self, *a, **kw): return self
        async def execute(self):
            raise RuntimeError("simulated redis failure for test isolation")

    class _FailingRedis:
        def pipeline(self):
            return _FailingPipeline()

    monkeypatch.setattr(rl_mod, "redis", _FailingRedis())
    rl_mod._local_counters.clear()
    yield
    rl_mod._local_counters.clear()


def _make_app(*, override_limit: int | None = None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    if override_limit is not None:
        settings.rate_limit_per_minute = override_limit
    return app


def test_localhost_is_exempt_from_rate_limit(monkeypatch):
    """127.0.0.1 should bypass the limiter entirely. The dashboard makes
    bursts of polling requests during local dev; capping them is unusable
    for zero abuse-prevention benefit.

    Starlette's TestClient reports its client IP as ``"testclient"`` rather
    than ``127.0.0.1`` so we extend the exempt set for the test only — what
    we're really verifying is *the bypass-by-host mechanism itself works*,
    not the literal string list (that's a config concern, covered separately
    by reading the module-level constant)."""
    from app.middleware import rate_limit as rl_mod
    monkeypatch.setattr(rl_mod, "_EXEMPT_HOSTS", {"testclient", "127.0.0.1", "::1"})

    app = _make_app(override_limit=2)
    with TestClient(app) as client:
        for _ in range(50):
            r = client.get("/ping")
            assert r.status_code == 200, (
                f"exempt host was rate-limited (status={r.status_code}); "
                f"the bypass-by-host check is broken"
            )


def test_loopback_addresses_are_in_default_exempt_set():
    """Pin the default config so a future PR can't accidentally drop
    127.0.0.1 from the exempt list (which would re-freeze the dashboard)."""
    from app.middleware.rate_limit import _EXEMPT_HOSTS
    assert "127.0.0.1" in _EXEMPT_HOSTS
    assert "::1" in _EXEMPT_HOSTS
    assert "localhost" in _EXEMPT_HOSTS


def test_health_path_is_exempt():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/health")
    async def health():
        return {"ok": True}

    settings.rate_limit_per_minute = 1
    with TestClient(app) as client:
        for _ in range(10):
            assert client.get("/health").status_code == 200


def test_429_response_shape_when_limit_tripped(monkeypatch):
    """The middleware MUST return a JSONResponse(429), not raise an
    HTTPException — the latter bubbles up as a 500 due to a Starlette quirk
    in BaseHTTPMiddleware. This test would fail if we ever regress to
    `raise HTTPException(...)`."""
    from app.middleware import rate_limit as rl_mod

    # Force the middleware to think we're not local.
    monkeypatch.setattr(rl_mod, "_EXEMPT_HOSTS", set())
    settings.rate_limit_per_minute = 2

    app = _make_app()

    with TestClient(app) as client:
        ok_count = 0
        rate_limited_seen = False
        for _ in range(8):
            r = client.get("/ping")
            if r.status_code == 200:
                ok_count += 1
            elif r.status_code == 429:
                rate_limited_seen = True
                # Critically: must be 429, never 500.
                body = r.json()
                assert body.get("limit") == 2
                assert "retry_after_seconds" in body
                assert "Retry-After" in r.headers
            else:  # pragma: no cover
                raise AssertionError(
                    f"Unexpected status {r.status_code} — middleware should "
                    f"return 200 or 429, never {r.status_code}"
                )

        assert rate_limited_seen, "Limit was never tripped despite 8 requests at limit=2"
        assert ok_count >= 2  # the first `limit` requests should have passed
