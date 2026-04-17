"""IM-user → last-task binding (Redis-backed, in-memory fallback).

When a user sends a message via Feishu/QQ, we record `(source, user_id) → task_id`
so a follow-up message like "改下颜色" can be routed back to that task as
feedback, without requiring the user to remember a uuid.

TTL defaults to 7 days. Latest binding wins.
"""
from __future__ import annotations

import logging
from typing import Optional

from ..redis_client import get_redis

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 60 * 60 * 24 * 7  # 7 days


def _key(source: str, user_id: str) -> str:
    return f"gateway:lasttask:{(source or 'unknown').lower()}:{user_id}"


async def remember_last_task(source: str, user_id: str, task_id: str,
                             ttl: int = _DEFAULT_TTL) -> None:
    if not source or not user_id or not task_id:
        return
    try:
        r = get_redis()
        await r.setex(_key(source, user_id), ttl, task_id)
    except Exception as e:
        logger.debug(f"[binding] remember failed: {e}")


async def get_last_task(source: str, user_id: str) -> Optional[str]:
    if not source or not user_id:
        return None
    try:
        r = get_redis()
        val = await r.get(_key(source, user_id))
        if not val:
            return None
        if isinstance(val, bytes):
            val = val.decode("utf-8")
        return val
    except Exception as e:
        logger.debug(f"[binding] get failed: {e}")
        return None


async def clear_last_task(source: str, user_id: str) -> None:
    try:
        r = get_redis()
        await r.delete(_key(source, user_id))
    except Exception:
        pass
