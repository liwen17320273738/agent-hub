"""Per-IM-user pending clarifier session storage.

When a user sends an under-specified requirement (e.g. just "做个 todo"),
we don't create a `PipelineTask` immediately. Instead we ask 1-2 follow-up
questions and accumulate answers across messages.

State (Redis hash, TTL ~1h):
  gateway:pending:<source>:<user_id> = {
    "messages":      [user message strings, FIFO],
    "asked_count":   int,            # number of clarifier rounds spent
    "questions":     [last questions asked],
    "title_hint":    str,            # extracted title (1st message)
    "started_at":    epoch_seconds,
  }
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from ..redis_client import get_redis

logger = logging.getLogger(__name__)

DEFAULT_TTL = 60 * 60  # 1 hour
MAX_ROUNDS = 2          # cap clarifier questions to avoid loops


def _key(source: str, user_id: str) -> str:
    return f"gateway:pending:{(source or 'unknown').lower()}:{user_id}"


async def get_session(source: str, user_id: str) -> Optional[Dict[str, Any]]:
    if not source or not user_id:
        return None
    try:
        r = get_redis()
        raw = await r.get(_key(source, user_id))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except Exception as e:
        logger.debug(f"[clarifier-session] get failed: {e}")
        return None


async def save_session(source: str, user_id: str, session: Dict[str, Any]) -> None:
    if not source or not user_id:
        return
    try:
        r = get_redis()
        await r.setex(
            _key(source, user_id),
            DEFAULT_TTL,
            json.dumps(session, ensure_ascii=False, default=str),
        )
    except Exception as e:
        logger.debug(f"[clarifier-session] save failed: {e}")


async def clear_session(source: str, user_id: str) -> None:
    if not source or not user_id:
        return
    try:
        r = get_redis()
        await r.delete(_key(source, user_id))
    except Exception:
        pass


def append_message(session: Optional[Dict[str, Any]], text: str) -> Dict[str, Any]:
    """Add a user message and return the updated session dict."""
    sess = session or {
        "messages": [],
        "asked_count": 0,
        "questions": [],
        "title_hint": "",
        "started_at": time.time(),
    }
    msgs: List[str] = list(sess.get("messages") or [])
    msgs.append(text.strip())
    sess["messages"] = msgs
    if not sess.get("title_hint"):
        sess["title_hint"] = text.strip()[:80]
    return sess


def merged_description(session: Dict[str, Any]) -> str:
    """Concatenate all collected user messages with their order preserved."""
    msgs: List[str] = list(session.get("messages") or [])
    if not msgs:
        return ""
    if len(msgs) == 1:
        return msgs[0]
    parts = [f"### 初始需求\n{msgs[0]}"]
    for i, m in enumerate(msgs[1:], start=1):
        parts.append(f"### 补充 {i}\n{m}")
    return "\n\n".join(parts)
