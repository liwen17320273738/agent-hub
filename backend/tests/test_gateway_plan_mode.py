from __future__ import annotations

import pytest


def _plan_fixture(title: str = "Plan Task"):
    from app.services.planner import ExecutionPlan, PlanStep

    return ExecutionPlan(
        title=title,
        summary="Generate a plan before execution.",
        steps=[
            PlanStep(no=1, title="Clarify scope", role="product", estimate_min=10),
            PlanStep(no=2, title="Build feature", role="developer", estimate_min=30),
            PlanStep(no=3, title="Verify output", role="qa", estimate_min=15),
            PlanStep(no=4, title="Deploy preview", role="devops", estimate_min=10),
        ],
        template="full",
        deploy_target="vercel",
        risks=["Scope may change"],
        estimate_min_total=65,
        confidence="medium",
    )


@pytest.mark.asyncio
async def test_openclaw_plan_mode_returns_pending_plan(client, monkeypatch):
    from app.config import settings
    from app.services import plan_session

    async def _fake_make_plan(title: str, description: str):
        return _plan_fixture(title)

    monkeypatch.setattr(settings, "pipeline_api_key", "test-secret", raising=False)
    monkeypatch.setattr("app.services.planner.make_plan", _fake_make_plan, raising=True)

    res = await client.post(
        "/api/gateway/openclaw/intake",
        headers={"Authorization": "Bearer test-secret"},
        json={
            "title": "Ship a todo app",
            "description": "Need plan first",
            "source": "openclaw",
            "userId": "Agent-phone",
            "planMode": True,
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["action"] == "plan_pending"
    assert body["pipelineTriggered"] is False
    assert body["planMode"] is True
    assert body["planSession"]["source"] == "openclaw"
    assert body["planSession"]["userId"] == "Agent-phone"
    assert body["planSession"]["links"]["approve"].endswith("/api/gateway/openclaw/plans/openclaw/Agent-phone/approve")

    pending = await plan_session.load_plan("openclaw", "Agent-phone")
    assert pending is not None
    assert pending["title"] == "Ship a todo app"


@pytest.mark.asyncio
async def test_openclaw_plan_approve_preserves_auto_final_accept(
    client, db, monkeypatch,
):
    from app.config import settings
    from app.models.pipeline import PipelineTask
    from app.services import plan_session
    from sqlalchemy import select

    called = {}

    async def _fake_run(task_id: str, title: str, description: str, *, pause_for_acceptance: bool = True):
        called["task_id"] = task_id
        called["pause_for_acceptance"] = pause_for_acceptance

    monkeypatch.setattr(settings, "pipeline_api_key", "test-secret", raising=False)
    monkeypatch.setattr("app.api.gateway._run_pipeline_background", _fake_run, raising=True)

    await plan_session.save_plan(
        "openclaw",
        "Agent-phone",
        plan_session.make_payload(
            "Ship a todo app",
            "Need plan first",
            _plan_fixture("Ship a todo app").to_dict(),
            metadata={"auto_final_accept": True, "source_message_id": "msg-123"},
        ),
    )

    res = await client.post(
        "/api/gateway/openclaw/plans/openclaw/Agent-phone/approve",
        headers={"Authorization": "Bearer test-secret"},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["action"] == "plan_approved"
    assert body["pipelineTriggered"] is True
    assert body["autoFinalAccept"] is True
    assert called["pause_for_acceptance"] is False

    result = await db.execute(select(PipelineTask).where(PipelineTask.id == body["taskId"]))
    task = result.scalar_one()
    assert task.auto_final_accept is True
    assert task.source_message_id == "msg-123"


@pytest.mark.asyncio
async def test_openclaw_plan_revise_regenerates_plan(client, monkeypatch):
    from app.config import settings
    from app.services import plan_session

    async def _fake_make_plan(title: str, description: str):
        if "React" in description:
            plan = _plan_fixture(f"{title} React")
            plan.summary = "Adjusted to use React."
            return plan
        return _plan_fixture(title)

    monkeypatch.setattr(settings, "pipeline_api_key", "test-secret", raising=False)
    monkeypatch.setattr("app.services.planner.make_plan", _fake_make_plan, raising=True)

    await plan_session.save_plan(
        "openclaw",
        "Agent-phone",
        plan_session.make_payload(
            "Ship a todo app",
            "Need plan first",
            _plan_fixture("Ship a todo app").to_dict(),
            metadata={"auto_final_accept": False},
        ),
    )

    res = await client.post(
        "/api/gateway/openclaw/plans/openclaw/Agent-phone/revise",
        headers={"Authorization": "Bearer test-secret"},
        json={"feedback": "改成 React 技术栈"},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["action"] == "plan_pending"
    assert body["pipelineTriggered"] is False
    assert body["rotation_count"] == 1
    assert "React" in body["plan"]["title"]

    pending = await plan_session.load_plan("openclaw", "Agent-phone")
    assert pending is not None
    assert pending["rotation_count"] == 1
