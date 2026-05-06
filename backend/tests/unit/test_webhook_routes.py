"""End-to-end tests for the webhook HTTP routes.

The unit tests in ``test_inbound_webhooks.py`` cover the parser and
verifier in isolation; this module wires them through the actual
FastAPI router so we catch wiring bugs (missing dependencies, wrong
header names, mis-applied dedup) that pure parser tests can't see.

Specifically validates:

* Delivery-UUID dedup — a retried webhook returns ``deduplicated``
  on the 2nd hit (regression net for the "Redis SETNX wired up
  correctly" guarantee).
* ``submit_feedback`` is followed by ``process_feedback`` so an
  inbound comment actually triggers iteration (closes the gap that
  the previous round shipped without).
* Self-authored comments are bounced (no feedback submitted).
* Bad signature ⇒ 401.
"""
from __future__ import annotations

import json
import uuid
from typing import List

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _purge_webhook_dedup():
    """Wipe ``webhook:gh:*`` and ``webhook:jira:*`` keys from BOTH
    the in-memory fallback AND the real Redis (when a real Redis
    is reachable). Tests use fixed UUIDs / comment IDs to assert
    dedup behavior, so leftover keys from a previous run with the
    24h TTL would silently break those assertions."""
    from app.redis_client import _memory_store, _memory_expiry, get_redis
    prefixes = ("webhook:gh:", "webhook:jira:")

    def _purge_memory():
        for k in list(_memory_store.keys()):
            if isinstance(k, str) and k.startswith(prefixes):
                _memory_store.pop(k, None)
                _memory_expiry.pop(k, None)

    async def _purge_real():
        try:
            r = get_redis()
            scan = getattr(r, "scan_iter", None)
            if scan is None:
                return
            for prefix in prefixes:
                async for k in r.scan_iter(match=f"{prefix}*"):
                    try:
                        await r.delete(k)
                    except Exception:
                        pass
        except Exception:
            pass

    _purge_memory()
    await _purge_real()
    yield
    _purge_memory()
    await _purge_real()


@pytest.fixture
def patch_feedback(monkeypatch):
    """Stub out ``feedback_loop`` so tests don't actually run the
    iteration agents — we only care that the route CALLS submit
    AND process. Returns a recorder dict the test can inspect."""
    submitted: List[dict] = []
    processed: List[dict] = []

    class _FakeFeedbackItem:
        def __init__(self, fid: str):
            self.id = fid

    class _FakeFeedbackLoop:
        async def submit_feedback(self, **kw):
            submitted.append(kw)
            return _FakeFeedbackItem(fid=f"fb-{len(submitted)}")

        async def process_feedback(self, feedback_id, db=None):
            processed.append({"feedback_id": feedback_id})
            return {
                "ok": True, "action": "iterate",
                "iteration": 1, "stagesToRerun": ["development"],
                "feedbackContent": "...",
            }

    fake = _FakeFeedbackLoop()

    # Patch BOTH possible import paths — the route does
    # ``from ..services.interaction.feedback import feedback_loop``
    # so the binding lives on the feedback module.
    import app.services.interaction.feedback as _fb_mod
    monkeypatch.setattr(_fb_mod, "feedback_loop", fake)
    return {"submitted": submitted, "processed": processed, "fake": fake}


# ─────────────────────────────────────────────────────────────────────
# GitHub webhook
# ─────────────────────────────────────────────────────────────────────


def _gh_payload(*, body="please retry", number=42, full_name="acme/web",
                login="alice", user_type="User", action="created"):
    return {
        "action": action,
        "issue": {"number": number},
        "comment": {"body": body, "user": {"login": login, "type": user_type}},
        "repository": {"full_name": full_name},
    }


async def _seed_linked_task(db, kind: str, key: str):
    """Create a task with a single external link so the inbound webhook
    has something to match against."""
    from app.models.pipeline import PipelineTask
    task = PipelineTask(
        title="Linked task",
        description="",
        external_links=[{"kind": kind, "key": key, "project": "", "url": "", "id": ""}],
    )
    db.add(task)
    await db.flush()
    await db.commit()
    return task


