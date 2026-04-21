"""GitHub Issues connector.

Implements the ``IssueConnector`` protocol against the GitHub REST
API v3 (``api.github.com``). Uses a fine-grained personal access
token for the Day-0 use case (server-to-server, single org).

Environment / settings
======================
Required:

* ``GITHUB_TOKEN``       — fine-grained PAT or classic PAT with
                            ``repo`` scope (or ``public_repo`` if
                            you only target public repos)

Optional:

* ``GITHUB_DEFAULT_REPO`` — default ``owner/repo`` slug used when
                            caller doesn't pass ``project=``
* ``GITHUB_API_URL``      — for GitHub Enterprise installs
                            (default ``https://api.github.com``)

When required vars are missing, every method returns
``ConnectorResult(skipped=True)``.
"""
from __future__ import annotations

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


_API_TIMEOUT = 15.0


class GitHubConnector:
    """GitHub Issues connector. ``project`` in the protocol maps to a
    ``owner/repo`` slug. We don't try to be clever about repo
    resolution — caller passes a slug or we fall back to
    ``GITHUB_DEFAULT_REPO``."""

    kind = "github"

    def __init__(
        self,
        token: str,
        api_url: str = "https://api.github.com",
        default_repo: Optional[str] = None,
    ):
        self.token = token
        self.api_url = api_url.rstrip("/")
        self.default_repo = default_repo

    @classmethod
    def from_env(cls) -> Optional["GitHubConnector"]:
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            return None
        return cls(
            token=token,
            api_url=os.getenv("GITHUB_API_URL") or "https://api.github.com",
            default_repo=os.getenv("GITHUB_DEFAULT_REPO") or None,
        )

    def _headers(self) -> Dict[str, str]:
        # X-GitHub-Api-Version pins the response shape so
        # ``data["html_url"]`` / ``data["number"]`` stay stable across
        # API versions.
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agent-hub-connector/1.0",
        }

    async def healthcheck(self) -> ConnectorResult:
        try:
            async with httpx.AsyncClient(timeout=_API_TIMEOUT) as c:
                r = await c.get(
                    f"{self.api_url}/user", headers=self._headers(),
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
        repo = (project or self.default_repo or "").strip()
        if "/" not in repo:
            return ConnectorResult(
                ok=False, kind=self.kind, skipped=True,
                error="no owner/repo slug (set GITHUB_DEFAULT_REPO or pass project=)",
            )

        payload: Dict[str, Any] = {
            "title": (title or "Untitled task")[:250],
            "body": body or "",
        }
        if labels:
            payload["labels"] = list(labels)
        if assignee:
            # GitHub API accepts a single login string here, not the
            # numeric id. Caller should pass a github username.
            payload["assignees"] = [assignee]

        try:
            async with httpx.AsyncClient(timeout=_API_TIMEOUT) as c:
                r = await c.post(
                    f"{self.api_url}/repos/{repo}/issues",
                    headers=self._headers(),
                    json=payload,
                )
            if r.status_code in (200, 201):
                data = r.json()
                number = data.get("number", "")
                ref = ExternalIssueRef(
                    kind=self.kind,
                    key=f"{repo}#{number}",
                    id=str(data.get("id", "")),
                    project=repo,
                    url=data.get("html_url", ""),
                    raw={"node_id": data.get("node_id", "")},
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
        """Append labels to an existing issue. GitHub treats this as
        an additive operation server-side (no need to GET-modify-PUT).

        Used by the escalation throttle to flag issues the AI keeps
        failing on so a human can pick them up from the normal
        triage queue.
        """
        if not ref or not ref.project or "#" not in ref.key:
            return ConnectorResult(
                ok=False, kind=self.kind, skipped=True,
                error="missing/invalid issue ref",
            )
        if not labels:
            return ConnectorResult(ok=True, kind=self.kind, skipped=True,
                                   error="no labels to add")
        try:
            number = ref.key.rsplit("#", 1)[1]
        except Exception:
            return ConnectorResult(
                ok=False, kind=self.kind, skipped=True,
                error=f"could not parse issue number from {ref.key!r}",
            )
        try:
            async with httpx.AsyncClient(timeout=_API_TIMEOUT) as c:
                r = await c.post(
                    f"{self.api_url}/repos/{ref.project}/issues/{number}/labels",
                    headers=self._headers(),
                    json={"labels": list(labels)},
                )
            if r.status_code in (200, 201):
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
        if not ref or not ref.project or "#" not in ref.key:
            return ConnectorResult(
                ok=False, kind=self.kind, skipped=True,
                error="missing/invalid issue ref",
            )
        try:
            number = ref.key.rsplit("#", 1)[1]
        except Exception:
            return ConnectorResult(
                ok=False, kind=self.kind, skipped=True,
                error=f"could not parse issue number from {ref.key!r}",
            )
        try:
            async with httpx.AsyncClient(timeout=_API_TIMEOUT) as c:
                r = await c.post(
                    f"{self.api_url}/repos/{ref.project}/issues/{number}/comments",
                    headers=self._headers(),
                    json={"body": body or ""},
                )
            if r.status_code in (200, 201):
                data = r.json()
                cref = ExternalCommentRef(
                    kind=self.kind,
                    issue_key=ref.key,
                    comment_id=str(data.get("id", "")),
                    url=data.get("html_url", ""),
                )
                return ConnectorResult(ok=True, kind=self.kind, comment=cref)
            return ConnectorResult(
                ok=False, kind=self.kind,
                error=f"add_comment HTTP {r.status_code}: {r.text[:300]}",
            )
        except Exception as exc:
            return ConnectorResult(ok=False, kind=self.kind, error=str(exc))


_: IssueConnector = GitHubConnector(token="x")  # type: ignore[abstract]
