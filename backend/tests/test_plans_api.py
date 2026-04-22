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
        "wayne-phone",
        plan_session.make_payload(
            "Ship todo app",
            "Need plan first",
            _plan_doc(),
            metadata={"auto_final_accept": True, "source_message_id": "msg-123"},
        ),
    )

    res = await client.get("/api/plans/openclaw/wayne-phone", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["auto_final_accept"] is True
    assert body["source_message_id"] == "msg-123"


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
        "wayne-phone",
        plan_session.make_payload(
            "Ship todo app",
            "Need plan first",
            _plan_doc(),
            metadata={"auto_final_accept": True, "source_message_id": "msg-123"},
        ),
    )

    res = await client.post(
        "/api/plans/openclaw/wayne-phone/revise",
        headers=auth_headers,
        json={"feedback": "改成 React"},
    )
    assert res.status_code == 200, res.text

    pending = await plan_session.load_plan("openclaw", "wayne-phone")
    assert pending is not None
    assert pending["metadata"]["auto_final_accept"] is True
    assert pending["metadata"]["source_message_id"] == "msg-123"
    assert pending["rotation_count"] == 1
