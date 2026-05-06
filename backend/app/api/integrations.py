"""Issue-tracker integrations API.

Surfaces the connectors package over REST so operators can:

  * See which connectors are configured (UI integration tab).
  * Health-check them without leaving the dashboard.
  * Manually create / comment on an issue from a task — until the
    automated mirror lands, this is the escape hatch.

All write endpoints require an authenticated user. Connectors that
aren't configured (env vars missing) return ``skipped=true`` rather
than 500 — same contract as the IM notify adapters.
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.pipeline import PipelineTask
from ..security import get_current_user
from ..services.connectors import (
    ExternalIssueRef,
    available_connectors,
    get_connector,
)
from ..services.connectors.webhook import (
    InboundComment,
    parse_github_issue_comment,
    parse_jira_comment,
    select_tasks_for_inbound,
    verify_github_signature,
    verify_jira_token,
)
from ..services.dedup import claim_dedup_token

logger = logging.getLogger(__name__)


# Webhook delivery-ID dedup TTL. 24h is the largest retry window
# either GitHub or Jira will use in practice.
_WEBHOOK_DEDUP_TTL = 24 * 3600

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


# ─────────────────────────────────────────────────────────────────────
# Request schemas
# ─────────────────────────────────────────────────────────────────────


class CreateIssueRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    body: str = ""
    labels: Optional[List[str]] = None
    assignee: Optional[str] = None
    project: Optional[str] = Field(
        None,
        description=(
            "Jira project key (e.g. 'AI') OR GitHub 'owner/repo' slug. "
            "When omitted, falls back to JIRA_DEFAULT_PROJECT / "
            "GITHUB_DEFAULT_REPO."
        ),
    )
    extras: Optional[Dict[str, Any]] = None


class CommentRequest(BaseModel):
    issue_key: str = Field(
        ...,
        description="Jira ABC-123 or GitHub 'owner/repo#42'",
        min_length=1, max_length=200,
    )
    project: Optional[str] = Field(
        None,
        description="Required for GitHub (the owner/repo slug). For "
                    "Jira, the project is encoded in the key.",
    )
    body: str = Field(..., min_length=1, max_length=10000)


# ─────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────


@router.get("/connectors")
async def list_connectors(_user=Depends(get_current_user)):
    """Configured connector kinds + a hint for any that aren't."""
    configured = set(available_connectors())
    all_kinds = ["jira", "github"]
    return {
        "configured": sorted(configured),
        "available_kinds": all_kinds,
        "details": {
            kind: {
                "configured": kind in configured,
                "hint": _config_hint(kind),
            }
            for kind in all_kinds
        },
    }


@router.get("/connectors/{kind}/healthcheck")
async def healthcheck_connector(kind: str, _user=Depends(get_current_user)):
    """Live-poke the connector to verify auth + reachability.

    A 200 with ``ok=false`` means the connector is configured but the
    remote system rejected us (bad token, repo deleted, etc.); a 200
    with ``skipped=true`` means the connector isn't configured. We
    deliberately don't 5xx so the dashboard can render either state.
    """
    conn = get_connector(kind)
    if conn is None:
        return {
            "ok": False, "kind": kind, "skipped": True,
            "error": _config_hint(kind),
        }
    res = await conn.healthcheck()
    return res.to_dict()


@router.post("/connectors/{kind}/issues")
async def create_external_issue(
    kind: str,
    req: CreateIssueRequest,
    _user=Depends(get_current_user),
):
    """Create an issue. Returns an ``ExternalIssueRef`` the caller can
    persist (e.g. against a ``PipelineTask``) and reuse for future
    comments."""
    conn = get_connector(kind)
    if conn is None:
        raise HTTPException(
            status_code=400, detail=f"Connector '{kind}' is not configured. {_config_hint(kind)}",
        )
    res = await conn.create_issue(
        title=req.title, body=req.body,
        labels=req.labels, assignee=req.assignee,
        project=req.project, extras=req.extras,
    )
    if not res.ok and not res.skipped:
        # Real error from the remote system — surface as 502.
        raise HTTPException(status_code=502, detail=res.error or "create_issue failed")
    return res.to_dict()


