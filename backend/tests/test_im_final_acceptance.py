"""Wave 5 — IM-side final-acceptance routing tests.

Covers the gateway helper that translates IM messages and Feishu/Slack
button clicks into the same final-accept / final-reject state machine
the dashboard uses, including:

* Keyword classification (``通过`` → accept, ``重做`` → reject, etc.)
* ``_apply_final_acceptance_from_im`` actually mutates the row
* ``@stage:xxx`` hint resets that stage + downstream
* Status guard: only fires when the task is at the awaiting terminus
* Replying to a parked task with garbage drops a hint instead of going
  back into the legacy intra-stage feedback loop

We don't exercise actual Feishu/QQ HTTP traffic — outbound notifications
get monkeypatched so the tests can run offline.
"""
from __future__ import annotations

import pytest

from app.models.pipeline import PipelineTask, PipelineStage


@pytest.fixture(autouse=True)
def _stub_emit_event(monkeypatch):
    """Same SSE stub as test_acceptance_endpoints — keeps Redis off the
    critical path so the in-memory sqlite event loop doesn't get tangled
    up across tests."""
    async def _noop(event, data):  # noqa: ANN001
        return None
    monkeypatch.setattr("app.services.sse.emit_event", _noop, raising=True)
    monkeypatch.setattr("app.api.gateway.emit_event", _noop, raising=False)


@pytest.fixture(autouse=True)
def _stub_outbound_notify(monkeypatch):
    """The gateway tries to push confirmation cards back to Feishu/QQ —
    we record calls but never hit the network."""
    sent: list[dict] = []

    async def _fake_notify_user_text(*, source, user_id, title, body):
        sent.append({"source": source, "user_id": user_id, "title": title, "body": body})
        return type("R", (), {"ok": True, "channel": source, "to_dict": lambda self: {}})()

    monkeypatch.setattr(
        "app.services.notify.notify_user_text",
        _fake_notify_user_text,
        raising=True,
    )
    return sent


async def _seed_parked_task(user) -> str:
    """Spin up a task already at the awaiting_final_acceptance terminus
    with three completed stages so reject-from-stage has somewhere to go."""
    from app.database import async_session

    async with async_session() as s:
        t = PipelineTask(
            title="IM Acceptance",
            description="x",
            org_id=user.org_id,
            created_by=str(user.id),
            source="feishu",
            source_user_id="ou_test_open_id",
            status="awaiting_final_acceptance",
            current_stage_id="final_acceptance",
            final_acceptance_status="pending",
            template="full",
        )
        s.add(t)
        await s.flush()
        for idx, sid in enumerate(["research", "draft", "review"]):
            s.add(PipelineStage(
                task_id=t.id, stage_id=sid, label=sid.title(),
                sort_order=idx, status="done", output=f"out-{sid}",
            ))
        await s.commit()
        return str(t.id)


# ── intent classifier ───────────────────────────────────────────────────

def test_classify_accept_keywords():
    from app.api.gateway import _classify_final_acceptance_intent
    for kw in ["通过", "ok", "lgtm", "上线", "可以", "accept", "approve"]:
        assert _classify_final_acceptance_intent(kw) == "accept", kw


def test_classify_reject_keywords():
    from app.api.gateway import _classify_final_acceptance_intent
    for kw in ["重做", "改一下", "回炉", "reject", "不行", "打回"]:
        assert _classify_final_acceptance_intent(kw) == "reject", kw


def test_classify_reject_wins_on_mixed_message():
    """If user says 「通过但要改 X」 we MUST treat it as reject — accidentally
    publishing a not-ready build is the worst possible failure mode."""
    from app.api.gateway import _classify_final_acceptance_intent
    assert _classify_final_acceptance_intent("通过，但要再改改样式") == "reject"


def test_classify_unknown_returns_none():
    from app.api.gateway import _classify_final_acceptance_intent
    assert _classify_final_acceptance_intent("没看明白") is None
    assert _classify_final_acceptance_intent("") is None


# ── _apply_final_acceptance_from_im happy paths ─────────────────────────

