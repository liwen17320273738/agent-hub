"""Redis-based sliding window rate limiter.

Degrades gracefully: if Redis is unavailable, uses an in-memory counter
per IP (not shared across workers, but still provides basic protection).
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings
from ..redis_client import redis

logger = logging.getLogger(__name__)

_EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

_local_counters: dict[str, list[float]] = defaultdict(list)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
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

        if request_count > settings.rate_limit_per_minute:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试")

        return await call_next(request)

    @staticmethod
    def _local_rate_check(client_ip: str, now: float, window: int) -> int:
        """In-memory fallback when Redis is unavailable."""
        timestamps = _local_counters[client_ip]
        cutoff = now - window
        _local_counters[client_ip] = [t for t in timestamps if t > cutoff]
        _local_counters[client_ip].append(now)
        return len(_local_counters[client_ip])
