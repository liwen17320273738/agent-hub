"""Lazy factory + per-process cache for IssueConnector instances.

Keeps construction OUT of import time so missing env vars only matter
for callers that actually use the connector. Tests can override the
cache by calling ``register_connector("jira", FakeJira())``.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .base import IssueConnector
from .github import GitHubConnector
from .jira import JiraConnector

logger = logging.getLogger(__name__)


_CACHE: Dict[str, Optional[IssueConnector]] = {}


def get_connector(kind: str) -> Optional[IssueConnector]:
    """Return a configured connector for ``kind`` or None if the env
    isn't wired up. Result is cached per process — ``register_connector``
    can override for tests."""
    kind = (kind or "").lower().strip()
    if kind in _CACHE:
        return _CACHE[kind]

    instance: Optional[IssueConnector]
    if kind == "jira":
        instance = JiraConnector.from_env()
        if instance is None:
            logger.info("[connectors] jira not configured (set JIRA_BASE_URL/EMAIL/API_TOKEN)")
    elif kind == "github":
        instance = GitHubConnector.from_env()
        if instance is None:
            logger.info("[connectors] github not configured (set GITHUB_TOKEN)")
    else:
        logger.warning("[connectors] unknown connector kind: %r", kind)
        instance = None

    _CACHE[kind] = instance
    return instance


def register_connector(kind: str, connector: Optional[IssueConnector]) -> None:
    """Override the cache. Used by tests to inject fakes; production
    code should rely on ``get_connector(kind)`` reading env."""
    _CACHE[(kind or "").lower().strip()] = connector


def reset_cache() -> None:
    """Clear the cache. Used by tests to force re-resolution from env
    after monkeypatching environment variables."""
    _CACHE.clear()


def available_connectors() -> List[str]:
    """Names of connectors that are currently configured (env present
    or fake registered). Used by ``/api/integrations/healthcheck``
    and the UI."""
    out: List[str] = []
    for kind in ("jira", "github"):
        if get_connector(kind) is not None:
            out.append(kind)
    return out
