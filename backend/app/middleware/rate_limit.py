"""Redis-based sliding window rate limiter."""
from __future__ import annotations

import time

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings
from ..redis_client import redis


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/health", "/docs", "/openapi.json"):
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
            return await call_next(request)

        if request_count > settings.rate_limit_per_minute:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试")

        return await call_next(request)