@pytest.mark.asyncio
async def test_github_webhook_invalid_signature_returns_401(
    client, patch_feedback, monkeypatch,
):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "topsecret")
    body = json.dumps(_gh_payload()).encode()

    r = await client.post(
        "/api/integrations/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "issue_comment",
            "X-Hub-Signature-256": "sha256=deadbeef",
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 401
    assert patch_feedback["submitted"] == []


@pytest.mark.asyncio
async def test_github_webhook_submits_AND_processes_feedback(
    client, db, patch_feedback, monkeypatch,
):
    """Closing the loop: submit ALONE persists; the route must also
    call process_feedback so the AI actually iterates. Without this,
    inbound comments would silently land in a queue forever."""
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)

    await _seed_linked_task(db, "github", "acme/web#42")

    body = json.dumps(_gh_payload()).encode()
    r = await client.post(
        "/api/integrations/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "issue_comment",
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["processed"] == 1
    assert out["submitted"][0]["action"] == "iterate"

    # CRITICAL: both submit AND process must have been called.
    assert len(patch_feedback["submitted"]) == 1
    assert len(patch_feedback["processed"]) == 1
    assert patch_feedback["processed"][0]["feedback_id"] == "fb-1"


@pytest.mark.asyncio
async def test_github_webhook_dedups_on_retry(
    client, db, patch_feedback, monkeypatch,
):
    """GitHub re-delivers the SAME ``X-GitHub-Delivery`` UUID on
    network retry. Second hit must return ``deduplicated=true`` and
    NOT re-submit feedback."""
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    await _seed_linked_task(db, "github", "acme/web#42")

    delivery = "00000000-1111-2222-3333-444444444444"
    body = json.dumps(_gh_payload()).encode()
    headers = {
        "X-GitHub-Event": "issue_comment",
        "X-GitHub-Delivery": delivery,
        "Content-Type": "application/json",
    }

    r1 = await client.post(
        "/api/integrations/webhooks/github", content=body, headers=headers,
    )
    assert r1.status_code == 200
    assert r1.json()["processed"] == 1, r1.json()

    # Same delivery UUID — must dedup.
    r2 = await client.post(
        "/api/integrations/webhooks/github", content=body, headers=headers,
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2.get("deduplicated") is True
    assert body2["processed"] == 0

    # Only ONE feedback submission across both calls.
    assert len(patch_feedback["submitted"]) == 1
    assert len(patch_feedback["processed"]) == 1


@pytest.mark.asyncio
async def test_github_webhook_self_loop_bounce(
    client, db, patch_feedback, monkeypatch,
):
    """A comment authored by Agent Hub itself ([Agent Hub] prefix) must
    NOT round-trip into another iterate — that would deadlock the
    REJECT path."""
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    await _seed_linked_task(db, "github", "acme/web#42")

    body = json.dumps(_gh_payload(body="[Agent Hub] 评审驳回 → ...")).encode()
    r = await client.post(
        "/api/integrations/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "issue_comment",
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 200
    out = r.json()
    assert out["processed"] == 0
    assert out.get("skipped_reason") == "self_authored"
    assert patch_feedback["submitted"] == []


# ─────────────────────────────────────────────────────────────────────
# Jira webhook
# ─────────────────────────────────────────────────────────────────────


def _jira_payload(*, comment_id="987", issue_key="AI-7",
                   body="please update schema", author_email="reviewer@acme.com"):
    return {
        "webhookEvent": "comment_created",
        "issue": {"key": issue_key},
        "comment": {
            "id": comment_id,
            "body": body,
            "author": {
                "emailAddress": author_email,
                "displayName": "Reviewer",
                "accountId": "acc-123",
            },
        },
    }


@pytest.mark.asyncio
async def test_jira_webhook_dedups_on_comment_id(
    client, db, patch_feedback, monkeypatch,
):
    """Jira doesn't ship a delivery UUID, so we dedup on
    ``comment.id`` — replay of the same comment ⇒ no-op."""
    monkeypatch.delenv("JIRA_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    await _seed_linked_task(db, "jira", "AI-7")

    body = json.dumps(_jira_payload(comment_id="cm-12345")).encode()
    headers = {"Content-Type": "application/json"}

    r1 = await client.post(
        "/api/integrations/webhooks/jira",
        content=body, headers=headers,
    )
    assert r1.status_code == 200
    assert r1.json()["processed"] == 1

    r2 = await client.post(
        "/api/integrations/webhooks/jira",
        content=body, headers=headers,
    )
    assert r2.status_code == 200
    out = r2.json()
    assert out.get("deduplicated") is True
    assert out["processed"] == 0
    assert len(patch_feedback["submitted"]) == 1
    assert len(patch_feedback["processed"]) == 1


@pytest.mark.asyncio
async def test_jira_webhook_token_required_when_secret_set(
    client, db, patch_feedback, monkeypatch,
):
    monkeypatch.setenv("JIRA_WEBHOOK_SECRET", "supersecret")
    body = json.dumps(_jira_payload()).encode()

    # Wrong token.
    r = await client.post(
        "/api/integrations/webhooks/jira?token=wrong",
        content=body, headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 401
    assert patch_feedback["submitted"] == []

    # Right token.
    r2 = await client.post(
        "/api/integrations/webhooks/jira?token=supersecret",
        content=body, headers={"Content-Type": "application/json"},
    )
    # No linked task → 200 with processed=0 (not 401), confirms auth passed.
    assert r2.status_code == 200
    assert r2.json()["processed"] == 0