@pytest.mark.asyncio
async def test_im_accept_marks_task_done(db, test_user, _stub_outbound_notify):
    from app.api.gateway import _apply_final_acceptance_from_im
    task_id = await _seed_parked_task(test_user)

    res = await _apply_final_acceptance_from_im(
        task_id=task_id, intent="accept",
        source="feishu", user_id="ou_test_open_id",
        raw_text="通过",
    )
    assert res["ok"] is True
    assert res["action"] == "final_accepted_from_im"
    assert res["by"].startswith("im:feishu:")

    from app.database import async_session
    from sqlalchemy import select
    import uuid as _uuid
    async with async_session() as s:
        row = await s.execute(
            select(PipelineTask).where(PipelineTask.id == _uuid.UUID(task_id))
        )
        t = row.scalar_one()
        assert t.status == "done"
        assert t.final_acceptance_status == "accepted"
        assert t.final_acceptance_by == "im:feishu:ou_test_open_id"
        assert t.final_acceptance_at is not None

    # User should have received a confirmation card
    titles = [m["title"] for m in _stub_outbound_notify]
    assert any("已上线" in t for t in titles)


@pytest.mark.asyncio
async def test_im_reject_without_stage_pauses(db, test_user, _stub_outbound_notify):
    from app.api.gateway import _apply_final_acceptance_from_im
    task_id = await _seed_parked_task(test_user)

    res = await _apply_final_acceptance_from_im(
        task_id=task_id, intent="reject",
        source="feishu", user_id="ou_test_open_id",
        raw_text="重做：登录页崩了",
    )
    assert res["ok"] is True
    assert res["action"] == "final_rejected_from_im"
    assert res["restartFromStage"] is None

    from app.database import async_session
    from sqlalchemy import select
    import uuid as _uuid
    async with async_session() as s:
        row = await s.execute(
            select(PipelineTask).where(PipelineTask.id == _uuid.UUID(task_id))
        )
        t = row.scalar_one()
        assert t.status == "paused"
        assert t.final_acceptance_status == "rejected"
        assert "登录页崩了" in (t.final_acceptance_feedback or "")


@pytest.mark.asyncio
async def test_im_reject_with_stage_hint_resets_downstream(
    db, test_user, _stub_outbound_notify,
):
    """``@stage:draft`` in the user's reply should reset draft + every
    later stage and put the task back to ``active`` so the DAG resumes."""
    from app.api.gateway import _apply_final_acceptance_from_im
    task_id = await _seed_parked_task(test_user)

    res = await _apply_final_acceptance_from_im(
        task_id=task_id, intent="reject",
        source="feishu", user_id="ou_test_open_id",
        raw_text="重做：草稿这块逻辑反了 @stage:draft",
    )
    assert res["ok"] is True
    assert res["restartFromStage"] == "draft"

    from app.database import async_session
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    import uuid as _uuid
    async with async_session() as s:
        row = await s.execute(
            select(PipelineTask)
            .options(selectinload(PipelineTask.stages))
            .where(PipelineTask.id == _uuid.UUID(task_id))
        )
        t = row.scalar_one()
        assert t.status == "active"
        assert t.current_stage_id == "draft"
        by_id = {st.stage_id: st for st in t.stages}
        assert by_id["research"].status == "done"     # untouched
        assert by_id["draft"].status == "pending"     # reset
        assert by_id["review"].status == "pending"    # downstream reset
        assert "草稿这块逻辑反了" in (by_id["draft"].last_error or "")


@pytest.mark.asyncio
async def test_im_reject_unknown_stage_falls_back_to_pause(
    db, test_user, _stub_outbound_notify,
):
    """``@stage:nonsense`` should be silently ignored (we have no way to
    surface a 400 in IM) and we fall back to a clean pause."""
    from app.api.gateway import _apply_final_acceptance_from_im
    task_id = await _seed_parked_task(test_user)
    res = await _apply_final_acceptance_from_im(
        task_id=task_id, intent="reject",
        source="feishu", user_id="ou_test_open_id",
        raw_text="重做：随便什么 @stage:nope",
    )
    assert res["restartFromStage"] is None

    from app.database import async_session
    from sqlalchemy import select
    import uuid as _uuid
    async with async_session() as s:
        row = await s.execute(
            select(PipelineTask).where(PipelineTask.id == _uuid.UUID(task_id))
        )
        t = row.scalar_one()
        assert t.status == "paused"


