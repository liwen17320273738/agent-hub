"""Per-task lock + pending-feedback queue for the feedback iteration loop.

Goals:
- Prevent concurrent `run_full_e2e` invocations on the same `task_id`.
- If a second feedback arrives while the first is running, queue its
  contents (so the running iteration can pick them up after it finishes).

Backed by Redis (or in-memory fallback). Locks have a hard TTL so a
crashed worker can't deadlock the task forever.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List

from ..redis_client import get_redis

logger = logging.getLogger(__name__)

DEFAULT_LOCK_TTL = 60 * 30  # 30 minutes — longer than typical e2e


def _lock_key(task_id: str) -> str:
    return f"feedback:running:{task_id}"


def _queue_key(task_id: str) -> str:
    return f"feedback:queue:{task_id}"


async def acquire_lock(task_id: str, owner: str, ttl: int = DEFAULT_LOCK_TTL) -> bool:
    """Try to acquire the per-task feedback lock. Returns True on success."""
    if not task_id:
        return False
    r = get_redis()
    key = _lock_key(task_id)
    try:
        try:
            result = await r.set(key, owner, nx=True, ex=ttl)
            return bool(result)
        except TypeError:
            existing = await r.get(key)
            if existing:
                return False
            await r.setex(key, ttl, owner)
            return True
    except Exception as e:
        logger.warning(f"[feedback-lock] acquire failed for {task_id}: {e}")
        return True  # fail-open: don't block the user on infra errors


async def release_lock(task_id: str, owner: str) -> None:
    """Release the lock if we still own it."""
    if not task_id:
        return
    r = get_redis()
    try:
        current = await r.get(_lock_key(task_id))
        if isinstance(current, bytes):
            current = current.decode("utf-8")
        if current == owner or current is None:
            await r.delete(_lock_key(task_id))
    except Exception as e:
        logger.warning(f"[feedback-lock] release failed for {task_id}: {e}")


async def enqueue_pending(task_id: str, payload: Dict[str, Any]) -> int:
    """Append a feedback payload to the pending queue. Returns new length."""
    r = get_redis()
    try:
        record = {**payload, "queued_at": time.time()}
        await r.rpush(_queue_key(task_id), json.dumps(record, ensure_ascii=False))
        await r.expire(_queue_key(task_id), DEFAULT_LOCK_TTL * 2)
        length = await r.llen(_queue_key(task_id))
        return int(length or 0)
    except Exception as e:
        logger.warning(f"[feedback-queue] enqueue failed for {task_id}: {e}")
        return 0


async def drain_pending(task_id: str) -> List[Dict[str, Any]]:
    """Pop all pending feedback payloads (FIFO) for a task and clear the queue."""
    r = get_redis()
    try:
        items = await r.lrange(_queue_key(task_id), 0, -1)
        await r.delete(_queue_key(task_id))
        out: List[Dict[str, Any]] = []
        for raw in items or []:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            try:
                out.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                continue
        return out
    except Exception as e:
        logger.warning(f"[feedback-queue] drain failed for {task_id}: {e}")
        return []


async def is_locked(task_id: str) -> bool:
    r = get_redis()
    try:
        return bool(await r.get(_lock_key(task_id)))
    except Exception:
        return False


async def queued_count(task_id: str) -> int:
    r = get_redis()
    try:
        return int(await r.llen(_queue_key(task_id)) or 0)
    except Exception:
        return 0
