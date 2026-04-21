"""Bidirectional connectors for external issue trackers (Jira, GitHub).

Goal
====
Right now the AI Legion ships task progress to chat channels (Slack /
Feishu / QQ) but is **blind** to the issue trackers people actually
plan work in. This package adds a thin, uniform interface for:

* **Pushing out** — turn a generated PRD into a Jira story or GitHub
  Issue when the task is created; mirror REJECT events as comments
  back to that issue so reviewers see the AI's verdict in their
  normal queue.
* **Pulling in** (future) — accept webhook callbacks from those
  systems so a comment on the linked issue can trigger an
  ``iterate`` event on the matching task.

Design
======
Every connector implements ``IssueConnector`` (see ``base.py``):

  * ``create_issue(title, body, labels, assignee, ...)`` →
    ``ExternalIssueRef``
  * ``add_comment(ref, body)`` → ``ExternalCommentRef``
  * ``healthcheck()`` — verify auth + reachability (used by
    ``/api/integrations/healthcheck``)

Implementations are kept thin, tolerant of missing config (return
``skipped`` results — same contract as the IM adapters), and use
``httpx.AsyncClient`` for transport so they don't block the event loop.

Public API
==========
* ``get_connector(kind)`` — factory; returns a configured connector
  for "jira" or "github", or ``None`` if not configured.
* ``available_connectors()`` — list of configured connector kinds
  (used by the integrations health endpoint and the UI).
* ``IssueConnector`` / ``ExternalIssueRef`` / ``ExternalCommentRef``
  — base types.
"""
from __future__ import annotations

from .base import (
    IssueConnector,
    ExternalIssueRef,
    ExternalCommentRef,
    ConnectorResult,
)
from .registry import get_connector, available_connectors
from .mirror import mirror_comment_to_links

__all__ = [
    "IssueConnector",
    "ExternalIssueRef",
    "ExternalCommentRef",
    "ConnectorResult",
    "get_connector",
    "available_connectors",
    "mirror_comment_to_links",
]
