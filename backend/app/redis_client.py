"""
Redis client with graceful in-memory fallback for local development.

When Redis is unavailable, all operations use a simple dict store.
This allows the system to start without Docker/Redis.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from .config import settings

logger = logging.getLogger(__name__)

_redis_instance = None
_fallback_mode = False
_memory_store: dict[str, Any] = {}
_memory_expiry: dict[str, float] = {}


class _MemoryFallback:
    """In-memory Redis-like stub for development without Redis."""

    async def get(self, key: str) -> Optional[str]:
        self._expire_check(key)
        return _memory_store.get(key)

    async def set(self, key: str, value: str) -> None:
        _memory_store[key] = value

    async def setex(self, key: str, ttl: int, value: str) -> None:
        _memory_store[key] = value
        _memory_expiry[key] = time.time() + ttl

    async def delete(self, key: str) -> None:
        _memory_store.pop(key, None)
        _memory_expiry.pop(key, None)

    async def hset(self, key: str, field: str, value: str) -> None:
        if key not in _memory_store or not isinstance(_memory_store[key], dict):
            _memory_store[key] = {}
        _memory_store[key][field] = value

    async def hgetall(self, key: str) -> dict:
        self._expire_check(key)
        val = _memory_store.get(key, {})
        return val if isinstance(val, dict) else {}

    async def expire(self, key: str, ttl: int) -> None:
        _memory_expiry[key] = time.time() + ttl

    async def publish(self, channel: str, message: str) -> int:
        return 0

    def pubsub(self):
        return _MemoryPubSub()

    async def pubsub_numsub(self, *channels):
        return [(ch, 0) for ch in channels]

    def pipeline(self):
        return _MemoryPipeline()

    async def scan_iter(self, match: str = "*"):
        import fnmatch
        for key in list(_memory_store.keys()):
            if fnmatch.fnmatch(key, match):
                yield key

    def _expire_check(self, key: str):
        exp = _memory_expiry.get(key)
        if exp and time.time() > exp:
            _memory_store.pop(key, None)
            _memory_expiry.pop(key, None)


class _MemoryPubSub:
    async def subscribe(self, *channels):
        pass

    async def unsubscribe(self, *channels):
        pass

    async def close(self):
        pass

    async def listen(self):
        while True:
            await asyncio.sleep(30)
            yield {"type": "heartbeat", "data": ""}


class _MemoryPipeline:
    _ops: list = []

    def __init__(self):
        self._ops = []

    def zremrangebyscore(self, key, min_score, max_score):
        self._ops.append(0)
        return self

    def zadd(self, key, mapping):
        self._ops.append(True)
        return self

    def zcard(self, key):
        self._ops.append(0)
        return self

    def expire(self, key, ttl):
        self._ops.append(True)
        return self

    async def execute(self):
        result = list(self._ops)
        self._ops.clear()
        return result


def _init_redis():
    global _redis_instance, _fallback_mode

    if _redis_instance is not None:
        return

    try:
        import redis.asyncio as aioredis
        import socket
        host = "localhost"
        port = 6379
        url = settings.redis_url
        if "://" in url:
            parts = url.split("://", 1)[1].split("/")[0]
            if ":" in parts:
                host, port_str = parts.rsplit(":", 1)
                port = int(port_str) if port_str.isdigit() else 6379

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((host, port))
        sock.close()

        if result != 0:
            raise ConnectionError(f"Redis not reachable at {host}:{port}")

        pool = aioredis.ConnectionPool.from_url(url, decode_responses=True)
        _redis_instance = aioredis.Redis(connection_pool=pool)
        _fallback_mode = False
        logger.info(f"Redis client initialized: {url}")
    except Exception as e:
        logger.warning(f"Redis unavailable ({e}), using in-memory fallback")
        _redis_instance = _MemoryFallback()
        _fallback_mode = True


def get_redis():
    """Get the Redis client (or in-memory fallback)."""
    if _redis_instance is None:
        _init_redis()
    return _redis_instance


# Legacy compatibility: `from .redis_client import redis`
class _LazyRedis:
    def __getattr__(self, name):
        return getattr(get_redis(), name)

redis = _LazyRedis()


async def cache_get(key: str) -> Optional[Any]:
    r = get_redis()
    raw = await r.get(key)
    if raw is None:
        return None
    return json.loads(raw)


async def cache_set(key: str, data: Any, ttl: Optional[int] = None) -> None:
    r = get_redis()
    payload = json.dumps(data, ensure_ascii=False)
    if ttl:
        await r.setex(key, ttl, payload)
    else:
        await r.set(key, payload)


async def cache_delete(key: str) -> None:
    r = get_redis()
    await r.delete(key)


async def cache_delete_pattern(pattern: str) -> None:
    r = get_redis()
    async for key in r.scan_iter(match=pattern):
        await r.delete(key)
