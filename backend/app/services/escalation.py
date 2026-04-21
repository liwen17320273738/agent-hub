"""Throttled escalation when the AI keeps failing review.

The auto-mirror in ``connectors/mirror.py`` posts a comment to every
linked Jira / GitHub issue *every* time a stage is rejected. Useful
once or twice; noise after the third try, and worse, gives reviewers
no signal that "this one isn't getting unstuck on its own".

This module adds the missing escalation:

* When ``reject_count`` for a stage crosses
  ``REJECT_ESCALATION_THRESHOLD`` (default 3) — i.e. after the 3rd
  rejection on the same stage — we:
    1. Add a fixed label (default ``ai-stuck-needs-human``) to every
       linked external issue, so the human triage queue can filter
       "AI gave up here".
    2. Post a louder, distinct comment so the escalation event is
       visually separate from the per-cycle REJECT comments.
    3. Send an IM notification (via ``notify_task_event``) to the
       channel that originated the task.

Throttling
==========
We only escalate on each *new* high-water-mark of ``reject_count``
(i.e. once per crossing). A second call with the same or lower
``reject_count`` is a no-op so a transient retry storm doesn't
re-spam the tracker.

Cross-worker dedup
==================
Throttle uses Redis ``SET key value NX EX 86400`` keyed on
``escalation:reject:{task_id}:{reject_count}`` — atomic across all
gunicorn workers, falls open on Redis outage so an outage doesn't
suppress legitimate escalations. A 24h TTL is enough for any single
DAG run; older keys auto-expire so the keyspace stays bounded.

Per-process ``_ESCALATED`` is kept as a 2nd-level guard (cheap
in-memory short-circuit before we round-trip to Redis), but the
**source of truth** is Redis.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .dedup import claim_dedup_token


logger = logging.getLogger(__name__)


# Local short-circuit cache — saves a Redis round trip when the same
# worker just escalated this exact (task, count). Real authority lives
# in Redis (see ``claim_dedup_token``), so an evicted entry here just
# means "ask Redis again".
_ESCALATED: Dict[str, int] = {}

# Dedup key TTL (seconds). 24h covers any reasonable DAG run; older
# (task, count) pairs naturally expire so the keyspace stays bounded.
_ESCALATION_DEDUP_TTL = 24 * 3600


def _threshold() -> int:
    raw = os.getenv("REJECT_ESCALATION_THRESHOLD", "3")
    try:
        n = int(raw)
        return n if n >= 1 else 3
    except (TypeError, ValueError):
        return 3


def _label() -> str:
    return os.getenv("REJECT_ESCALATION_LABEL", "ai-stuck-needs-human")


def reset_escalation_state(task_id: Optional[str] = None) -> None:
    """Sync test hook + admin escape valve. Clears the local
    in-memory short-circuit ONLY. For full cross-process clearing
    (including Redis dedup tokens), use :func:`aclear_escalation_state`
    — required from async tests because purging real Redis is async.
    """
    if task_id is None:
        _ESCALATED.clear()
    else:
        _ESCALATED.pop(task_id, None)

    # Best-effort fallback purge (in-memory Redis stub). Real Redis
    # is left alone — see ``aclear_escalation_state`` for that.
    try:
        from ..redis_client import _memory_store, _memory_expiry
        prefix = "escalation:reject:"
        for k in list(_memory_store.keys()):
            if not (isinstance(k, str) and k.startswith(prefix)):
                continue
            if task_id is None or f":{task_id}:" in k:
                _memory_store.pop(k, None)
                _memory_expiry.pop(k, None)
    except Exception:  # pragma: no cover - defensive
        pass


async def aclear_escalation_state(task_id: Optional[str] = None) -> None:
    """Async cousin of :func:`reset_escalation_state` that ALSO purges
    the Redis dedup tokens (``escalation:reject:{task_id}:*``).

    Tests MUST use this in async fixtures, otherwise the 24h TTL on
    dedup keys carries state across test runs (when pointed at a
    real Redis) and ``maybe_escalate`` silently no-ops.
    """
    reset_escalation_state(task_id)
    try:
        from ..redis_client import get_redis
        r = get_redis()
        scan = getattr(r, "scan_iter", None)
        if scan is None:
            return
        prefix = "escalation:reject:"
        pattern = f"{prefix}{task_id}:*" if task_id else f"{prefix}*"
        async for k in r.scan_iter(match=pattern):
            try:
                await r.delete(k)
            except Exception:
                pass
    except Exception:  # pragma: no cover - defensive
        pass


async def _fan_out_labels(
    links: Iterable[Dict[str, Any]],
    labels: List[str],
) -> List[Dict[str, Any]]:
    """Best-effort per-link label add. Connectors without
    ``add_labels`` (or unconfigured) are reported as skipped."""
    from .connectors import get_connector
    from .connectors.base import ConnectorResult, ExternalIssueRef

    results: List[Dict[str, Any]] = []
    for link in links:
        if not isinstance(link, dict):
            continue
        kind = str(link.get("kind", "")).lower()
        key = str(link.get("key", ""))
        if not kind or not key:
            continue
        conn = get_connector(kind)
        if conn is None:
            results.append(ConnectorResult(
                ok=False, kind=kind, skipped=True,
                error="connector not configured",
            ).to_dict())
            continue
        add_labels = getattr(conn, "add_labels", None)
        if add_labels is None:
            results.append(ConnectorResult(
                ok=False, kind=kind, skipped=True,
                error="connector does not support add_labels",
            ).to_dict())
            continue
        ref = ExternalIssueRef(
            kind=kind, key=key,
            project=str(link.get("project", "")),
            url=str(link.get("url", "")),
            id=str(link.get("id", "")),
        )
        try:
            res = await add_labels(ref, labels)
            results.append(res.to_dict())
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[escalate] add_labels(%s) raised: %s", kind, exc)
            results.append(ConnectorResult(
                ok=False, kind=kind,
                error=f"{type(exc).__name__}: {exc}"[:300],
            ).to_dict())
    return results


def _escalation_comment(
    *,
    task_title: str,
    task_id: str,
    target: str,
    reject_count: int,
    threshold: int,
    label: str,
) -> str:
    """Distinct comment shape so reviewers can tell escalation apart
    from the per-cycle REJECT comments at a glance."""
    return (
        f"[Agent Hub] 🚨 自动升级（连续 {reject_count} 次驳回，阈值 {threshold}）\n\n"
        f"**任务**: {task_title}\n"
        f"**Task ID**: {task_id}\n"
        f"**当前卡在阶段**: `{target}`\n"
        f"**已添加 label**: `{label}`\n\n"
        f"AI 多次返工仍未通过评审，已暂停自动迭代，请人工介入排查。"
    )


async def maybe_escalate(
    db: AsyncSession,
    *,
    task_id: str,
    task_title: str,
    target_stage: str,
    reject_count: int,
    links: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Escalate iff (a) reject_count crosses the threshold AND (b) we
    haven't already escalated at this or higher count. Returns a
    summary dict on fire, ``None`` otherwise.

    Caller (DAG REJECT path) is expected to invoke this every cycle —
    we own the throttle.
    """
    threshold = _threshold()
    if reject_count < threshold:
        return None

    # Local short-circuit — saves one Redis round trip when the same
    # worker just handled this exact (task, count). We still defer to
    # Redis as the cross-worker authority below.
    last = _ESCALATED.get(task_id, 0)
    if reject_count <= last:
        return None

    # Cross-worker dedup. Returns False if any worker (including this
    # one across restarts) already claimed this (task, count) within
    # the TTL window — that worker fired the escalation, this one
    # should stay quiet.
    claimed = await claim_dedup_token(
        f"escalation:reject:{task_id}:{reject_count}",
        ttl_seconds=_ESCALATION_DEDUP_TTL,
        value=str(reject_count),
    )
    if not claimed:
        # Update the local cache anyway so we don't keep round-tripping
        # to Redis for the same (task, count).
        _ESCALATED[task_id] = max(_ESCALATED.get(task_id, 0), reject_count)
        return None

    _ESCALATED[task_id] = reject_count

    label = _label()
    label_results = await _fan_out_labels(links or [], [label])

    # Lazy import to avoid pulling httpx into pure-DAG unit tests
    # that never hit the connector code path.
    from .connectors import mirror_comment_to_links

    comment_body = _escalation_comment(
        task_title=task_title,
        task_id=task_id,
        target=target_stage,
        reject_count=reject_count,
        threshold=threshold,
        label=label,
    )
    comment_results = await mirror_comment_to_links(links or [], comment_body)

    # IM notification — best-effort. Lazy-load the task row + the
    # notify dispatcher so a missing channel config doesn't crash
    # the DAG.
    notify_result: Optional[Dict[str, Any]] = None
    try:
        from ..models.pipeline import PipelineTask
        from .notify.dispatcher import notify_task_event

        task_row = await db.get(PipelineTask, uuid.UUID(task_id))
        if task_row is not None:
            res = await notify_task_event(
                task_row,
                event="auto_paused",
                message=(
                    f"已升级：阶段 `{target_stage}` 第 {reject_count} 次评审驳回 "
                    f"(阈值 {threshold})；已加 label `{label}` + 暂停自动迭代。"
                ),
            )
            notify_result = res.to_dict()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[escalate] IM notify failed for %s: %s", task_id, exc)
        notify_result = {"ok": False, "error": str(exc)[:300]}

    return {
        "taskId": task_id,
        "target": target_stage,
        "rejectCount": reject_count,
        "threshold": threshold,
        "label": label,
        "labelResults": label_results,
        "commentResults": comment_results,
        "notify": notify_result,
    }
