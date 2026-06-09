"""
SSE (Server-Sent Events) — Real-time event broadcasting via Redis Pub/Sub.

Unlike the Node version which used in-memory arrays (lost on restart),
this uses Redis Pub/Sub for cross-worker event delivery + asyncio queues
per SSE connection.

Event bridging
==============
To give the frontend swimlane a unified view, the ``lead-agent`` path
(``subtask:*`` / ``pipeline:smart-*`` / ``lead-agent:*``) is bridged into
``e2e:phase`` events, because the frontend has no direct handler for them.

- **Gateway e2e** (``run_full_e2e``) emits ``e2e:*`` directly.
- **smart-run** emits ``subtask:*`` / ``pipeline:smart-*`` which
  ``emit_event`` translates to ``e2e:phase`` — identical swimlane UX.
- **dag-run / auto-run** emit ``stage:*`` which the frontend handles
  directly; these are NOT bridged (bridging would double the entries).
"""
from __future__ import annotations

import contextvars
import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from ..redis_client import redis

logger = logging.getLogger(__name__)

CHANNEL = "agenthub:pipeline:events"

# When True in the current async context, the stage→e2e bridge is suppressed.
# The gateway ``run_full_e2e`` sets this because it already emits its own
# rich ``e2e:*`` events; bridging the internal ``stage:*`` would duplicate them.
_suppress_e2e_bridge: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "suppress_e2e_bridge", default=False
)


def suppress_e2e_bridge() -> "contextvars.Token[bool]":
    """Suppress stage→e2e bridging for the current async context.

    Returns a token; pass it to :func:`restore_e2e_bridge` to undo.
    """
    return _suppress_e2e_bridge.set(True)


def restore_e2e_bridge(token: "contextvars.Token[bool]") -> None:
    try:
        _suppress_e2e_bridge.reset(token)
    except (ValueError, LookupError):
        pass

# Known stage IDs mapped to human-readable swimlane phases.
# Unmatched stages fall back to the stage_id itself.
_STAGE_TO_PHASE: Dict[str, str] = {
    "planning": "design-pipeline",
    "development:planning": "design-pipeline",
    "development": "codegen",
    "testing": "build-test",
    "deployment": "deploy",
    "reviewing": "acceptance",
}


def _stage_event_to_e2e(event: str, data: Dict[str, Any]) -> Optional[tuple[str, dict]]:
    """Translate a lead-agent / smart-pipeline event into an ``e2e:*`` event.

    Only the ``lead_agent`` path (smart-run) is bridged here — it emits
    ``subtask:*`` / ``pipeline:smart-*`` / ``lead-agent:*`` events that the
    frontend has no direct handler for.

    ``stage:*`` events are deliberately NOT bridged: the frontend already
    handles ``stage:processing`` / ``stage:completed`` / ``stage:error``
    directly, so bridging them here would produce duplicate swimlane entries
    for the ``execute_stage`` paths (auto-run / dag-run / gateway internals).

    Returns ``(e2e_event, e2e_data)`` or ``None`` (no bridge needed).
    """
    task_id = data.get("taskId") or data.get("task_id") or ""
    if not task_id:
        return None

    # ── Lead-agent / smart pipeline events ──
    if event.startswith("pipeline:smart-"):
        suffix = event[len("pipeline:smart-"):]
        if suffix == "start":
            return ("e2e:start", {"taskId": task_id, "title": data.get("title", "")})
        # smart-completed → e2e:complete
        if suffix == "completed":
            return ("e2e:complete", {"taskId": task_id, "url": "", "summary": "smart-run 完成"})
        return None

    if event == "lead-agent:plan-ready":
        # Plan ready → design-pipeline phase done
        return ("e2e:phase", {
            "taskId": task_id,
            "phase": "design-pipeline",
            "status": "done",
        })

    if event == "lead-agent:error":
        return ("e2e:failed", {
            "taskId": task_id,
            "phase": "design-pipeline",
            "error": data.get("error", ""),
        })

    # subtask events → codegen / build phases
    if event.startswith("subtask"):
        subtask_stage = data.get("stageId", "development")
        phase = _STAGE_TO_PHASE.get(subtask_stage, subtask_stage)
        if event == "subtask:start":
            return ("e2e:phase", {"taskId": task_id, "phase": phase, "status": "running"})
        if event in ("subtask:completed",):
            return ("e2e:phase", {"taskId": task_id, "phase": phase, "status": "done"})
        if event == "subtask:failed":
            return ("e2e:phase", {"taskId": task_id, "phase": phase, "status": "failed"})
        return None

    return None