@router.post("/connectors/{kind}/comments")
async def add_external_comment(
    kind: str,
    req: CommentRequest,
    _user=Depends(get_current_user),
):
    """Append a comment to an existing issue. The caller passes the
    issue key (and project for GitHub) — we don't try to parse it
    out of an opaque persisted reference because callers may have
    been edited / re-imported since."""
    conn = get_connector(kind)
    if conn is None:
        raise HTTPException(
            status_code=400, detail=f"Connector '{kind}' is not configured. {_config_hint(kind)}",
        )
    # Reconstruct an ExternalIssueRef just enough for add_comment.
    project = req.project or ""
    if kind.lower() == "github" and "#" in req.issue_key and not project:
        # Allow callers to encode owner/repo#N in issue_key alone.
        project = req.issue_key.rsplit("#", 1)[0]
    ref = ExternalIssueRef(
        kind=kind.lower(), key=req.issue_key,
        project=project, url="",
    )
    res = await conn.add_comment(ref, req.body)
    if not res.ok and not res.skipped:
        raise HTTPException(status_code=502, detail=res.error or "add_comment failed")
    return res.to_dict()


# ─────────────────────────────────────────────────────────────────────
# Task ↔ external-issue link CRUD
# ─────────────────────────────────────────────────────────────────────
#
# These four endpoints turn a generic ``PipelineTask`` into something
# that *knows* it represents Jira AI-7 / GitHub acme/web#42, so the
# DAG REJECT path can mirror verdicts back automatically (see
# ``app.services.connectors.mirror``).


class LinkTaskRequest(BaseModel):
    """Bind an existing external issue to a task (the user already
    created the issue manually or via /connectors/{kind}/issues)."""

    kind: str = Field(..., description="'jira' | 'github'")
    key: str = Field(..., min_length=1, max_length=200,
                     description="Jira ABC-123 or GitHub owner/repo#42")
    url: str = ""
    project: str = ""
    id: str = ""

    def to_link_dict(self) -> Dict[str, Any]:
        kind_l = self.kind.lower()
        project = self.project
        # Auto-derive project for GitHub from "owner/repo#N".
        if kind_l == "github" and "#" in self.key and not project:
            project = self.key.rsplit("#", 1)[0]
        return {
            "kind": kind_l, "key": self.key, "url": self.url,
            "project": project, "id": self.id,
        }


class CreateAndLinkRequest(BaseModel):
    """Create a brand-new external issue from the task's metadata and
    bind it in a single round trip."""

    kind: str = Field(..., description="'jira' | 'github'")
    title: Optional[str] = Field(
        None, description="Defaults to the task's title.",
    )
    body: Optional[str] = Field(
        None, description="Defaults to the task's description.",
    )
    project: Optional[str] = None
    labels: Optional[List[str]] = None
    assignee: Optional[str] = None
    extras: Optional[Dict[str, Any]] = None


def _parse_task_uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid task id")


async def _load_task(db: AsyncSession, task_id: str) -> PipelineTask:
    task = await db.get(PipelineTask, _parse_task_uuid(task_id))
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


def _normalize_existing_links(raw: Any) -> List[Dict[str, Any]]:
    """Accept legacy/garbage shapes and return a clean list."""
    if not raw:
        return []
    if isinstance(raw, dict):
        return [raw]
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict) and item.get("kind") and item.get("key"):
            out.append(item)
    return out


def _link_dedup_key(link: Dict[str, Any]) -> str:
    return f"{str(link.get('kind','')).lower()}::{link.get('key','')}"


