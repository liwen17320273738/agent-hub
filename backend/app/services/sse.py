"""
SSE (Server-Sent Events) — Real-time event broadcasting via Redis Pub/Sub.

Unlike the Node version which used in-memory arrays (lost on restart),
this uses Redis Pub/Sub for cross-worker event delivery + asyncio queues
per SSE connection.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator, Dict

from ..redis_client import redis

logger = logging.getLogger(__name__)

CHANNEL = "agenthub:pipeline:events"


async def emit_event(event: str, data: Dict[str, Any]) -> None:
    """Publish a pipeline event to all connected SSE clients via Redis.

    Redis 发布失败时仅记录警告，不向上层抛出异常，避免中断 Pipeline 执行。
    """
    try:
        payload = json.dumps(
            {"event": event, "data": data, "timestamp": time.time()},
            ensure_ascii=False,
            default=str,
        )
        await redis.publish(CHANNEL, payload)
        logger.debug("[sse] emitted %s", event)
    except Exception as exc:
        logger.warning("[sse] emit %s failed (non-fatal): %s", event, exc)


async def event_stream() -> AsyncIterator[str]:
    """Yield SSE-formatted strings for a single client connection.

    连接断开或 Redis 异常时自动重试（最多 3 次），避免异常导致整个生成器崩溃。
    """
    import asyncio

    max_retries = 3
    retry_delay = 1.0

    for attempt in range(max_retries):
        pubsub = redis.pubsub()
        try:
            await pubsub.subscribe(CHANNEL)
            yield f"data: {json.dumps({'event': 'connected', 'timestamp': time.time()})}\n\n"

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                raw = message["data"]
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                yield f"data: {raw}\n\n"
            # pubsub.listen() 正常结束（不会发生），退出重试循环
            break
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning(
                "[sse] event_stream attempt %d/%d failed: %s",
                attempt + 1, max_retries, exc,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
        finally:
            try:
                await pubsub.unsubscribe(CHANNEL)
            except Exception:
                pass
            try:
                await pubsub.close()
            except Exception:
                pass


async def get_sse_client_count() -> int:
    """Approximate subscriber count on the pipeline channel."""
    info = await redis.pubsub_numsub(CHANNEL)
    for ch, count in info:
        if ch == CHANNEL or ch == CHANNEL.encode():
            return count
    return 0
