"""
SSE → IM Notify Bridge

Subscribes to the SSE Redis Pub/Sub channel and forwards failure/error events
to the originating IM platform for any task with an IM source (feishu, qq, slack, wechat).

This ensures that even when errors fire from outside the E2E orchestrator
(e.g. pipeline_engine), the IM user still receives a notification.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from ...models.pipeline import PipelineTask
from ..sse import CHANNEL as SSE_CHANNEL
from .dispatcher import notify_task_event

logger = logging.getLogger(__name__)

# Map of SSE event → notify event metadata
_EVENT_MAP: Dict[str, Dict[str, Any]] = {
    "pipeline:auto-error": {"event": "failed", "key": "error", "fallback": "流水线执行异常"},
    "pipeline:smart-error": {"event": "failed", "key": "error", "fallback": "智能执行异常"},
    "stage:error": {"event": "failed", "key": "error", "fallback": "阶段执行错误"},
    "e2e:failed": {"event": "failed", "key": "error", "fallback": "E2E 全流程失败"},
    "e2e:contract-blocked": {"event": "failed", "key": "summary", "fallback": "交付物验证未通过"},
    "e2e:build-failed": {"event": "progress", "key": "error", "fallback": "构建失败"},
}


async def _get_channel_session() -> Any:
    """Import lazily to avoid circular imports and sync issues."""
    from ...database import async_session_factory
    return async_session_factory


async def bridge_event_to_im(event: str, data: Dict[str, Any]) -> None:
    """Route a single SSE event to IM notification if applicable.

    Called from the bridge background task for each event on the SSE channel.
    """
    mapping = _EVENT_MAP.get(event)
    if mapping is None:
        return  # Not an event we bridge

    task_id = data.get("taskId") or (data.get("task", {}) or {}).get("id")
    if not task_id:
        return

    error_text: str = data.get(mapping["key"]) or mapping["fallback"]
    if isinstance(error_text, (list, dict)):
        error_text = str(error_text)[:300]

    session_factory = _get_channel_session()
    try:
        async with session_factory() as db:
            import uuid
            try:
                uid = uuid.UUID(task_id) if isinstance(task_id, str) and not task_id.startswith("e2e:") else None
            except (ValueError, AttributeError):
                uid = None
            if uid is None:
                return

            task = await db.get(PipelineTask, uid)
            if task is None:
                return

            # Only bridge for IM-originated tasks
            if task.source not in ("feishu", "qq", "slack", "wechat"):
                return

            extras: Dict[str, Any] = {}
            if data.get("phase"):
                extras["阶段"] = data["phase"]
            if data.get("attempt"):
                extras["尝试次数"] = f"{data['attempt']}/{data.get('maxRetries', '?')}"
            if data.get("reason"):
                extras["原因"] = data["reason"]

            await notify_task_event(
                task,
                event=mapping["event"],
                message=error_text[:500],
                extras=extras or None,
            )
    except Exception as e:
        logger.warning("[sse-notify-bridge] Error bridging %s for task %s: %s", event, task_id, e)


async def run_sse_notify_bridge() -> None:
    """Background coroutine: listen to SSE Redis channel and bridge events to IM.

    Intended to be launched as a background asyncio task during lifespan startup.
    """
    from ...redis_client import redis as _redis

    logger.info("[sse-notify-bridge] Starting SSE→IM notify bridge")

    pubsub = _redis.pubsub()
    try:
        await pubsub.subscribe(SSE_CHANNEL)
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            raw = message["data"]
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            try:
                parsed = json.loads(raw)
                event: str = parsed.get("event", "")
                ev_data: Dict[str, Any] = parsed.get("data", {})
                if event:
                    await bridge_event_to_im(event, ev_data)
            except (json.JSONDecodeError, KeyError):
                continue
    except Exception as e:
        logger.error("[sse-notify-bridge] Fatal error: %s", e, exc_info=True)
    finally:
        try:
            await pubsub.unsubscribe(SSE_CHANNEL)
            await pubsub.close()
        except Exception:
            pass
        logger.info("[sse-notify-bridge] Stopped")