@router.get("/tasks/{task_id}/links")
async def list_task_links(
    task_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user=Depends(get_current_user),
):
    """Return the external_links currently attached to a task."""
    task = await _load_task(db, task_id)
    return {
        "taskId": str(task.id),
        "links": _normalize_existing_links(task.external_links),
    }


@router.post("/tasks/{task_id}/links", status_code=201)
async def add_task_link(
    task_id: str,
    req: LinkTaskRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user=Depends(get_current_user),
):
    """Bind an existing external issue to the task. Idempotent on
    ``(kind, key)`` — a duplicate bind just updates url/project/id."""
    if req.kind.lower() not in {"jira", "github"}:
        raise HTTPException(status_code=400,
                            detail=f"unsupported connector kind {req.kind!r}")
    task = await _load_task(db, task_id)
    new_link = req.to_link_dict()

    existing = _normalize_existing_links(task.external_links)
    dedup_key = _link_dedup_key(new_link)
    merged = [link for link in existing if _link_dedup_key(link) != dedup_key]
    merged.append(new_link)

    task.external_links = merged
    # SQLAlchemy doesn't dirty-track in-place mutation of a JSON column
    # consistently across dialects; reassigning forces an UPDATE.
    await db.commit()
    await db.refresh(task)
    return {
        "taskId": str(task.id),
        "added": new_link,
        "links": task.external_links,
    }


@router.delete("/tasks/{task_id}/links/{kind}/{key:path}")
async def remove_task_link(
    task_id: str,
    kind: str,
    key: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user=Depends(get_current_user),
):
    """Unbind a previously-linked external issue. ``key`` is allowed
    to contain ``/`` and ``#`` (GitHub owner/repo#42) — that's why
    it's a path-style param."""
    task = await _load_task(db, task_id)
    target_dedup = _link_dedup_key({"kind": kind, "key": key})
    existing = _normalize_existing_links(task.external_links)
    remaining = [link for link in existing if _link_dedup_key(link) != target_dedup]
    if len(remaining) == len(existing):
        raise HTTPException(status_code=404, detail="link not found")

    task.external_links = remaining
    await db.commit()
    await db.refresh(task)
    return {
        "taskId": str(task.id),
        "removed": {"kind": kind.lower(), "key": key},
        "links": task.external_links,
    }


@router.post("/tasks/{task_id}/links/create-and-bind", status_code=201)
async def create_and_bind_task_link(
    task_id: str,
    req: CreateAndLinkRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user=Depends(get_current_user),
):
    """Create a fresh external issue *from* the task and bind it.

    Single-call shortcut for the common "promote this AI-spawned task
    into our Jira backlog" flow. Falls back to the task's own title
    and description when the request body omits them.
    """
    conn = get_connector(req.kind)
    if conn is None:
        raise HTTPException(
            status_code=400,
            detail=f"Connector '{req.kind}' is not configured. {_config_hint(req.kind)}",
        )
    task = await _load_task(db, task_id)
    title = req.title or task.title
    body = req.body if req.body is not None else (task.description or "")

    res = await conn.create_issue(
        title=title, body=body,
        labels=req.labels, assignee=req.assignee,
        project=req.project, extras=req.extras,
    )
    if not res.ok:
        # Don't pollute external_links if creation failed.
        if res.skipped:
            return res.to_dict()
        raise HTTPException(status_code=502,
                            detail=res.error or "create_issue failed")

    issue = res.issue
    if issue is None:
        raise HTTPException(status_code=502,
                            detail="connector returned ok=True but no issue ref")

    new_link = {
        "kind": issue.kind, "key": issue.key, "url": issue.url,
        "project": issue.project, "id": issue.id,
    }
    existing = _normalize_existing_links(task.external_links)
    dedup_key = _link_dedup_key(new_link)
    merged = [link for link in existing if _link_dedup_key(link) != dedup_key]
    merged.append(new_link)
    task.external_links = merged
    await db.commit()
    await db.refresh(task)

    return {
        "taskId": str(task.id),
        "created": res.to_dict(),
        "links": task.external_links,
    }


