"""Per-IM-user pending PLAN session storage (waits for user approval).

Lifecycle:
  1. clarifier finishes → planner produces plan → save_plan(...)
  2. user replies "通过/开干/approve" → load_plan(), clear, run_full_e2e
  3. user replies "修改：xxx" → load_plan(), regenerate plan with feedback,
     save again (rotation_count++)
  4. user replies "取消" → clear_plan
  5. user replies anything else within TTL → treat as new amendment input

State (Redis JSON, TTL ~30 min):
  gateway:plan:<source>:<user_id> = {
    "title":            str,
    "description":      str,           # the clarified description
    "plan":             dict (ExecutionPlan.to_dict()),
    "rotation_count":   int,           # how many times user has asked to revise
    "started_at":       epoch_seconds,
  }
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, Optional

from ..redis_client import get_redis

logger = logging.getLogger(__name__)

DEFAULT_TTL = 30 * 60  # 30 minutes
MAX_ROTATIONS = 3       # cap revisions per requirement


def _key(source: str, user_id: str) -> str:
    return f"gateway:plan:{(source or 'unknown').lower()}:{user_id}"


async def save_plan(source: str, user_id: str, payload: Dict[str, Any]) -> None:
    if not source or not user_id:
        return
    try:
        r = get_redis()
        await r.setex(
            _key(source, user_id),
            DEFAULT_TTL,
            json.dumps(payload, ensure_ascii=False, default=str),
        )
    except Exception as e:
        logger.debug(f"[plan-session] save failed: {e}")


async def load_plan(source: str, user_id: str) -> Optional[Dict[str, Any]]:
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
        logger.debug(f"[plan-session] load failed: {e}")
        return None


async def clear_plan(source: str, user_id: str) -> None:
    if not source or not user_id:
        return
    try:
        r = get_redis()
        await r.delete(_key(source, user_id))
    except Exception:
        pass


def make_payload(title: str, description: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "plan": plan,
        "rotation_count": 0,
        "started_at": time.time(),
    }


async def list_pending(prefix: str = "gateway:plan:") -> list[Dict[str, Any]]:
    """SCAN all pending plan sessions in Redis.

    Returns a list of {source, user_id, key, payload} entries. Empty on any
    Redis failure (caller should treat as "no pending plans").
    """
    out: list[Dict[str, Any]] = []
    try:
        r = get_redis()
        cursor = 0
        # SCAN in chunks until we wrap. cap to ~5k keys to avoid OOM.
        seen = 0
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=f"{prefix}*", count=500)
            for k in keys or []:
                if isinstance(k, bytes):
                    k = k.decode("utf-8")
                rest = k[len(prefix):]
                if ":" not in rest:
                    continue
                source, user_id = rest.split(":", 1)
                try:
                    raw = await r.get(k)
                    if raw is None:
                        continue
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    payload = json.loads(raw)
                except Exception:
                    continue
                out.append({
                    "key": k,
                    "source": source,
                    "user_id": user_id,
                    "payload": payload,
                })
                seen += 1
                if seen >= 5000:
                    return out
            if cursor == 0:
                break
    except Exception as e:
        logger.debug(f"[plan-session] list_pending failed: {e}")
    return out


# ───── intent detection from IM user reply ─────────────────────────

_APPROVE_PATTERNS = (
    "通过", "approve", "approved", "lgtm", "开干", "go", "上",
    "可以", "ok", "好的", "同意", "动手", "执行", "开始", "yes",
)
_CANCEL_PATTERNS = ("取消", "cancel", "停", "不做了", "算了", "abort", "stop")
_REVISE_KEYWORDS = ("修改", "调整", "改成", "改为", "改", "换成", "替换",
                    "加上", "去掉", "加", "增加", "减少", "revise", "edit",
                    "amend", "tweak", "再", "重做")
_REVISE_PATTERN = re.compile(
    r"^\s*(?:修改|调整|改|revise|edit|amend|变更|改成|换成)[：:\s]+(.+)",
    re.IGNORECASE | re.DOTALL,
)


def detect_intent(text: str) -> Dict[str, Any]:
    """Classify a user reply against an active plan.

    Returns one of:
      {"intent": "approve"}
      {"intent": "cancel"}
      {"intent": "revise", "feedback": "..."}
      {"intent": "unknown"}
    """
    raw = (text or "").strip()
    if not raw:
        return {"intent": "unknown"}

    lowered = raw.lower()

    m = _REVISE_PATTERN.match(raw)
    if m:
        return {"intent": "revise", "feedback": m.group(1).strip()}

    for kw in _CANCEL_PATTERNS:
        if kw in lowered:
            return {"intent": "cancel"}

    if any(
        lowered == kw
        or lowered.startswith(kw + " ")
        or lowered.startswith(kw + "，")
        or lowered.startswith(kw + ",")
        for kw in _APPROVE_PATTERNS
    ):
        return {"intent": "approve"}

    if lowered in {"通过", "开干", "approve", "lgtm", "执行"}:
        return {"intent": "approve"}

    if any(kw in raw for kw in _REVISE_KEYWORDS):
        return {"intent": "revise", "feedback": raw}

    if len(raw) >= 5:
        return {"intent": "revise", "feedback": raw}

    return {"intent": "unknown"}
