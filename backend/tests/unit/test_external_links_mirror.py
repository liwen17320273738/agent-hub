"""Tests for ``PipelineTask.external_links`` + auto-mirror on REJECT.

Two layers covered here:

1. **Model / migration shape** — the column exists with the right
   default (``[]``) so existing rows stay compatible and inserts
   without an explicit value get a stable empty list, not ``NULL``.
2. **Mirror fan-out** — ``mirror_comment_to_links`` correctly handles
   the configured / not-configured / raise-mid-call matrix without
   ever bubbling, and the DAG REJECT helper
   (``_mirror_reject_to_external_links``) only fires when there ARE
   links and never blocks the orchestrator on a flaky tracker.

These are the regression nets for the "Demo → Production" bridge:
if a future refactor drops the JSON default or makes the mirror
loop blocking, these tests fail loudly.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List

import pytest

from app.services.connectors.base import (
    ConnectorResult,
    ExternalIssueRef,
)
from app.services.connectors.mirror import (
    _normalize_links,
    mirror_comment_to_links,
)


# ─────────────────────────────────────────────────────────────────────
# 1. _normalize_links — input hygiene
# ─────────────────────────────────────────────────────────────────────


def test_normalize_links_handles_none():
    assert _normalize_links(None) == []


def test_normalize_links_handles_empty_list():
    assert _normalize_links([]) == []


def test_normalize_links_wraps_legacy_single_dict():
    legacy = {"kind": "jira", "key": "AI-1"}
    assert _normalize_links(legacy) == [legacy]


def test_normalize_links_drops_garbage_entries():
    raw = [
        {"kind": "jira", "key": "AI-1"},          # ok
        {"kind": "jira"},                           # missing key → drop
        {"key": "AI-2"},                            # missing kind → drop
        "not-a-dict",                               # garbage → drop
        {"kind": "github", "key": "owner/r#42"},  # ok
    ]
    out = _normalize_links(raw)
    assert len(out) == 2
    assert out[0]["key"] == "AI-1"
    assert out[1]["key"] == "owner/r#42"


def test_normalize_links_rejects_arbitrary_scalar():
    assert _normalize_links("hello") == []
    assert _normalize_links(42) == []


# ─────────────────────────────────────────────────────────────────────
# 2. mirror_comment_to_links — fan-out behaviour
# ─────────────────────────────────────────────────────────────────────


class _StubConnector:
    """Tiny in-process connector that records add_comment calls and
    returns a configurable result. We don't need a full ``IssueConnector``
    runtime check for this — the mirror only calls ``add_comment``."""

    kind = "stub"

    def __init__(self, *, kind="stub", behavior="ok"):
        self.kind = kind
        self.behavior = behavior
        self.calls: List[Dict[str, Any]] = []

    async def add_comment(self, ref: ExternalIssueRef, body: str) -> ConnectorResult:
        self.calls.append({"ref": ref, "body": body})
        if self.behavior == "raise":
            raise RuntimeError("simulated transport blow-up")
        if self.behavior == "fail":
            return ConnectorResult(ok=False, kind=self.kind, error="API 500")
        if self.behavior == "skip":
            return ConnectorResult(ok=False, kind=self.kind, skipped=True)
        return ConnectorResult(
            ok=True, kind=self.kind,
        )


@pytest.fixture
def patch_registry(monkeypatch):
    """Yield a function that registers stub connectors keyed by kind."""
    from app.services.connectors import registry as _reg

    def _install(stubs: Dict[str, _StubConnector]):
        def _fake_get(kind):
            return stubs.get((kind or "").lower())

        monkeypatch.setattr(_reg, "get_connector", _fake_get)
        # Also patch the import binding the mirror module uses.
        from app.services.connectors import mirror as _mirror
        monkeypatch.setattr(_mirror, "get_connector", _fake_get)
        return stubs

    return _install


@pytest.mark.asyncio
async def test_mirror_returns_empty_when_no_links(patch_registry):
    patch_registry({"jira": _StubConnector(kind="jira")})
    out = await mirror_comment_to_links([], "hi")
    assert out == []


@pytest.mark.asyncio
async def test_mirror_skips_unconfigured_connector(patch_registry):
    # Registry returns None for github — meaning "not configured".
    patch_registry({"jira": _StubConnector(kind="jira")})
    links = [{"kind": "github", "key": "acme/web#42"}]
    out = await mirror_comment_to_links(links, "REJECTED")
    assert len(out) == 1
    assert out[0]["ok"] is False
    assert out[0]["skipped"] is True
    assert "not configured" in out[0]["error"]


@pytest.mark.asyncio
async def test_mirror_fans_out_in_parallel(patch_registry):
    jira = _StubConnector(kind="jira")
    gh = _StubConnector(kind="github")
    patch_registry({"jira": jira, "github": gh})

    links = [
        {"kind": "jira",   "key": "AI-7", "project": "AI",  "url": "u1"},
        {"kind": "github", "key": "acme/web#42", "project": "acme/web", "url": "u2"},
    ]
    out = await mirror_comment_to_links(links, "REJECTED — try again")
    assert len(out) == 2
    assert all(r["ok"] for r in out)
    assert jira.calls[0]["ref"].key == "AI-7"
    assert gh.calls[0]["ref"].key == "acme/web#42"
    assert "REJECTED" in jira.calls[0]["body"]


@pytest.mark.asyncio
async def test_mirror_swallows_connector_exception(patch_registry):
    """A raised exception in one connector must NOT poison the others."""
    bad = _StubConnector(kind="jira", behavior="raise")
    good = _StubConnector(kind="github")
    patch_registry({"jira": bad, "github": good})

    links = [
        {"kind": "jira",   "key": "AI-1"},
        {"kind": "github", "key": "acme/web#1"},
    ]
    out = await mirror_comment_to_links(links, "x")
    assert len(out) == 2
    # Bad connector returned a structured failure, not raised.
    bad_result = next(r for r in out if r["kind"] == "jira")
    assert bad_result["ok"] is False
    assert bad_result["skipped"] is False
    assert "RuntimeError" in bad_result["error"]
    # Good one still succeeded.
    good_result = next(r for r in out if r["kind"] == "github")
    assert good_result["ok"] is True


@pytest.mark.asyncio
async def test_mirror_only_kinds_filter(patch_registry):
    jira = _StubConnector(kind="jira")
    gh = _StubConnector(kind="github")
    patch_registry({"jira": jira, "github": gh})

    links = [
        {"kind": "jira",   "key": "AI-7"},
        {"kind": "github", "key": "acme/web#42"},
    ]
    out = await mirror_comment_to_links(links, "x", only_kinds={"github"})

    # Jira slot is reported as skipped (not silently dropped).
    jira_r = next(r for r in out if r["kind"] == "jira")
    assert jira_r["skipped"] is True and jira_r["ok"] is False
    # GitHub still got the call.
    assert len(gh.calls) == 1
    assert len(jira.calls) == 0


# ─────────────────────────────────────────────────────────────────────
# 3. Model column — migration backfill default
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_task_external_links_default_empty_list():
    """Inserting a PipelineTask without setting external_links should
    yield an empty list, not None — guards the migration's
    ``server_default=text("'[]'")`` and the model's ``default=list``.
    """
    # We use the existing test DB engine via the conftest fixtures.
    from app.database import Base, engine
    from app.models.pipeline import PipelineTask

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        t = PipelineTask(
            title="ext-links default test",
            description="",
            source="unit-test",
        )
        db.add(t)
        await db.commit()
        await db.refresh(t)

        # Critical assertion: backfill default must be [], not None.
        assert t.external_links == [], f"unexpected default: {t.external_links!r}"

        # And we can mutate it through reassignment (the API path).
        t.external_links = [
            {"kind": "jira", "key": "AI-7", "project": "AI", "url": "u", "id": "10042"},
        ]
        await db.commit()
        await db.refresh(t)
        assert isinstance(t.external_links, list)
        assert t.external_links[0]["key"] == "AI-7"

        # Cleanup.
        await db.delete(t)
        await db.commit()


# ─────────────────────────────────────────────────────────────────────
# 4. DAG REJECT auto-mirror integration
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dag_reject_helper_skips_when_no_links(monkeypatch):
    """When the task has no external_links, the helper must be a no-op
    and emit no events — this is the common case and we don't want
    SSE noise."""
    from app.services import dag_orchestrator as dag

    captured_events = []

    async def _fake_emit(event, payload):
        captured_events.append((event, payload))

    # Monkeypatch the *bound* emit_event the helper imports indirectly.
    monkeypatch.setattr(dag, "emit_event", _fake_emit)

    # And the DB lookup → return a task with empty links.
    class _T:
        external_links = []

    class _DB:
        async def get(self, model, pk):
            return _T()

    await dag._mirror_reject_to_external_links(
        _DB(), task_id=str(uuid.uuid4()),
        task_title="t", target="development",
        feedback="why", reject_count=1,
    )
    # No mirror, no SSE event.
    assert all(e[0] != "integrations:mirrored" for e in captured_events)


@pytest.mark.asyncio
async def test_dag_reject_helper_fans_out_and_emits_event(monkeypatch):
    """When the task DOES have links, every connector is called and
    a single ``integrations:mirrored`` event summarizes the result."""
    from app.services import dag_orchestrator as dag

    posted: List[Dict[str, Any]] = []
    captured_events: List[tuple] = []

    async def _fake_mirror(links, body, *, only_kinds=None):
        posted.append({"links": list(links), "body": body})
        return [
            {"ok": True,  "kind": "jira",   "skipped": False, "error": "",
             "issue": None, "comment": None},
            {"ok": False, "kind": "github", "skipped": True,  "error": "no token",
             "issue": None, "comment": None},
        ]

    async def _fake_emit(event, payload):
        captured_events.append((event, payload))

    # Replace the lazy import target inside the helper.
    import app.services.connectors as _conn
    monkeypatch.setattr(_conn, "mirror_comment_to_links", _fake_mirror)
    monkeypatch.setattr(dag, "emit_event", _fake_emit)

    class _T:
        external_links = [
            {"kind": "jira",   "key": "AI-7", "project": "AI", "url": "u"},
            {"kind": "github", "key": "acme/web#42", "project": "acme/web", "url": "v"},
        ]

    class _DB:
        async def get(self, model, pk):
            return _T()

    await dag._mirror_reject_to_external_links(
        _DB(), task_id=str(uuid.uuid4()),
        task_title="My task", target="development",
        feedback="schema field missing",
        reject_count=2,
    )

    assert len(posted) == 1, "mirror_comment_to_links should be called exactly once"
    body = posted[0]["body"]
    assert "schema field missing" in body
    assert "development" in body
    assert "第 2 次" in body

    mirrored_events = [p for e, p in captured_events if e == "integrations:mirrored"]
    assert len(mirrored_events) == 1
    ev = mirrored_events[0]
    assert ev["posted"] == 1
    assert ev["skipped"] == 1
    assert ev["failed"] == 0
    assert ev["target"] == "development"
    assert ev["rejectCount"] == 2


@pytest.mark.asyncio
async def test_dag_reject_helper_truncates_long_feedback(monkeypatch):
    """A reviewer that dumps 50KB of chain-of-thought must not blow
    Jira's comment size limit. We cap at 1500 chars + ellipsis."""
    from app.services import dag_orchestrator as dag

    seen_body = {}

    async def _fake_mirror(links, body, *, only_kinds=None):
        seen_body["body"] = body
        return [{"ok": True, "kind": "jira", "skipped": False, "error": "",
                 "issue": None, "comment": None}]

    async def _fake_emit(*a, **kw):
        return None

    import app.services.connectors as _conn
    monkeypatch.setattr(_conn, "mirror_comment_to_links", _fake_mirror)
    monkeypatch.setattr(dag, "emit_event", _fake_emit)

    huge = "x" * 50_000

    class _T:
        external_links = [{"kind": "jira", "key": "AI-1"}]

    class _DB:
        async def get(self, model, pk):
            return _T()

    await dag._mirror_reject_to_external_links(
        _DB(), task_id=str(uuid.uuid4()),
        task_title="t", target="development",
        feedback=huge, reject_count=1,
    )
    body = seen_body["body"]
    # Feedback section must be truncated. Total body is small (the
    # 50000 chars never make it through).
    assert len(body) < 2500
    assert body.endswith("…")
