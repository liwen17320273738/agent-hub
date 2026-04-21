"""Inbound-webhook helpers for issue-tracker comments.

Closes the loop opened by ``mirror.py``: when a reviewer drops a
comment on the linked Jira / GitHub issue ("please retry with X"),
that comment should round-trip back into Agent Hub as an iterate
feedback so the AI can act on it without anyone alt-tabbing.

This module is intentionally protocol-only — payload parsing, secret
verification, dedup. Network I/O (looking up tasks, calling
``feedback_loop.submit_feedback``) lives in the API layer
(``app/api/integrations.py``).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Comments authored by the bot itself look like "[Agent Hub] ..." (see
# ``mirror.py`` and ``escalation.py``). We bounce those to break the
# loop — otherwise our REJECT comment would webhook back, become a
# feedback, trigger another REJECT, and so on.
_SELF_AUTHORED_PREFIX = "[Agent Hub]"


@dataclass
class InboundComment:
    """Normalized comment payload extracted from a webhook body."""

    kind: str            # "jira" | "github"
    issue_key: str       # "AI-7" | "owner/repo#42"
    body: str
    author: str          # "alice@acme.com" | "alice"
    is_self_authored: bool
    raw: Dict[str, Any]


# ─────────────────────────────────────────────────────────────────────
# Signature verification
# ─────────────────────────────────────────────────────────────────────


def verify_github_signature(
    body: bytes,
    signature_header: Optional[str],
    *,
    secret: Optional[str] = None,
) -> bool:
    """Validate ``X-Hub-Signature-256`` per GitHub's spec.

    When no secret is configured (env not set), the verification is
    skipped — but a warning is logged so ops know the endpoint is
    open. In production you almost always want to set the secret.
    """
    secret = secret if secret is not None else os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        logger.warning(
            "[webhook] GITHUB_WEBHOOK_SECRET not set — webhook signature unverified"
        )
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256,
    ).hexdigest()
    given = signature_header.split("=", 1)[1].strip()
    return hmac.compare_digest(expected, given)


def verify_jira_token(
    given_token: Optional[str],
    *,
    secret: Optional[str] = None,
) -> bool:
    """Jira Cloud webhooks don't natively sign, so we use a shared
    bearer token in the URL or X-Jira-Webhook-Token header.

    No secret env set ⇒ open endpoint (logged warning, same trade-off
    as the GitHub side)."""
    secret = secret if secret is not None else os.getenv("JIRA_WEBHOOK_SECRET", "")
    if not secret:
        logger.warning(
            "[webhook] JIRA_WEBHOOK_SECRET not set — webhook auth unverified"
        )
        return True
    if not given_token:
        return False
    return hmac.compare_digest(secret, given_token)


# ─────────────────────────────────────────────────────────────────────
# Payload parsing
# ─────────────────────────────────────────────────────────────────────


def parse_github_issue_comment(payload: Dict[str, Any]) -> Optional[InboundComment]:
    """Normalize a GitHub ``issue_comment`` webhook payload.

    Returns None for events we don't care about (PR comments,
    deletions, edits) — caller should treat None as a benign no-op.
    """
    if not isinstance(payload, dict):
        return None
    if payload.get("action") != "created":
        return None
    issue = payload.get("issue") or {}
    if not isinstance(issue, dict):
        return None
    # GitHub uses the same webhook for issue comments AND pull-request
    # comments. We only handle issue comments here (no ``pull_request``
    # key on the issue object).
    if issue.get("pull_request"):
        return None
    repo = payload.get("repository") or {}
    full_name = repo.get("full_name") or ""
    number = issue.get("number")
    comment = payload.get("comment") or {}
    body = (comment.get("body") or "").strip()
    user = comment.get("user") or {}
    login = user.get("login") or ""
    if not (full_name and number and body):
        return None
    is_self = body.startswith(_SELF_AUTHORED_PREFIX) or (user.get("type") == "Bot")
    return InboundComment(
        kind="github",
        issue_key=f"{full_name}#{number}",
        body=body,
        author=login,
        is_self_authored=is_self,
        raw=payload,
    )


def _adf_to_text(node: Any) -> str:
    """Best-effort flatten Atlassian Document Format → plain text.

    Jira comments arrive as nested ADF; for our purposes (feeding the
    text back into a prompt) a flattened concatenation of ``text``
    nodes is enough — preserves words, drops formatting."""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return node.get("text", "")
    out = []
    for child in node.get("content") or []:
        out.append(_adf_to_text(child))
    sep = "\n" if node.get("type") in ("paragraph", "heading", "doc") else ""
    return sep.join(s for s in out if s)


def parse_jira_comment(payload: Dict[str, Any]) -> Optional[InboundComment]:
    """Normalize a Jira ``comment_created`` webhook payload."""
    if not isinstance(payload, dict):
        return None
    event = payload.get("webhookEvent") or ""
    if event != "comment_created":
        return None
    comment = payload.get("comment") or {}
    issue = payload.get("issue") or {}
    if not isinstance(comment, dict) or not isinstance(issue, dict):
        return None
    issue_key = issue.get("key") or ""
    raw_body = comment.get("body")
    # Jira Cloud sends ADF; Server/DC may send plain text. Handle both.
    if isinstance(raw_body, dict):
        body = _adf_to_text(raw_body).strip()
    else:
        body = (raw_body or "").strip()
    author = comment.get("author") or {}
    author_id = (
        author.get("emailAddress")
        or author.get("displayName")
        or author.get("accountId", "")
    )
    if not (issue_key and body):
        return None
    self_email = (os.getenv("JIRA_EMAIL") or "").lower()
    is_self = bool(
        body.startswith(_SELF_AUTHORED_PREFIX)
        or (self_email and author_id.lower() == self_email)
    )
    return InboundComment(
        kind="jira",
        issue_key=issue_key,
        body=body,
        author=str(author_id),
        is_self_authored=is_self,
        raw=payload,
    )


# ─────────────────────────────────────────────────────────────────────
# Task lookup
# ─────────────────────────────────────────────────────────────────────


def link_matches(link: Dict[str, Any], kind: str, issue_key: str) -> bool:
    """Equality with case-insensitive kind compare; key compared
    exactly (Jira keys are case-sensitive; GitHub repos are not, but
    GitHub returns the canonical-cased ``full_name`` so equality is
    safe in practice)."""
    if not isinstance(link, dict):
        return False
    return (
        str(link.get("kind", "")).lower() == kind.lower()
        and link.get("key") == issue_key
    )


def find_matching_link(
    links: Any, kind: str, issue_key: str,
) -> Optional[Dict[str, Any]]:
    """Walk a task's ``external_links`` and return the first matching
    entry. Tolerant of None / non-list garbage."""
    if not links:
        return None
    if isinstance(links, dict):
        links = [links]
    if not isinstance(links, list):
        return None
    for link in links:
        if link_matches(link, kind, issue_key):
            return link
    return None


def select_tasks_for_inbound(
    tasks: List[Any], kind: str, issue_key: str,
) -> List[Any]:
    """Filter a pre-fetched list of tasks down to those linked to the
    incoming comment's issue. We keep this pure so callers (API or
    background worker) handle the DB roundtrip."""
    return [
        t for t in tasks
        if find_matching_link(getattr(t, "external_links", None), kind, issue_key)
    ]
