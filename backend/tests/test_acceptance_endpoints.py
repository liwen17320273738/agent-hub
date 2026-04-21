"""Tests for the wave-4 "acceptance stage" endpoints:

* GET/PUT  /pipeline/tasks/{id}/quality-gate-config — per-task gate overrides
* POST     /pipeline/tasks/{id}/final-accept       — final acceptance terminus
* POST     /pipeline/tasks/{id}/final-reject       — reject + restart-from-stage

Coverage focuses on the *contract* (status codes, persisted side-effects),
not the engine plumbing — engine paths live in their own integration tests.
"""
from __future__ import annotations

import pytest

from app.models.pipeline import PipelineTask, PipelineStage


# ── shared fixture: stub out the Redis-backed SSE emitter ───────────────
#
# emit_event() publishes via redis.publish(), which keeps a singleton
# connection bound to the *first* asyncio loop it runs on. When pytest
# tears that loop down between tests the cached connection blows up with
# "Event loop is closed" on the second test's POST. We don't actually
# care about SSE delivery in these unit tests — only the persisted
# side-effects on the row — so swap in a no-op for the test session.

@pytest.fixture(autouse=True)
def _stub_emit_event(monkeypatch):
    async def _noop(event, data):  # noqa: ANN001 — match real signature
        return None
    # Patch every import site:
    monkeypatch.setattr("app.services.sse.emit_event", _noop, raising=True)
    monkeypatch.setattr("app.api.pipeline.emit_event", _noop, raising=False)


# ── helpers ─────────────────────────────────────────────────────────────

async def _seed_completed_task(db, user) -> str:
    """Create a task that's parked at the final-acceptance terminus,
    with a few completed stages so reject-with-restart has somewhere to go.

    Uses a *fresh* async session rather than the ``db`` fixture because the
    httpx ASGI client opens its own session per request and co-mingling
    commits across two long-lived sessions confuses aiosqlite's connection
    pool ("Event loop is closed") when tests run in sequence on the
    in-memory shared DB."""
    from app.database import async_session

    async with async_session() as s:
        task = PipelineTask(
            title="Acceptance Test Task",
            description="x",
            org_id=user.org_id,
            created_by=str(user.id),
            status="awaiting_final_acceptance",
            current_stage_id="final_acceptance",
            final_acceptance_status="pending",
            template="full",
        )
        s.add(task)
        await s.flush()
        for idx, sid in enumerate(["research", "draft", "review"]):
            s.add(PipelineStage(
                task_id=task.id,
                stage_id=sid,
                label=sid.title(),
                sort_order=idx,
                status="done",
                output=f"output-{sid}",
            ))
        await s.commit()
        task_id = str(task.id)
    return task_id


