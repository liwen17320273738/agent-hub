from __future__ import annotations

import pytest


def _plan_doc():
    return {
        "title": "Plan doc",
        "summary": "Review before execution",
        "steps": [
            {"no": 1, "title": "Scope", "role": "product", "estimate_min": 10},
            {"no": 2, "title": "Build", "role": "developer", "estimate_min": 30},
        ],
        "template": "full",
        "deploy_target": "vercel",
        "risks": ["scope drift"],
        "estimate_min_total": 40,
        "confidence": "medium",
    }


@pytest.mark.asyncio
async def test_get_plan_exposes_runtime_options(client, auth_headers):
    from app.services import plan_session

    await plan_session.save_plan(
        "openclaw",
        "Agent-phone",
        plan_session.make_payload(
            "Ship todo app",
            "Need plan first",
            _plan_doc(),
            metadata={"auto_final_accept": True, "source_message_id": "msg-123"},
        ),
    )

    res = await client.get("/api/plans/openclaw/Agent-phone", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["auto_final_accept"] is True
    assert body["source_message_id"] == "msg-123"


@pytest.mark.asyncio
async def test_resolve_plan_pending_without_redis(client, auth_headers, monkeypatch):
    """DB-only resolve when gateway:plan Redis key is gone (TTL / dev)."""
    from app.config import settings
    from app.services import plan_session

    async def _fake_make_plan(title: str, description: str):
        from app.services.planner import ExecutionPlan, PlanStep

        return ExecutionPlan(
            title=title,
            summary=description[:80],
            steps=[PlanStep(no=1, title="A", role="dev", estimate_min=5)],
            template="full",
            deploy_target="vercel",
            risks=[],
            estimate_min_total=5,
            confidence="medium",
        )

    called: dict = {}

    async def _fake_run(task_id: str, title: str, description: str, *, pause_for_acceptance: bool = True):
        called["task_id"] = task_id

    monkeypatch.setattr(settings, "pipeline_api_key", "test-secret", raising=False)
    monkeypatch.setattr("app.services.planner.make_plan", _fake_make_plan, raising=True)
    monkeypatch.setattr("app.api.gateway._run_pipeline_background", _fake_run, raising=True)

    intake = await client.post(
        "/api/gateway/openclaw/intake",
        headers={"Authorization": "Bearer test-secret"},
        json={
            "title": "Ship app",
            "description": "Plan first",
            "source": "web",
            "userId": "dashboard",
            "planMode": True,
        },
    )
    assert intake.status_code == 200, intake.text
    task_id = intake.json()["taskId"]

    await plan_session.clear_plan("web", "dashboard")
    assert await plan_session.load_plan("web", "dashboard") is None

    res = await client.post(
        f"/api/pipeline/tasks/{task_id}/resolve-plan-pending",
        headers=auth_headers,
        json={"approved": True},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["action"] == "plan_approved"
    assert body["taskId"] == task_id
    assert called.get("task_id") == task_id


@pytest.mark.asyncio
async def test_approve_plan_reuses_gateway_pending_task(client, auth_headers, monkeypatch):
    """Web /plans/approve must reuse the task created by plan-mode intake (metadata.pending_task_id)."""
    from app.config import settings
    from app.services import plan_session
    async def _fake_make_plan(title: str, description: str):
        from app.services.planner import ExecutionPlan, PlanStep

        return ExecutionPlan(
            title=title,
            summary=description[:80],
            steps=[PlanStep(no=1, title="A", role="dev", estimate_min=5)],
            template="full",
            deploy_target="vercel",
            risks=[],
            estimate_min_total=5,
            confidence="medium",
        )

    called: dict = {}

    async def _fake_run(task_id: str, title: str, description: str, *, pause_for_acceptance: bool = True):
        called["task_id"] = task_id

    monkeypatch.setattr(settings, "pipeline_api_key", "test-secret", raising=False)
    monkeypatch.setattr("app.services.planner.make_plan", _fake_make_plan, raising=True)
    monkeypatch.setattr("app.api.gateway._run_pipeline_background", _fake_run, raising=True)

    intake = await client.post(
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
    assert intake.status_code == 200, intake.text
    pending_tid = intake.json()["taskId"]

    res = await client.post(
        "/api/plans/openclaw/Agent-phone/approve",
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["taskId"] == pending_tid
    assert body["action"] == "plan_approved"
    assert called.get("task_id") == pending_tid

    detail = await client.get(f"/api/pipeline/tasks/{pending_tid}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["task"]["status"] == "active"

    leftover = await plan_session.load_plan("openclaw", "Agent-phone")
    assert leftover is None


@pytest.mark.asyncio
async def test_revise_plan_preserves_runtime_options(client, auth_headers, monkeypatch):
    from app.services import plan_session
    from app.services.planner import ExecutionPlan, PlanStep

    async def _fake_make_plan(title: str, description: str):
        return ExecutionPlan(
            title=f"{title} revised",
            summary=description[:100],
            steps=[
                PlanStep(no=1, title="Revise", role="product", estimate_min=12),
                PlanStep(no=2, title="Execute", role="developer", estimate_min=28),
            ],
            template="full",
            deploy_target="vercel",
            risks=["timeline"],
            estimate_min_total=40,
            confidence="medium",
        )

    monkeypatch.setattr("app.services.planner.make_plan", _fake_make_plan, raising=True)

    await plan_session.save_plan(
        "openclaw",
        "Agent-phone",
        plan_session.make_payload(
            "Ship todo app",
            "Need plan first",
            _plan_doc(),
            metadata={"auto_final_accept": True, "source_message_id": "msg-123"},
        ),
    )

    res = await client.post(
        "/api/plans/openclaw/Agent-phone/revise",
        headers=auth_headers,
        json={"feedback": "改成 React"},
    )
    assert res.status_code == 200, res.text

    pending = await plan_session.load_plan("openclaw", "Agent-phone")
    assert pending is not None
    assert pending["metadata"]["auto_final_accept"] is True
    assert pending["metadata"]["source_message_id"] == "msg-123"
    assert pending["rotation_count"] == 1
