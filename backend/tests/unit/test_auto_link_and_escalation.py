"""Tests for ``auto_link`` task hook + reject_count escalation throttle.

Covers the production-loop completers:

* ``_try_auto_link`` (``app/api/pipeline.py``) — task creation hook
  that mints an external issue and writes it to ``external_links``.
  We assert it never raises, soft-fails on missing config, and on
  success persists the link onto the task row.
* ``maybe_escalate`` (``app/services/escalation.py``) — throttle that
  fires exactly once per crossing of ``REJECT_ESCALATION_THRESHOLD``,
  fans out label-add to every linked tracker, posts a louder comment,
  and pings IM.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.services import escalation as esc
from app.services.connectors.base import (
    ConnectorResult,
    ExternalIssueRef,
)


# ─────────────────────────────────────────────────────────────────────
# Stubs
# ─────────────────────────────────────────────────────────────────────


class _StubConnector:
    """Tiny in-process connector that records label/comment calls."""

    def __init__(self, *, kind="stub", supports_labels=True,
                 label_behavior="ok", comment_behavior="ok",
                 create_behavior="ok"):
        self.kind = kind
        self.supports_labels = supports_labels
        self.label_behavior = label_behavior
        self.comment_behavior = comment_behavior
        self.create_behavior = create_behavior
        self.label_calls = []
        self.comment_calls = []
        self.create_calls = []

    async def create_issue(self, *, title, body, labels=None, assignee=None,
                           project=None, extras=None):
        self.create_calls.append({
            "title": title, "body": body, "labels": labels,
            "project": project,
        })
        if self.create_behavior == "ok":
            return ConnectorResult(
                ok=True, kind=self.kind,
                issue=ExternalIssueRef(
                    kind=self.kind, key="STUB-1",
                    project=project or "P", url="https://x/STUB-1",
                    id="100",
                ),
            )
        if self.create_behavior == "skip":
            return ConnectorResult(ok=False, kind=self.kind, skipped=True,
                                   error="no project")
        return ConnectorResult(ok=False, kind=self.kind, error="boom")

    async def add_comment(self, ref, body):
        self.comment_calls.append({"ref": ref, "body": body})
        if self.comment_behavior == "ok":
            return ConnectorResult(ok=True, kind=self.kind)
        return ConnectorResult(ok=False, kind=self.kind, error="comment err")

    if True:
        # Defined conditionally below in __init__ via attribute juggling.
        pass

    async def add_labels(self, ref, labels):
        if not self.supports_labels:
            raise AttributeError("no add_labels")
        self.label_calls.append({"ref": ref, "labels": list(labels)})
        if self.label_behavior == "ok":
            return ConnectorResult(ok=True, kind=self.kind)
        if self.label_behavior == "raise":
            raise RuntimeError("label endpoint blew up")
        return ConnectorResult(ok=False, kind=self.kind, error="label err")


class _LegacyConnector:
    """Connector without an ``add_labels`` method — mirrors a hypothetical
    older connector implementation. Used to verify the escalation
    helper degrades gracefully."""

    kind = "legacy"

    async def add_comment(self, ref, body):
        return ConnectorResult(ok=True, kind=self.kind)


# ─────────────────────────────────────────────────────────────────────
# auto_link path
# ─────────────────────────────────────────────────────────────────────


class _FakeTask:
    """Minimal stand-in for PipelineTask — just the attributes the
    auto_link helper touches. Avoids spinning up a DB session for
    a pure-Python test of the hook."""

    def __init__(self, *, title="My Task", description="desc",
                 external_links=None):
        self.title = title
        self.description = description
        self.external_links = list(external_links or [])


@pytest.mark.asyncio
async def test_auto_link_persists_new_link_on_success(monkeypatch):
    from app.api import pipeline as pipeline_api

    stub = _StubConnector(kind="jira")

    def _fake_get(kind):
        return stub if kind == "jira" else None

    # The helper imports get_connector lazily — patch the module attr.
    import app.services.connectors as _conn
    monkeypatch.setattr(_conn, "get_connector", _fake_get)

    task = _FakeTask(title="Add login", description="acceptance: ...")
    out = await pipeline_api._try_auto_link(
        task=task, kind="jira", project="AI", labels=["ai-generated"],
    )
    assert out["ok"] is True
    assert out["link"]["kind"] == "jira"
    assert out["link"]["key"] == "STUB-1"
    assert task.external_links[-1]["key"] == "STUB-1"
    assert stub.create_calls[0]["title"] == "Add login"
    assert stub.create_calls[0]["labels"] == ["ai-generated"]


@pytest.mark.asyncio
async def test_auto_link_soft_skip_when_connector_missing(monkeypatch):
    from app.api import pipeline as pipeline_api
    import app.services.connectors as _conn
    monkeypatch.setattr(_conn, "get_connector", lambda kind: None)

    task = _FakeTask()
    out = await pipeline_api._try_auto_link(
        task=task, kind="github", project=None, labels=None,
    )
    assert out["ok"] is False
    assert out["skipped"] is True
    assert out["reason"] == "connector_not_configured"
    # Critically: no link added (would corrupt downstream mirror).
    assert task.external_links == []


@pytest.mark.asyncio
async def test_auto_link_rejects_unknown_kind():
    from app.api import pipeline as pipeline_api
    task = _FakeTask()
    out = await pipeline_api._try_auto_link(
        task=task, kind="gitlab", project=None, labels=None,
    )
    assert out["ok"] is False
    assert out["skipped"] is True


@pytest.mark.asyncio
async def test_auto_link_handles_create_error_without_raising(monkeypatch):
    from app.api import pipeline as pipeline_api
    stub = _StubConnector(kind="jira", create_behavior="fail")
    import app.services.connectors as _conn
    monkeypatch.setattr(_conn, "get_connector", lambda kind: stub if kind == "jira" else None)

    task = _FakeTask()
    out = await pipeline_api._try_auto_link(
        task=task, kind="jira", project="AI", labels=None,
    )
    assert out["ok"] is False
    assert "boom" in (out.get("error") or "")
    assert task.external_links == []


# ─────────────────────────────────────────────────────────────────────
# Escalation throttle
# ─────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def _reset_escalation():
    """Async because the escalation dedup now writes to Redis (24h
    TTL); we MUST purge those keys between tests or a re-run within
    the same day looks like "already escalated"."""
    await esc.aclear_escalation_state()
    yield
    await esc.aclear_escalation_state()


def _patch_connectors(monkeypatch, mapping):
    """Make ``get_connector`` resolve through a fixed dict, on every
    import binding the escalation module + mirror module use."""
    def _fake_get(kind):
        return mapping.get((kind or "").lower())

    import app.services.connectors as _conn
    import app.services.connectors.mirror as _mirror
    monkeypatch.setattr(_conn, "get_connector", _fake_get)
    monkeypatch.setattr(_mirror, "get_connector", _fake_get)


class _FakeDB:
    """Stand-in for AsyncSession.get(...) returning a task row."""

    def __init__(self, task=None):
        self._task = task

    async def get(self, model, pk):
        return self._task


@pytest.mark.asyncio
async def test_escalation_silent_below_threshold(monkeypatch):
    monkeypatch.setenv("REJECT_ESCALATION_THRESHOLD", "3")
    stub = _StubConnector(kind="jira")
    _patch_connectors(monkeypatch, {"jira": stub})

    out = await esc.maybe_escalate(
        _FakeDB(_FakeTask(external_links=[
            {"kind": "jira", "key": "AI-7", "project": "AI", "url": "u"}
        ])),
        task_id="11111111-1111-1111-1111-111111111111",
        task_title="t", target_stage="dev",
        reject_count=2,
        links=[{"kind": "jira", "key": "AI-7"}],
    )
    assert out is None
    assert stub.label_calls == []
    assert stub.comment_calls == []


@pytest.mark.asyncio
async def test_escalation_fires_at_threshold_and_throttles(monkeypatch):
    monkeypatch.setenv("REJECT_ESCALATION_THRESHOLD", "3")
    monkeypatch.setenv("REJECT_ESCALATION_LABEL", "ai-stuck")

    jira = _StubConnector(kind="jira")
    gh = _StubConnector(kind="github")
    _patch_connectors(monkeypatch, {"jira": jira, "github": gh})

    # Stub IM notify so we don't try to import dispatcher's deps.
    import app.services.escalation as _esc

    async def _fake_notify(task, *, event, message="", url="", extras=None):
        from app.services.notify.dispatcher import NotifyResult
        return NotifyResult(ok=True, channel="test", mode="stub")

    monkeypatch.setattr(
        "app.services.notify.dispatcher.notify_task_event",
        _fake_notify,
    )

    task_id = "22222222-2222-2222-2222-222222222222"
    links = [
        {"kind": "jira", "key": "AI-7", "project": "AI", "url": "u1"},
        {"kind": "github", "key": "acme/web#42", "project": "acme/web", "url": "u2"},
    ]

    # First crossing — fires.
    out1 = await esc.maybe_escalate(
        _FakeDB(_FakeTask(external_links=links)),
        task_id=task_id, task_title="My task",
        target_stage="development",
        reject_count=3, links=links,
    )
    assert out1 is not None
    assert out1["rejectCount"] == 3
    assert out1["label"] == "ai-stuck"
    # Both connectors got a label add and a comment.
    assert len(jira.label_calls) == 1 and jira.label_calls[0]["labels"] == ["ai-stuck"]
    assert len(gh.label_calls) == 1
    assert len(jira.comment_calls) == 1
    assert "🚨" in jira.comment_calls[0]["body"]

    # Same count again — throttled (no new fan-out).
    out2 = await esc.maybe_escalate(
        _FakeDB(_FakeTask(external_links=links)),
        task_id=task_id, task_title="My task",
        target_stage="development",
        reject_count=3, links=links,
    )
    assert out2 is None
    assert len(jira.label_calls) == 1
    assert len(jira.comment_calls) == 1

    # Higher count — fires again (new high-water-mark).
    out3 = await esc.maybe_escalate(
        _FakeDB(_FakeTask(external_links=links)),
        task_id=task_id, task_title="My task",
        target_stage="development",
        reject_count=5, links=links,
    )
    assert out3 is not None
    assert out3["rejectCount"] == 5
    assert len(jira.label_calls) == 2
    assert len(jira.comment_calls) == 2


@pytest.mark.asyncio
async def test_escalation_handles_connector_without_add_labels(monkeypatch):
    """A connector missing ``add_labels`` (e.g. an older version) must
    not break escalation — the comment + IM still go out."""
    monkeypatch.setenv("REJECT_ESCALATION_THRESHOLD", "1")
    legacy = _LegacyConnector()
    _patch_connectors(monkeypatch, {"legacy": legacy})

    async def _fake_notify(task, *, event, message="", url="", extras=None):
        from app.services.notify.dispatcher import NotifyResult
        return NotifyResult(ok=True, channel="test", mode="stub")

    monkeypatch.setattr(
        "app.services.notify.dispatcher.notify_task_event",
        _fake_notify,
    )

    out = await esc.maybe_escalate(
        _FakeDB(_FakeTask(external_links=[{"kind": "legacy", "key": "X-1"}])),
        task_id="33333333-3333-3333-3333-333333333333",
        task_title="t", target_stage="dev",
        reject_count=1,
        links=[{"kind": "legacy", "key": "X-1"}],
    )
    assert out is not None
    # Label fan-out reports skipped per link, didn't crash.
    label_summary = out["labelResults"]
    assert len(label_summary) == 1
    assert label_summary[0]["skipped"] is True
    assert "add_labels" in label_summary[0]["error"]


@pytest.mark.asyncio
async def test_escalation_swallows_label_exception(monkeypatch):
    monkeypatch.setenv("REJECT_ESCALATION_THRESHOLD", "1")
    bad = _StubConnector(kind="jira", label_behavior="raise")
    _patch_connectors(monkeypatch, {"jira": bad})

    async def _fake_notify(task, *, event, message="", url="", extras=None):
        from app.services.notify.dispatcher import NotifyResult
        return NotifyResult(ok=True, channel="test", mode="stub")

    monkeypatch.setattr(
        "app.services.notify.dispatcher.notify_task_event",
        _fake_notify,
    )

    out = await esc.maybe_escalate(
        _FakeDB(_FakeTask(external_links=[{"kind": "jira", "key": "AI-1"}])),
        task_id="44444444-4444-4444-4444-444444444444",
        task_title="t", target_stage="dev",
        reject_count=1,
        links=[{"kind": "jira", "key": "AI-1"}],
    )
    # Despite the raise, escalation still completed: comment was sent
    # and the labelResults entry reports the failure structurally.
    assert out is not None
    assert out["labelResults"][0]["ok"] is False
    assert "RuntimeError" in out["labelResults"][0]["error"]


@pytest.mark.asyncio
async def test_escalation_threshold_env_default(monkeypatch):
    """Bad env values should fall back to 3, not break."""
    monkeypatch.setenv("REJECT_ESCALATION_THRESHOLD", "not-a-number")
    assert esc._threshold() == 3
    monkeypatch.setenv("REJECT_ESCALATION_THRESHOLD", "0")
    assert esc._threshold() == 3
    monkeypatch.setenv("REJECT_ESCALATION_THRESHOLD", "5")
    assert esc._threshold() == 5


# ─────────────────────────────────────────────────────────────────────
# Cross-worker dedup (Redis SETNX)
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_escalation_cross_worker_dedup(monkeypatch):
    """Simulate two workers seeing the same (task_id, reject_count):
    the SECOND ``maybe_escalate`` call must be a no-op even after we
    blow away the local in-memory cache, because Redis SETNX denies
    the second claim.

    This is the regression net for "gunicorn -w 4 sends 4× IM blasts"
    — without Redis dedup, every worker would fire independently."""
    monkeypatch.setenv("REJECT_ESCALATION_THRESHOLD", "1")
    stub = _StubConnector(kind="jira")
    _patch_connectors(monkeypatch, {"jira": stub})

    async def _fake_notify(task, *, event, message="", url="", extras=None):
        from app.services.notify.dispatcher import NotifyResult
        return NotifyResult(ok=True, channel="test", mode="stub")

    monkeypatch.setattr(
        "app.services.notify.dispatcher.notify_task_event",
        _fake_notify,
    )

    task_id = "55555555-5555-5555-5555-555555555555"
    links = [{"kind": "jira", "key": "AI-1"}]

    # Worker A — first call, should fire.
    out1 = await esc.maybe_escalate(
        _FakeDB(_FakeTask(external_links=links)),
        task_id=task_id, task_title="t", target_stage="dev",
        reject_count=1, links=links,
    )
    assert out1 is not None
    assert len(stub.label_calls) == 1
    assert len(stub.comment_calls) == 1

    # SIMULATE worker B: blow away the local high-water-mark cache so
    # the in-memory short-circuit doesn't hide the bug. Redis SETNX
    # must still deny the claim.
    esc._ESCALATED.clear()

    out2 = await esc.maybe_escalate(
        _FakeDB(_FakeTask(external_links=links)),
        task_id=task_id, task_title="t", target_stage="dev",
        reject_count=1, links=links,
    )
    assert out2 is None
    # NO additional fan-out — the second worker stayed quiet.
    assert len(stub.label_calls) == 1
    assert len(stub.comment_calls) == 1


@pytest.mark.asyncio
async def test_escalation_distinct_counts_each_fire(monkeypatch):
    """Even with Redis dedup, each NEW reject_count must fire — only
    *exact* (task, count) repeats are suppressed. Otherwise a stuck
    AI would keep climbing reject_count silently."""
    monkeypatch.setenv("REJECT_ESCALATION_THRESHOLD", "1")
    stub = _StubConnector(kind="jira")
    _patch_connectors(monkeypatch, {"jira": stub})

    async def _fake_notify(task, *, event, message="", url="", extras=None):
        from app.services.notify.dispatcher import NotifyResult
        return NotifyResult(ok=True, channel="test", mode="stub")

    monkeypatch.setattr(
        "app.services.notify.dispatcher.notify_task_event",
        _fake_notify,
    )

    task_id = "66666666-6666-6666-6666-666666666666"
    links = [{"kind": "jira", "key": "AI-2"}]

    fired = 0
    for count in (1, 2, 3):
        # Wipe local cache between to isolate Redis behavior.
        esc._ESCALATED.clear()
        out = await esc.maybe_escalate(
            _FakeDB(_FakeTask(external_links=links)),
            task_id=task_id, task_title="t", target_stage="dev",
            reject_count=count, links=links,
        )
        if out is not None:
            fired += 1

    assert fired == 3, "each new reject_count should produce its own escalation"
    assert len(stub.label_calls) == 3