# ── quality-gate-config ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_quality_gate_config_shape(client, db, test_user, auth_headers):
    """GET returns {taskId, template, stages: [{stageId, effective, overrides, hasOverrides}]}."""
    task_id = await _seed_completed_task(db, test_user)
    res = await client.get(
        f"/api/pipeline/tasks/{task_id}/quality-gate-config",
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["taskId"] == task_id
    assert body["template"] == "full"
    assert isinstance(body["stages"], list)
    # Every entry must carry the documented keys so the drawer can render
    # without optional-chaining gymnastics.
    for s in body["stages"]:
        assert "stageId" in s
        assert "effective" in s and isinstance(s["effective"], dict)
        # Camel-cased per API contract:
        assert "passThreshold" in s["effective"]
        assert "failThreshold" in s["effective"]
        assert "minLength" in s["effective"]
        assert "overrides" in s
        assert "hasOverrides" in s


@pytest.mark.asyncio
async def test_put_quality_gate_config_persists(client, db, test_user, auth_headers):
    """PUT stores the overrides blob and the next GET reflects it both as
    raw overrides AND merged into effective."""
    task_id = await _seed_completed_task(db, test_user)
    overrides = {
        "research": {"min_length": 1234, "pass_threshold": 0.42},
        "draft":    {"min_length": 555},
    }
    put_res = await client.put(
        f"/api/pipeline/tasks/{task_id}/quality-gate-config",
        json={"overrides": overrides},
        headers=auth_headers,
    )
    assert put_res.status_code == 200, put_res.text
    body = put_res.json()
    assert body["ok"] is True
    assert body["overrides"]["research"]["min_length"] == 1234
    assert body["overrides"]["research"]["pass_threshold"] == 0.42

    # Round-trip through GET
    get_res = await client.get(
        f"/api/pipeline/tasks/{task_id}/quality-gate-config",
        headers=auth_headers,
    )
    assert get_res.status_code == 200
    by_stage = {s["stageId"]: s for s in get_res.json()["stages"]}
    if "research" in by_stage:
        assert by_stage["research"]["overrides"].get("min_length") == 1234
        assert by_stage["research"]["effective"]["minLength"] == 1234
        assert by_stage["research"]["effective"]["passThreshold"] == 0.42
        assert by_stage["research"]["hasOverrides"] is True


@pytest.mark.asyncio
async def test_put_quality_gate_config_rejects_bad_threshold(
    client, db, test_user, auth_headers,
):
    task_id = await _seed_completed_task(db, test_user)
    res = await client.put(
        f"/api/pipeline/tasks/{task_id}/quality-gate-config",
        json={"overrides": {"research": {"pass_threshold": 1.7}}},
        headers=auth_headers,
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_put_quality_gate_config_requires_auth(client, db, test_user):
    task_id = await _seed_completed_task(db, test_user)
    res = await client.put(
        f"/api/pipeline/tasks/{task_id}/quality-gate-config",
        json={"overrides": {}},
    )
    assert res.status_code in (401, 403)


# ── final accept / reject ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_final_accept_marks_task_done(client, db, test_user, auth_headers):
    task_id = await _seed_completed_task(db, test_user)

    res = await client.post(
        f"/api/pipeline/tasks/{task_id}/final-accept",
        json={"notes": "LGTM"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["taskId"] == task_id
    assert body["acceptedAt"]

    follow = await client.get(f"/api/pipeline/tasks/{task_id}", headers=auth_headers)
    assert follow.status_code == 200
    t = follow.json()["task"]
    assert t["status"] == "done"
    # ORM column → JSON serializer keeps snake_case unless renamed; accept either.
    accepted_status = t.get("finalAcceptanceStatus") or t.get("final_acceptance_status")
    assert accepted_status == "accepted"
    assert (t.get("finalAcceptanceBy") or t.get("final_acceptance_by"))
    assert (t.get("finalAcceptanceAt") or t.get("final_acceptance_at"))


@pytest.mark.asyncio
async def test_final_accept_idempotent(client, db, test_user, auth_headers):
    """A second accept on an already-accepted task is a no-op (200 +
    alreadyAccepted=True) so the UI can suppress duplicate toasts."""
    task_id = await _seed_completed_task(db, test_user)
    await client.post(
        f"/api/pipeline/tasks/{task_id}/final-accept",
        json={}, headers=auth_headers,
    )
    res = await client.post(
        f"/api/pipeline/tasks/{task_id}/final-accept",
        json={}, headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body.get("alreadyAccepted") is True


@pytest.mark.asyncio
async def test_final_accept_rejects_wrong_status(client, db, test_user, auth_headers):
    """If the task isn't actually parked at the terminus we 400 — the UI
    almost certainly has a stale view."""
    task = PipelineTask(
        title="Active Task",
        description="x",
        org_id=test_user.org_id,
        created_by=str(test_user.id),
        status="active",
    )
    db.add(task)
    await db.flush()
    await db.commit()
    res = await client.post(
        f"/api/pipeline/tasks/{task.id}/final-accept",
        json={}, headers=auth_headers,
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_final_reject_without_restart_pauses(client, db, test_user, auth_headers):
    task_id = await _seed_completed_task(db, test_user)

    res = await client.post(
        f"/api/pipeline/tasks/{task_id}/final-reject",
        json={"reason": "缺少错误码列表"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body.get("paused") is True

    follow = await client.get(f"/api/pipeline/tasks/{task_id}", headers=auth_headers)
    t = follow.json()["task"]
    rs = t.get("finalAcceptanceStatus") or t.get("final_acceptance_status")
    fb = t.get("finalAcceptanceFeedback") or t.get("final_acceptance_feedback")
    assert rs == "rejected"
    assert fb == "缺少错误码列表"
    assert t["status"] == "paused"


@pytest.mark.asyncio
async def test_final_reject_with_restart_resets_downstream(
    client, db, test_user, auth_headers, monkeypatch,
):
    """Rejecting with restart_from_stage="draft" should:
    * mark the task rejected
    * reset the chosen stage AND every later one back to pending
    * leave earlier stages alone

    We stub the background re-run so the test doesn't try to actually
    invoke the DAG executor (and its model-provider calls) — we only care
    that the row mutations happened.
    """
    monkeypatch.setattr(
        "app.api.pipeline._resume_dag_after_reject",
        lambda *a, **kw: None,
        raising=True,
    )

    task_id = await _seed_completed_task(db, test_user)

    res = await client.post(
        f"/api/pipeline/tasks/{task_id}/final-reject",
        json={"reason": "rework draft", "restart_from_stage": "draft"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["restartFromStage"] == "draft"

    follow = await client.get(f"/api/pipeline/tasks/{task_id}", headers=auth_headers)
    stages = {
        (s.get("stageId") or s.get("stage_id")): s
        for s in follow.json()["task"]["stages"]
    }
    assert stages["research"]["status"] == "done"      # untouched
    assert stages["draft"]["status"] == "pending"      # reset
    assert stages["review"]["status"] == "pending"     # downstream reset


@pytest.mark.asyncio
async def test_final_reject_unknown_stage_400(client, db, test_user, auth_headers):
    task_id = await _seed_completed_task(db, test_user)
    res = await client.post(
        f"/api/pipeline/tasks/{task_id}/final-reject",
        json={"reason": "x", "restart_from_stage": "no-such-stage"},
        headers=auth_headers,
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_final_reject_requires_reason(client, db, test_user, auth_headers):
    task_id = await _seed_completed_task(db, test_user)
    res = await client.post(
        f"/api/pipeline/tasks/{task_id}/final-reject",
        json={"reason": ""},
        headers=auth_headers,
    )
    assert res.status_code in (400, 422)


@pytest.mark.asyncio
async def test_final_accept_unauthenticated(client, db, test_user):
    task_id = await _seed_completed_task(db, test_user)
    res = await client.post(
        f"/api/pipeline/tasks/{task_id}/final-accept",
        json={"notes": "x"},
    )
    assert res.status_code in (401, 403)