# ─────────────────────────────────────────────────────────────────────
# Inbound webhooks (Jira / GitHub → Agent Hub)
# ─────────────────────────────────────────────────────────────────────
#
# Closes the bidirectional loop: a comment dropped on a linked Jira
# issue / GitHub issue lands here, gets normalized into an
# ``InboundComment``, matched against ``PipelineTask.external_links``,
# and submitted as feedback so the AI iterates without anyone having
# to switch back to Agent Hub.
#
# Important behaviour:
#   * Signature / shared-token verification is enforced when env is
#     set; left open with a logged warning otherwise — same trade-off
#     as our Slack / Feishu inbound paths so dev workflows stay
#     friction-free.
#   * Comments authored by the bot itself ("[Agent Hub] ..." or by a
#     GitHub Bot user / matching JIRA_EMAIL) are dropped to break the
#     loop. Without this, a single REJECT would echo back ⇒ another
#     REJECT ⇒ explosion.
#   * Returns 200 with ``processed=N`` even when no task matches — a
#     non-2xx makes upstream trackers retry / disable the webhook,
#     which we never want for "comment on an unrelated issue".


async def _ingest_inbound_comment(
    db: AsyncSession,
    inbound: InboundComment,
) -> Dict[str, Any]:
    """Find linked tasks for ``inbound`` and submit each as feedback.

    The query loads only tasks with non-empty ``external_links``
    (using a coarse "is not null" filter) and finishes the match in
    Python — works on every dialect (SQLite dev, Postgres prod) and
    cardinality is small per webhook hit.
    """
    if inbound.is_self_authored:
        return {
            "processed": 0,
            "skipped_reason": "self_authored",
            "issueKey": inbound.issue_key,
        }

    # Coarse SQL filter; final match is Python-side via
    # ``select_tasks_for_inbound`` so we don't have to write
    # dialect-specific JSON queries.
    stmt = select(PipelineTask).where(PipelineTask.external_links.isnot(None))
    rows = await db.execute(stmt)
    candidates = rows.scalars().all()
    matched = select_tasks_for_inbound(candidates, inbound.kind, inbound.issue_key)
    if not matched:
        return {
            "processed": 0,
            "skipped_reason": "no_linked_task",
            "issueKey": inbound.issue_key,
        }

    # Lazy import — feedback module pulls in pipeline_engine.
    from ..services.interaction.feedback import feedback_loop

    submitted: List[Dict[str, Any]] = []
    for task in matched:
        item = await feedback_loop.submit_feedback(
            task_id=str(task.id),
            content=inbound.body,
            source=f"{inbound.kind}:{inbound.author or 'unknown'}",
            user_id=inbound.author,
            feedback_type="revision",
        )
        feedback_id = item.id if hasattr(item, "id") else getattr(item, "feedback_id", "")

        # Mirror the IM gateway path (app/api/gateway.py:152-153):
        # submit ALONE only persists the record; we need
        # process_feedback to actually trigger the iteration agents.
        # Without this, an inbound Jira / GitHub comment would silently
        # land in the feedback table and the AI would never act on it.
        process_result: Dict[str, Any] = {}
        try:
            process_result = await feedback_loop.process_feedback(
                feedback_id, db=db,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "[webhook] process_feedback failed for task=%s feedback=%s: %s",
                task.id, feedback_id, exc,
            )
            process_result = {"ok": False, "error": str(exc)[:300]}

        submitted.append({
            "taskId": str(task.id),
            "feedbackId": feedback_id,
            "action": process_result.get("action"),
            "iteration": process_result.get("iteration"),
            "stagesToRerun": process_result.get("stagesToRerun"),
        })

    return {
        "processed": len(submitted),
        "issueKey": inbound.issue_key,
        "kind": inbound.kind,
        "submitted": submitted,
    }


