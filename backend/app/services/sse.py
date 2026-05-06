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
    """Publish a pipeline event to all connected SSE clients via Redis."""
    payload = json.dumps(
        {"event": event, "data": data, "timestamp": time.time()},
        ensure_ascii=False,
        default=str,
    )
    await redis.publish(CHANNEL, payload)
    logger.debug(f"[sse] emitted {event}")


async def event_stream() -> AsyncIterator[str]:
    """Yield SSE-formatted strings for a single client connection."""
    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL)

    try:
        yield f"data: {json.dumps({'event': 'connected', 'timestamp': time.time()})}\n\n"
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            raw = message["data"]
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            yield f"data: {raw}\n\n"
    finally:
        await pubsub.unsubscribe(CHANNEL)
        await pubsub.close()


async def get_sse_client_count() -> int:
    """Approximate subscriber count on the pipeline channel."""
    info = await redis.pubsub_numsub(CHANNEL)
    for ch, count in info:
        if ch == CHANNEL or ch == CHANNEL.encode():
            return count
    return 0
