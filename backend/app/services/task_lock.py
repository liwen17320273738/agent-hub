"""
Per-task Redis mutex for preventing concurrent execution on the same task.

Gateway e2e, dag-run, auto-run, smart-run all operate on the same PipelineTask.
Without a per-task lock, concurrent runs on the same task produce conflicting
worktrees, duplicated artifacts, and confusing SSE events.

Usage::

    lock = TaskLock(task_id, ttl=3600)
    if not await lock.acquire():
        raise HTTPException(409, "Task is already being executed")
    try:
        ... run pipeline ...
    finally:
        await lock.release()

Alternatively, use ``async with TaskLock(task_id) as lock:``.
"""
from __future__ import annotations

import logging
from typing import Optional

from ..redis_client import redis

logger = logging.getLogger(__name__)

_LOCK_PREFIX = "agenthub:task-lock:"
_DEFAULT_TTL = 1800  # 30 minutes — longest pipeline run rarely exceeds this


class TaskLock:
    """Redis-based per-task mutex (non-reentrant)."""

    def __init__(self, task_id: str, ttl: int = _DEFAULT_TTL):
        key = task_id.strip().replace("-", "")[:36]
        self._key = f"{_LOCK_PREFIX}{key}"
        self._ttl = ttl
        self._locked = False

    async def acquire(self) -> bool:
        """Try to acquire the lock. Returns True if acquired, False if held by
        another worker.

        Uses the atomic ``SET key val NX EX ttl`` form — a single round trip
        that is portable across real redis-py and the in-memory fallback
        (which both accept ``nx`` / ``ex`` kwargs on ``set``)."""
        try:
            ok = await redis.set(self._key, "1", nx=True, ex=self._ttl)
            if ok:
                self._locked = True
                logger.debug("[task-lock] Acquired %s (TTL=%ds)", self._key, self._ttl)
                return True
            logger.info(
                "[task-lock] %s already locked, concurrent run prevented", self._key,
            )
            return False
        except Exception as e:
            # Redis down — degrade gracefully rather than blocking the pipeline.
            # Note: in multi-worker mode each process has its own in-memory
            # fallback, so the lock does NOT work across workers without Redis.
            # SSE/pubsub also degrades to single-process in that scenario.
            logger.warning(
                "[task-lock] Redis unavailable (%s), lock BYPASSED for %s. "
                "Multi-worker concurrent runs of the same task are NOT prevented.",
                e, self._key,
            )
            return True

    async def release(self) -> None:
        """Release the lock. Safe to call even if we never acquired it."""
        if not self._locked:
            return
        try:
            await redis.delete(self._key)
            logger.debug("[task-lock] Released %s", self._key)
        except Exception as e:
            logger.warning("[task-lock] Failed to release %s: %s", self._key, e)
        finally:
            self._locked = False

    async def __aenter__(self) -> "TaskLock":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.release()
