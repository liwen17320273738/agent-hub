"""Base types and protocol for issue-tracker connectors.

Every connector returns ``ConnectorResult`` so callers can uniformly
handle success/skip/error without try/except — same contract as the
IM notify adapters in ``app/services/notify``.

The ``ExternalIssueRef`` / ``ExternalCommentRef`` types are the
canonical handles we persist on our side (e.g. on a
``PipelineTask.external_links`` JSON column) so we can later add
comments without re-resolving the issue.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@dataclass
class ExternalIssueRef:
    """Stable handle for an issue created in an external system.

    ``key`` is the human-readable identifier displayed in URLs
    (Jira ``ABC-123``, GitHub ``owner/repo#42``); ``id`` is the
    opaque internal id used by the API for subsequent calls (some
    systems require it instead of key).
    """
    kind: str           # "jira" | "github"
    key: str            # ABC-123 / owner/repo#42
    url: str
    id: str = ""        # opaque API id when distinct from key
    project: str = ""   # JIRA project key / GH "owner/repo"
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind, "key": self.key, "url": self.url,
            "id": self.id, "project": self.project,
        }


@dataclass
class ExternalCommentRef:
    kind: str
    issue_key: str
    comment_id: str
    url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind, "issueKey": self.issue_key,
            "commentId": self.comment_id, "url": self.url,
        }


@dataclass
class ConnectorResult:
    """Uniform return type. ``ok`` is True on success; ``skipped`` is
    True when we deliberately did nothing (no credentials, dry run,
    target system disabled). Callers should treat ``skipped`` as a
    benign no-op, not an error."""
    ok: bool
    kind: str
    skipped: bool = False
    error: str = ""
    issue: Optional[ExternalIssueRef] = None
    comment: Optional[ExternalCommentRef] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "kind": self.kind,
            "skipped": self.skipped, "error": self.error,
            "issue": self.issue.to_dict() if self.issue else None,
            "comment": self.comment.to_dict() if self.comment else None,
        }


@runtime_checkable
class IssueConnector(Protocol):
    """Protocol every connector implements. Async because every method
    does I/O against a remote system."""

    kind: str

    async def healthcheck(self) -> ConnectorResult:
        """Verify auth + reachability. Used by the integrations health
        endpoint and at app startup to log warnings."""
        ...

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
        """Create an issue. ``project`` is required for Jira; for
        GitHub it's the ``owner/repo`` slug (or None to use the
        connector's default repo)."""
        ...

    async def add_comment(
        self,
        ref: ExternalIssueRef,
        body: str,
    ) -> ConnectorResult:
        """Append a comment to an existing issue. Used to mirror
        REJECT_TO events back to the originating tracker so reviewers
        can follow the AI's verdict in their normal queue."""
        ...