# ── status guard ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_im_accept_state_mismatch_when_task_not_parked(
    db, test_user, _stub_outbound_notify,
):
    """When the task isn't at the terminus we MUST refuse to flip it to
    ``done`` — protects against stale feedback racing the engine."""
    from app.api.gateway import _apply_final_acceptance_from_im
    from app.database import async_session

    async with async_session() as s:
        t = PipelineTask(
            title="Active Task", description="x",
            org_id=test_user.org_id, created_by=str(test_user.id),
            status="active",
        )
        s.add(t)
        await s.commit()
        task_id = str(t.id)

    res = await _apply_final_acceptance_from_im(
        task_id=task_id, intent="accept",
        source="feishu", user_id="ou_x",
        raw_text="通过",
    )
    assert res["ok"] is False
    assert res["action"] == "final_acceptance_state_mismatch"
    assert res["status"] == "active"


# ── _try_parse_feedback routing ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_try_parse_feedback_routes_to_final_accept(
    db, test_user, monkeypatch, _stub_outbound_notify,
):
    """A reply that looks like feedback AND lands on a parked task must
    short-circuit to ``_apply_final_acceptance_from_im`` instead of the
    legacy ``feedback_loop`` (which would have no effect on a done DAG)."""
    from app.api import gateway as gw

    task_id = await _seed_parked_task(test_user)

    # Make _resolve_feedback_task return our parked task without needing
    # a real gateway_binding redis lookup.
    async def _fake_resolve(text, source, user_id):
        return task_id, text
    monkeypatch.setattr(gw, "_resolve_feedback_task", _fake_resolve)

    # Sentinel: legacy feedback_loop must NOT be reached.
    called = {"legacy": False}

    class _FakeFeedback:
        @staticmethod
        async def parse_im_feedback(*a, **kw):
            called["legacy"] = True
            raise AssertionError("legacy feedback path should not run")

        @staticmethod
        async def process_feedback(*a, **kw):
            return {}

    monkeypatch.setattr(
        "app.services.interaction.feedback.feedback_loop",
        _FakeFeedback,
        raising=False,
    )

    res = await gw._try_parse_feedback("通过", "feishu", "ou_test_open_id")
    assert res is not None
    assert res["action"] == "final_accepted_from_im"
    assert called["legacy"] is False


# ── card-action button → state machine ──────────────────────────────────

@pytest.mark.asyncio
async def test_card_action_final_accept_button(
    db, test_user, monkeypatch, _stub_outbound_notify,
):
    from app.api.gateway import _handle_plan_card_action

    task_id = await _seed_parked_task(test_user)

    res = await _handle_plan_card_action(
        db, None,
        {
            "action": "final_accept",
            "source": "feishu",
            "user_id": "ou_test_open_id",
            "task_id": task_id,
        },
    )
    assert res["ok"] is True
    assert res["action"] == "final_accepted_from_im"

    from app.database import async_session
    from sqlalchemy import select
    import uuid as _uuid
    async with async_session() as s:
        row = await s.execute(
            select(PipelineTask).where(PipelineTask.id == _uuid.UUID(task_id))
        )
        t = row.scalar_one()
        assert t.status == "done"
        assert t.final_acceptance_status == "accepted"


@pytest.mark.asyncio
async def test_card_action_final_reject_button_pauses(
    db, test_user, monkeypatch, _stub_outbound_notify,
):
    from app.api.gateway import _handle_plan_card_action

    task_id = await _seed_parked_task(test_user)

    res = await _handle_plan_card_action(
        db, None,
        {
            "action": "final_reject",
            "source": "feishu",
            "user_id": "ou_test_open_id",
            "task_id": task_id,
        },
    )
    assert res["ok"] is True
    assert res["action"] == "final_rejected_from_im"
    assert res["restartFromStage"] is None  # no stage hint via button

    from app.database import async_session
    from sqlalchemy import select
    import uuid as _uuid
    async with async_session() as s:
        row = await s.execute(
            select(PipelineTask).where(PipelineTask.id == _uuid.UUID(task_id))
        )
        t = row.scalar_one()
        assert t.status == "paused"
        assert t.final_acceptance_status == "rejected"


@pytest.mark.asyncio
async def test_card_action_final_accept_missing_task_id(
    db, test_user, _stub_outbound_notify,
):
    """Defensive: a malformed button payload without task_id should fail
    cleanly, not crash the webhook."""
    from app.api.gateway import _handle_plan_card_action
    res = await _handle_plan_card_action(
        db, None,
        {
            "action": "final_accept",
            "source": "feishu",
            "user_id": "ou_x",
            "task_id": "",
        },
    )
    assert res["ok"] is False
    assert "no_task_id" in (res.get("reason") or "")
