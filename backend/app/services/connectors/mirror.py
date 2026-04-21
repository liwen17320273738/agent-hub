"""Fan-out helpers that mirror Agent Hub events back to linked issues.

Bridges the bidirectional gap: a ``PipelineTask`` may be linked to one
or more external issues (Jira / GitHub) via
``PipelineTask.external_links``; when something noteworthy happens
(e.g. reviewer rejects → DAG branches back), reviewers should see the
verdict in their *own* queue without having to refresh Agent Hub.

This module is intentionally side-effect-light:

* If the connector for a link's ``kind`` isn't configured, we skip
  that link (return ``ConnectorResult(ok=False, skipped=True)``).
* If a connector raises mid-fan-out, we catch and continue with the
  rest — one bad token shouldn't take down the whole mirror.
* All comment posts run concurrently via ``asyncio.gather`` so a slow
  Jira instance doesn't serialize a fast GitHub.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Iterable, List, Optional

from .base import ConnectorResult, ExternalIssueRef
from .registry import get_connector


logger = logging.getLogger(__name__)


def _normalize_links(raw: Any) -> List[Dict[str, Any]]:
    """Coerce ``PipelineTask.external_links`` to a clean list of dicts.

    Tolerates ``None``, single-dict (legacy), and arbitrary garbage —
    callers shouldn't have to validate before invoking us.
    """
    if not raw:
        return []
    if isinstance(raw, dict):
        # Single-link legacy shape.
        return [raw]
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and item.get("kind") and item.get("key")]


async def mirror_comment_to_links(
    links: Iterable[Dict[str, Any]],
    body: str,
    *,
    only_kinds: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Post ``body`` as a comment to every link in ``links``.

    Returns a list of ``ConnectorResult.to_dict()`` (one per link
    attempted), preserving order. Empty list if there's nothing to do.

    ``only_kinds`` lets the caller restrict the fan-out (e.g. only
    Jira during an outage); when omitted, every kind is attempted.
    """
    normalized = _normalize_links(links)
    if not normalized:
        return []

    kinds_filter = {k.lower() for k in only_kinds} if only_kinds else None

    async def _one(link: Dict[str, Any]) -> Dict[str, Any]:
        kind = str(link.get("kind", "")).lower()
        key = str(link.get("key", ""))
        project = str(link.get("project", ""))
        url = str(link.get("url", ""))

        if kinds_filter and kind not in kinds_filter:
            return ConnectorResult(
                ok=False, kind=kind, skipped=True,
                error=f"kind {kind!r} excluded by only_kinds filter",
            ).to_dict()

        conn = get_connector(kind)
        if conn is None:
            return ConnectorResult(
                ok=False, kind=kind, skipped=True,
                error=f"connector {kind!r} not configured",
            ).to_dict()

        ref = ExternalIssueRef(
            kind=kind, key=key, project=project, url=url,
            id=str(link.get("id", "")),
        )
        try:
            result = await conn.add_comment(ref, body)
            return result.to_dict()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "[mirror] connector %s raised on add_comment(%s): %s",
                kind, key, exc,
            )
            return ConnectorResult(
                ok=False, kind=kind,
                error=f"{type(exc).__name__}: {exc}"[:300],
            ).to_dict()

    # Fan out concurrently. ``return_exceptions=False`` is fine —
    # ``_one`` already swallows everything inside the per-link try.
    return await asyncio.gather(*[_one(l) for l in normalized])
