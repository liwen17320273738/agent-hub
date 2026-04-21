"""Redis-based sliding window rate limiter.

Degrades gracefully: if Redis is unavailable, uses an in-memory counter
per IP (not shared across workers, but still provides basic protection).

Notes on the 429-vs-500 trap:
    Starlette's ``BaseHTTPMiddleware`` runs ``dispatch`` inside its own
    AnyIO TaskGroup. If we ``raise HTTPException(...)`` from there, the
    exception propagates *outside* of FastAPI's exception-handler chain
    and surfaces to the ASGI server as an unhandled error → 500. So we
    have to **return** a ``JSONResponse(429, ...)`` instead of raising.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..config import settings
from ..redis_client import redis

logger = logging.getLogger(__name__)

# Endpoints that should never be rate-limited (health checks, docs, and the
# polling endpoints used by the frontend pipeline detail view — those are
# already authenticated and self-throttle on the client side).
_EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

# Loopback / link-local addresses. Local dev hits these constantly when the
# Vue dev server polls multiple endpoints; rate-limiting them produces an
# unusable UI without any real abuse-prevention benefit.
_EXEMPT_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}

_local_counters: dict[str, list[float]] = defaultdict(list)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        # Local development: bypass entirely. The frontend dashboard polls
        # ~7 endpoints per refresh; capping at 60 req/min would make the UI
        # unusable while providing zero protection (the host is already trusted).
        if client_ip in _EXEMPT_HOSTS:
            return await call_next(request)

        key = f"ratelimit:{client_ip}"
        now = time.time()
        window = 60

        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, now - window)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window)

        try:
            results = await pipe.execute()
            request_count = results[2]
        except Exception:
            request_count = self._local_rate_check(client_ip, now, window)

        limit = settings.rate_limit_per_minute
        if request_count > limit:
            retry_after = max(1, window)
            logger.warning(
                "[ratelimit] %s exceeded %d/min (count=%d) on %s",
                client_ip, limit, request_count, request.url.path,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "请求过于频繁，请稍后重试",
                    "limit": limit,
                    "window_seconds": window,
                    "retry_after_seconds": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Window": str(window),
                },
            )

        return await call_next(request)

    @staticmethod
    def _local_rate_check(client_ip: str, now: float, window: int) -> int:
        """In-memory fallback when Redis is unavailable."""
        timestamps = _local_counters[client_ip]
        cutoff = now - window
        _local_counters[client_ip] = [t for t in timestamps if t > cutoff]
        _local_counters[client_ip].append(now)
        return len(_local_counters[client_ip])
