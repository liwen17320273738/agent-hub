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
_memory_sets: dict[str, set[str]] = {}
_memory_zsets: dict[str, dict[str, float]] = {}
_memory_pubsub_channels: dict[str, list[asyncio.Queue]] = {}


class _MemoryFallback:
    """In-memory Redis-like stub for development without Redis."""

    # --- String / generic key operations ---

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
        _memory_sets.pop(key, None)
        _memory_zsets.pop(key, None)

    async def expire(self, key: str, ttl: int) -> None:
        _memory_expiry[key] = time.time() + ttl

    # --- Hash operations ---

    async def hset(self, key: str, field: str, value: str) -> None:
        if key not in _memory_store or not isinstance(_memory_store[key], dict):
            _memory_store[key] = {}
        _memory_store[key][field] = value

    async def hgetall(self, key: str) -> dict:
        self._expire_check(key)
        val = _memory_store.get(key, {})
        return val if isinstance(val, dict) else {}

    # --- Pub/Sub (in-process only, no cross-worker delivery) ---

    async def publish(self, channel: str, message: str) -> int:
        subs = _memory_pubsub_channels.get(channel, [])
        for q in subs:
            try:
                q.put_nowait({"type": "message", "channel": channel, "data": message})
            except asyncio.QueueFull:
                pass
        return len(subs)

    def pubsub(self):
        return _MemoryPubSub()

    async def pubsub_numsub(self, *channels):
        return [(ch, len(_memory_pubsub_channels.get(ch, []))) for ch in channels]

    def pipeline(self):
        return _MemoryPipeline()

    # --- List operations ---

    async def rpush(self, key: str, *values: str) -> int:
        if key not in _memory_store or not isinstance(_memory_store[key], list):
            _memory_store[key] = []
        _memory_store[key].extend(values)
        return len(_memory_store[key])

    async def lrange(self, key: str, start: int, end: int) -> list:
        self._expire_check(key)
        val = _memory_store.get(key, [])
        if not isinstance(val, list):
            return []
        if end < 0:
            end = len(val) + end + 1
        else:
            end = end + 1
        return val[start:end]

    async def llen(self, key: str) -> int:
        self._expire_check(key)
        lst = _memory_store.get(key, [])
        return len(lst) if isinstance(lst, list) else 0

    # --- Set operations (use dedicated _memory_sets) ---

    async def sadd(self, key: str, *members: str) -> int:
        if key not in _memory_sets:
            _memory_sets[key] = set()
        before = len(_memory_sets[key])
        _memory_sets[key].update(str(m) for m in members)
        return len(_memory_sets[key]) - before

    async def srem(self, key: str, *members: str) -> int:
        if key not in _memory_sets:
            return 0
        removed = 0
        for m in members:
            if str(m) in _memory_sets[key]:
                _memory_sets[key].discard(str(m))
                removed += 1
        return removed

    async def smembers(self, key: str) -> set:
        return set(_memory_sets.get(key, set()))

    # --- Sorted set operations (use dedicated _memory_zsets) ---

    async def zadd(self, key: str, mapping: dict, **kwargs) -> int:
        if key not in _memory_zsets:
            _memory_zsets[key] = {}
        added = 0
        for member, score in mapping.items():
            if member not in _memory_zsets[key]:
                added += 1
            _memory_zsets[key][member] = float(score)
        return added

    async def zrem(self, key: str, *members: str) -> int:
        zset = _memory_zsets.get(key)
        if not zset:
            return 0
        removed = 0
        for m in members:
            if m in zset:
                del zset[m]
                removed += 1
        return removed

    async def zrange(self, key: str, start: int, end: int, **kwargs) -> list:
        zset = _memory_zsets.get(key, {})
        items = sorted(zset.items(), key=lambda x: x[1])
        members = [m for m, _ in items]
        if end == -1:
            return members[start:]
        return members[start:end + 1]

    async def zrevrange(self, key: str, start: int, end: int, **kwargs) -> list:
        zset = _memory_zsets.get(key, {})
        items = sorted(zset.items(), key=lambda x: x[1], reverse=True)
        members = [m for m, _ in items]
        if end == -1:
            return members[start:]
        return members[start:end + 1]

    async def zcard(self, key: str) -> int:
        return len(_memory_zsets.get(key, {}))

    async def zremrangebyrank(self, key: str, start: int, stop: int) -> int:
        zset = _memory_zsets.get(key)
        if not zset:
            return 0
        items = sorted(zset.items(), key=lambda x: x[1])
        if stop < 0:
            stop = len(items) + stop
        to_remove = items[start:stop + 1]
        for m, _ in to_remove:
            del zset[m]
        return len(to_remove)

    # --- Scan ---

    async def scan_iter(self, match: str = "*"):
        import fnmatch
        for key in list(_memory_store.keys()):
            if fnmatch.fnmatch(key, match):
                yield key

    # --- Internal ---

    def _expire_check(self, key: str):
        exp = _memory_expiry.get(key)
        if exp and time.time() > exp:
            _memory_store.pop(key, None)
            _memory_expiry.pop(key, None)


class _MemoryPubSub:
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._channels: list[str] = []

    async def subscribe(self, *channels):
        for ch in channels:
            if ch not in _memory_pubsub_channels:
                _memory_pubsub_channels[ch] = []
            _memory_pubsub_channels[ch].append(self._queue)
            self._channels.append(ch)

    async def unsubscribe(self, *channels):
        for ch in channels:
            if ch in _memory_pubsub_channels:
                try:
                    _memory_pubsub_channels[ch].remove(self._queue)
                except ValueError:
                    pass
            if ch in self._channels:
                self._channels.remove(ch)

    async def close(self):
        for ch in list(self._channels):
            await self.unsubscribe(ch)

    async def listen(self):
        while True:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=30)
                yield msg
            except asyncio.TimeoutError:
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
