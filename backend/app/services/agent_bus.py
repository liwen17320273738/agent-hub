"""Agent message bus — pub/sub for inter-agent collaboration.

Today agents only communicate synchronously through tools (``delegate_to_agent``
or ``deerflow_delegate``). That's request/response only. Wave 4 adds an
asynchronous layer: an agent can ``publish`` a message on a topic and any
other agent can ``wait_for`` matching messages, with optional persistence
for replay/debug.

Implementation sketch:

* **Transport** — Redis pub/sub on a dedicated channel
  ``agenthub:agent:bus``. Falls back to the in-memory pubsub stub when
  Redis is unavailable (same path SSE uses).
* **Persistence** — every published message is also stored in the
  ``agent_messages`` table for `get_recent`-style replay and audit.
* **Filtering** — subscribers filter by ``topic`` (exact match) and
  optionally ``task_id`` / ``sender``.

Use it from agents via the tools registered in ``tools/registry.py``:
``agent_publish`` and ``agent_wait_for``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..redis_client import redis
from ..models.agent_message import AgentMessage

logger = logging.getLogger(__name__)

CHANNEL = "agenthub:agent:bus"


async def publish(
    db: Optional[AsyncSession],
    *,
    topic: str,
    sender: str,
    payload: Dict[str, Any],
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Publish a message to the bus.

    The message is broadcast on Redis pub/sub immediately (subscribers get
    it in real time) and also persisted to ``agent_messages`` when ``db``
    is provided (so late subscribers can fetch via ``get_recent``).
    """
    msg_id = str(uuid.uuid4())
    body = {
        "id": msg_id,
        "topic": topic,
        "sender": sender,
        "task_id": task_id,
        "payload": payload,
        "ts": time.time(),
    }
    try:
        await redis.publish(CHANNEL, json.dumps(body, default=str, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"[agent_bus] redis publish failed: {e}")

    if db is not None:
        try:
            row = AgentMessage(
                id=uuid.UUID(msg_id),
                topic=topic,
                sender=sender,
                task_id=uuid.UUID(task_id) if task_id else None,
                payload=payload,
            )
            db.add(row)
            await db.flush()
        except Exception as e:
            logger.warning(f"[agent_bus] db persist failed: {e}")

    return body


async def wait_for(
    *,
    topic: str,
    timeout: float = 30.0,
    task_id: Optional[str] = None,
    sender: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Block until the next matching message arrives, or until timeout.

    Returns the message dict on success, or None on timeout.
    """
    pubsub = redis.pubsub()
    try:
        await pubsub.subscribe(CHANNEL)
    except Exception as e:
        logger.warning(f"[agent_bus] subscribe failed: {e}")
        return None

    deadline = time.time() + max(0.0, timeout)
    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            try:
                # Both real Redis and the in-memory stub expose .listen();
                # we cap each iteration with wait_for so timeout is honored.
                message = await asyncio.wait_for(_next_message(pubsub), timeout=remaining)
            except asyncio.TimeoutError:
                return None
            if not message or message.get("type") != "message":
                continue
            raw = message.get("data")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                body = json.loads(raw)
            except Exception:
                continue
            if not isinstance(body, dict):
                continue
            if body.get("topic") != topic:
                continue
            if task_id and str(body.get("task_id") or "") != str(task_id):
                continue
            if sender and body.get("sender") != sender:
                continue
            return body
    finally:
        try:
            await pubsub.unsubscribe(CHANNEL)
            await pubsub.close()
        except Exception:
            pass


async def _next_message(pubsub) -> Optional[Dict[str, Any]]:
    """Single-message reader compatible with both real and fallback pubsub."""
    async for m in pubsub.listen():
        return m
    return None


async def get_recent(
    db: AsyncSession,
    *,
    topic: Optional[str] = None,
    task_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Replay-style fetch of recent persisted messages."""
    stmt = select(AgentMessage).order_by(desc(AgentMessage.created_at)).limit(max(1, min(500, limit)))
    if topic:
        stmt = stmt.where(AgentMessage.topic == topic)
    if task_id:
        try:
            stmt = stmt.where(AgentMessage.task_id == uuid.UUID(task_id))
        except Exception:
            pass
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(r.id),
            "topic": r.topic,
            "sender": r.sender,
            "task_id": str(r.task_id) if r.task_id else None,
            "payload": r.payload,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def stream(
    *,
    topic: Optional[str] = None,
    task_id: Optional[str] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Long-lived async generator for an HTTP/SSE consumer."""
    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            raw = message.get("data")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                body = json.loads(raw)
            except Exception:
                continue
            if topic and body.get("topic") != topic:
                continue
            if task_id and str(body.get("task_id") or "") != str(task_id):
                continue
            yield body
    finally:
        try:
            await pubsub.unsubscribe(CHANNEL)
            await pubsub.close()
        except Exception:
            pass