@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_github_event: Optional[str] = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    x_github_delivery: Optional[str] = Header(None, alias="X-GitHub-Delivery"),
):
    """GitHub → Agent Hub bridge for ``issue_comment.created``.

    Configure on the GitHub side: repo Settings → Webhooks → Add ::

        Payload URL:  https://your-host/api/integrations/webhooks/github
        Content type: application/json
        Secret:       <same as GITHUB_WEBHOOK_SECRET>
        Events:       Issue comments (only)
    """
    raw = await request.body()
    if not verify_github_signature(raw, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    if x_github_event and x_github_event != "issue_comment":
        return {"processed": 0, "skipped_reason": f"event_{x_github_event}"}

    # Dedup BEFORE parsing — GitHub auto-retries on 5xx / network blip
    # and assigns a stable ``X-GitHub-Delivery`` UUID per event. Two
    # workers receiving the same retry must not both fire iterate
    # (would burn 2× tokens on the same reviewer comment).
    if x_github_delivery:
        claimed = await claim_dedup_token(
            f"webhook:gh:{x_github_delivery}",
            ttl_seconds=_WEBHOOK_DEDUP_TTL,
        )
        if not claimed:
            return {
                "processed": 0,
                "deduplicated": True,
                "deliveryId": x_github_delivery,
            }

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON payload")

    inbound = parse_github_issue_comment(payload)
    if inbound is None:
        return {"processed": 0, "skipped_reason": "unsupported_action"}

    return await _ingest_inbound_comment(db, inbound)


@router.post("/webhooks/jira")
async def jira_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: Optional[str] = Query(
        None, description="Shared-secret token (matches JIRA_WEBHOOK_SECRET)",
    ),
    x_jira_webhook_token: Optional[str] = Header(None, alias="X-Jira-Webhook-Token"),
):
    """Jira → Agent Hub bridge for ``comment_created``.

    Configure on the Jira side: System → WebHooks → Create ::

        URL:    https://your-host/api/integrations/webhooks/jira?token=<JIRA_WEBHOOK_SECRET>
        Events: Comment → created
        JQL:    (optional, restrict to projects you've linked)

    Either the ``?token=`` query param OR the ``X-Jira-Webhook-Token``
    header is accepted — Jira UI doesn't always allow custom headers
    so the query string is the documented escape hatch.
    """
    given = token or x_jira_webhook_token
    if not verify_jira_token(given):
        raise HTTPException(status_code=401, detail="invalid webhook token")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON payload")

    inbound = parse_jira_comment(payload)
    if inbound is None:
        return {"processed": 0, "skipped_reason": "unsupported_event"}

    # Jira doesn't ship a delivery UUID, but every comment has a stable
    # numeric id we can dedup on. Combined with the issue key it's a
    # reasonable global key (Jira instances don't collide across keys).
    comment = (payload.get("comment") or {})
    comment_id = str(comment.get("id") or "")
    if comment_id:
        claimed = await claim_dedup_token(
            f"webhook:jira:{inbound.issue_key}:{comment_id}",
            ttl_seconds=_WEBHOOK_DEDUP_TTL,
        )
        if not claimed:
            return {
                "processed": 0,
                "deduplicated": True,
                "issueKey": inbound.issue_key,
                "commentId": comment_id,
            }

    return await _ingest_inbound_comment(db, inbound)


def _config_hint(kind: str) -> str:
    """Human-readable env-var checklist for the misconfigured case."""
    kind = (kind or "").lower()
    if kind == "jira":
        return (
            "Set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN. Optional: "
            "JIRA_DEFAULT_PROJECT, JIRA_DEFAULT_ISSUE_TYPE."
        )
    if kind == "github":
        return (
            "Set GITHUB_TOKEN. Optional: GITHUB_DEFAULT_REPO (owner/repo), "
            "GITHUB_API_URL (for Enterprise)."
        )
    return f"unknown connector kind {kind!r}; supported: jira, github"