async def emit_event(event: str, data: Dict[str, Any]) -> None:
    """Publish a pipeline event to all connected SSE clients via Redis.

    Bridges the ``lead-agent`` path (``subtask:*`` / ``pipeline:smart-*`` /
    ``lead-agent:*``) into ``e2e:*`` so smart-run renders in the swimlane.
    ``stage:*`` is handled by the frontend directly and is NOT bridged.

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

        # ▸ Event bridge: lead-agent (subtask:/pipeline:smart-/lead-agent:) → e2e:*
        # Skip when already inside a gateway e2e run (it emits its own e2e:*).
        bridge = None if _suppress_e2e_bridge.get() else _stage_event_to_e2e(event, data)
        if bridge is not None:
            e2e_event, e2e_data = bridge
            try:
                bridge_payload = json.dumps(
                    {"event": e2e_event, "data": e2e_data, "timestamp": time.time()},
                    ensure_ascii=False,
                    default=str,
                )
                await redis.publish(CHANNEL, bridge_payload)
                logger.debug("[sse] bridge %s → %s", event, e2e_event)
            except Exception as exc:
                logger.warning("[sse] bridge emit %s failed (non-fatal): %s", e2e_event, exc)
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
            # EventSourceResponse frames each yielded str as the SSE `data:`
            # field itself — so yield the bare JSON payload. Pre-formatting with
            # "data: ...\n\n" here caused a double `data: data: {...}` prefix,
            # which made every client-side JSON.parse(e.data) throw and silently
            # drop every event (the live UI looked permanently frozen).
            yield json.dumps({"event": "connected", "timestamp": time.time()})

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                raw = message["data"]
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                yield raw
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


def chunk_text_for_sse(text: str, chunk_size: int = 120) -> List[str]:
    """Split completed LLM text into SSE-sized slices for synthetic streaming."""
    if not text:
        return []
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]


async def emit_synthetic_output_stream(
    *,
    task_id: Any,
    stage_id: str,
    content: str,
    model: str = "",
) -> int:
    """Emit output-start/chunk/end for a completed non-streaming LLM response.

    Used when ``chat_completion_stream`` fails or returns empty — the UI still
    gets a typing effect instead of a silent multi-minute wait.
    """
    text = content or ""
    await emit_event("stage:output-start", {
        "taskId": task_id,
        "stageId": stage_id,
        "model": model,
        "synthetic": True,
    })
    if not text.strip():
        await emit_event("stage:output-end", {
            "taskId": task_id,
            "stageId": stage_id,
            "totalChunks": 0,
            "length": 0,
            "synthetic": True,
        })
        return 0

    chunk_count = 0
    for piece in chunk_text_for_sse(text):
        chunk_count += 1
        await emit_event("stage:output-chunk", {
            "taskId": task_id,
            "stageId": stage_id,
            "text": piece,
            "chunkIndex": chunk_count,
            "synthetic": True,
        })
    await emit_event("stage:output-end", {
        "taskId": task_id,
        "stageId": stage_id,
        "totalChunks": chunk_count,
        "length": len(text),
        "synthetic": True,
    })
    return chunk_count


async def get_sse_client_count() -> int:
    """Approximate subscriber count on the pipeline channel."""
    info = await redis.pubsub_numsub(CHANNEL)
    for ch, count in info:
        if ch == CHANNEL or ch == CHANNEL.encode():
            return count
    return 0
