"""Jira Cloud connector.

Implements the ``IssueConnector`` protocol against the Jira Cloud
REST API v3 (``/rest/api/3``). Uses Atlassian's documented
"email + API token" Basic auth scheme — no OAuth flow required for
the Day-0 use case (server-to-server, single workspace).

Environment / settings
======================
Required:

* ``JIRA_BASE_URL``   — e.g. ``https://acme.atlassian.net``
* ``JIRA_EMAIL``      — login email of the bot user
* ``JIRA_API_TOKEN``  — Atlassian-generated token

Optional:

* ``JIRA_DEFAULT_PROJECT``   — default project key (e.g. ``AI``)
                                used when caller doesn't specify one
* ``JIRA_DEFAULT_ISSUE_TYPE`` — default issue type (default ``Story``)

When required vars are missing, every method returns
``ConnectorResult(skipped=True)`` — same contract as the IM adapters.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from .base import (
    ConnectorResult,
    ExternalCommentRef,
    ExternalIssueRef,
    IssueConnector,
)

logger = logging.getLogger(__name__)


_API_TIMEOUT = 15.0  # seconds — Jira Cloud is usually fast but we don't want to hang the pipeline


def _basic_auth(email: str, token: str) -> str:
    raw = f"{email}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _adf_doc(text: str) -> Dict[str, Any]:
    """Wrap plain text in Atlassian Document Format (the required
    body shape for Jira v3 description / comment fields).

    We only emit a single paragraph block — sufficient for our use
    case (PRD body, REJECT comment) and avoids the complexity of
    converting Markdown → ADF nodes. Newlines in the source become
    paragraph breaks.
    """
    paragraphs = (text or "").split("\n\n")
    content = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        content.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": p}],
        })
    if not content:
        content = [{"type": "paragraph", "content": [{"type": "text", "text": " "}]}]
    return {"type": "doc", "version": 1, "content": content}


class JiraConnector:
    """Jira Cloud REST v3 connector. Stateless — safe to share across
    coroutines; ``httpx.AsyncClient`` is created per call to avoid
    pinning a connection pool to one event loop (we have a small
    request volume, not worth optimising)."""

    kind = "jira"

    def __init__(
        self,
        base_url: str,
        email: str,
        token: str,
        default_project: Optional[str] = None,
        default_issue_type: str = "Story",
    ):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.token = token
        self.default_project = default_project
        self.default_issue_type = default_issue_type or "Story"
        self._auth_header = _basic_auth(email, token)

    @classmethod
    def from_env(cls) -> Optional["JiraConnector"]:
        """Build from environment. Returns None if any required var
        is missing — caller treats this as "Jira not configured"."""
        base = os.getenv("JIRA_BASE_URL")
        email = os.getenv("JIRA_EMAIL")
        token = os.getenv("JIRA_API_TOKEN")
        if not (base and email and token):
            return None
        return cls(
            base_url=base,
            email=email,
            token=token,
            default_project=os.getenv("JIRA_DEFAULT_PROJECT") or None,
            default_issue_type=os.getenv("JIRA_DEFAULT_ISSUE_TYPE") or "Story",
        )

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": self._auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def healthcheck(self) -> ConnectorResult:
        try:
            async with httpx.AsyncClient(timeout=_API_TIMEOUT) as c:
                r = await c.get(
                    f"{self.base_url}/rest/api/3/myself",
                    headers=self._headers(),
                )
            if r.status_code == 200:
                return ConnectorResult(ok=True, kind=self.kind)
            return ConnectorResult(
                ok=False, kind=self.kind,
                error=f"healthcheck HTTP {r.status_code}: {r.text[:200]}",
            )
        except Exception as exc:
            return ConnectorResult(ok=False, kind=self.kind, error=str(exc))

    async def create_issue(
        self,
        *,
        title: str,
        body: str,
        labels: Optional[List[str]] = None,
        assignee: Optional[str] = None,
        project: Optional[str] = None,
        extras: Optional[Dict[str, Any]] = None,
    ) -> ConnectorResult:
        proj = project or self.default_project
        if not proj:
            return ConnectorResult(
                ok=False, kind=self.kind, skipped=True,
                error="no project key (set JIRA_DEFAULT_PROJECT or pass project=)",
            )

        # Trim title — Jira allows up to 255 chars in summary.
        summary = (title or "Untitled task")[:250]

        payload: Dict[str, Any] = {
            "fields": {
                "project": {"key": proj},
                "summary": summary,
                "issuetype": {"name": (extras or {}).get("issue_type") or self.default_issue_type},
                "description": _adf_doc(body),
            }
        }
        if labels:
            payload["fields"]["labels"] = list(labels)
        if assignee:
            # Atlassian deprecated ``name`` → ``accountId``; we accept
            # whatever the caller passes and let Jira validate.
            payload["fields"]["assignee"] = {"accountId": assignee}

        try:
            async with httpx.AsyncClient(timeout=_API_TIMEOUT) as c:
                r = await c.post(
                    f"{self.base_url}/rest/api/3/issue",
                    headers=self._headers(),
                    json=payload,
                )
            if r.status_code in (200, 201):
                data = r.json()
                key = data.get("key", "")
                issue_id = str(data.get("id", ""))
                ref = ExternalIssueRef(
                    kind=self.kind, key=key, id=issue_id,
                    project=proj,
                    url=f"{self.base_url}/browse/{key}",
                    raw={"self": data.get("self", "")},
                )
                return ConnectorResult(ok=True, kind=self.kind, issue=ref)
            return ConnectorResult(
                ok=False, kind=self.kind,
                error=f"create_issue HTTP {r.status_code}: {r.text[:300]}",
            )
        except Exception as exc:
            return ConnectorResult(ok=False, kind=self.kind, error=str(exc))

    async def add_labels(
        self, ref: ExternalIssueRef, labels: List[str],
    ) -> ConnectorResult:
        """Append labels to an existing issue (idempotent — Jira de-dupes
        on its side). Used by the escalation throttle to mark issues
        the AI couldn't resolve after N rejects.

        Uses Jira's standard ``update.labels.add`` operation so we
        don't have to GET-modify-PUT the full label list.
        """
        if not ref or not ref.key:
            return ConnectorResult(
                ok=False, kind=self.kind, skipped=True,
                error="missing issue ref",
            )
        if not labels:
            return ConnectorResult(ok=True, kind=self.kind, skipped=True,
                                   error="no labels to add")
        payload = {
            "update": {
                "labels": [{"add": label} for label in labels],
            }
        }
        try:
            async with httpx.AsyncClient(timeout=_API_TIMEOUT) as c:
                r = await c.put(
                    f"{self.base_url}/rest/api/3/issue/{ref.key}",
                    headers=self._headers(),
                    json=payload,
                )
            if r.status_code in (200, 204):
                return ConnectorResult(ok=True, kind=self.kind)
            return ConnectorResult(
                ok=False, kind=self.kind,
                error=f"add_labels HTTP {r.status_code}: {r.text[:300]}",
            )
        except Exception as exc:
            return ConnectorResult(ok=False, kind=self.kind, error=str(exc))

    async def add_comment(
        self, ref: ExternalIssueRef, body: str,
    ) -> ConnectorResult:
        if not ref or not ref.key:
            return ConnectorResult(
                ok=False, kind=self.kind, skipped=True,
                error="missing issue ref",
            )
        payload = {"body": _adf_doc(body)}
        try:
            async with httpx.AsyncClient(timeout=_API_TIMEOUT) as c:
                r = await c.post(
                    f"{self.base_url}/rest/api/3/issue/{ref.key}/comment",
                    headers=self._headers(),
                    json=payload,
                )
            if r.status_code in (200, 201):
                data = r.json()
                cref = ExternalCommentRef(
                    kind=self.kind,
                    issue_key=ref.key,
                    comment_id=str(data.get("id", "")),
                    url=f"{self.base_url}/browse/{ref.key}?focusedCommentId={data.get('id', '')}",
                )
                return ConnectorResult(ok=True, kind=self.kind, comment=cref)
            return ConnectorResult(
                ok=False, kind=self.kind,
                error=f"add_comment HTTP {r.status_code}: {r.text[:300]}",
            )
        except Exception as exc:
            return ConnectorResult(ok=False, kind=self.kind, error=str(exc))


# Runtime check: ensure JiraConnector satisfies the protocol.
_: IssueConnector = JiraConnector(  # type: ignore[abstract]
    base_url="https://example.atlassian.net",
    email="x@x.com", token="x",
)
