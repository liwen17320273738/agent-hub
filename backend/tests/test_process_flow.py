"""进程内调度流程测试 — TaskScheduler + Pipeline 投递闭环.

验证：
  * ``POST .../smart-run`` / ``POST .../auto-run`` 将工作交给全局调度器；
  * 后台协程结束后 ``lifetime.finished`` 递增；
  * ``GET /api/scheduler/status`` 与 ``get_scheduler().status()`` 一致。

不调用真实 LLM：对 ``run_smart_pipeline`` / ``execute_full_pipeline`` 做 monkeypatch。
"""
from __future__ import annotations

import asyncio

import pytest

from app.services.task_scheduler import get_scheduler


async def _wait_for_finished_increment(
    before_finished: int,
    *,
    timeout_s: float = 5.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        st = get_scheduler().status()
        if st["lifetime"]["finished"] > before_finished:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(
        f"scheduler lifetime.finished did not exceed {before_finished} within {timeout_s}s"
    )


@pytest.mark.asyncio
async def test_process_flow_smart_run_scheduler_lifetime(
    client, db, auth_headers, monkeypatch,
):
    async def _noop_smart_pipeline(db, task_id, title, description):
        return {"ok": True, "task_id": task_id}

    monkeypatch.setattr(
        "app.services.lead_agent.run_smart_pipeline",
        _noop_smart_pipeline,
    )

    before = get_scheduler().status()["lifetime"]["finished"]
    before_failed = get_scheduler().status()["lifetime"]["failed"]

    t = await client.post(
        "/api/pipeline/tasks",
        json={"title": "Process flow smart-run", "description": ""},
        headers=auth_headers,
    )
    assert t.status_code == 201, t.text
    task_id = t.json()["task"]["id"]

    r = await client.post(
        f"/api/pipeline/tasks/{task_id}/smart-run",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert body.get("submissionId")

    await _wait_for_finished_increment(before)

    after = get_scheduler().status()["lifetime"]
    assert after["finished"] >= before + 1
    assert after["failed"] == before_failed


@pytest.mark.asyncio
async def test_process_flow_auto_run_scheduler_lifetime(
    client, db, auth_headers, monkeypatch,
):
    async def _noop_full_pipeline(db, **kwargs):
        return {"ok": True}

    monkeypatch.setattr(
        "app.services.pipeline_engine.execute_full_pipeline",
        _noop_full_pipeline,
    )

    before = get_scheduler().status()["lifetime"]["finished"]

    t = await client.post(
        "/api/pipeline/tasks",
        json={"title": "Process flow auto-run", "description": ""},
        headers=auth_headers,
    )
    assert t.status_code == 201, t.text
    task_id = t.json()["task"]["id"]

    r = await client.post(
        f"/api/pipeline/tasks/{task_id}/auto-run",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("submissionId")

    await _wait_for_finished_increment(before)

    st = get_scheduler().status()
    assert st["lifetime"]["finished"] >= before + 1


@pytest.mark.asyncio
async def test_process_flow_scheduler_api_matches_singleton(
    client, db, auth_headers,
):
    api = await client.get("/api/scheduler/status", headers=auth_headers)
    assert api.status_code == 200
    direct = get_scheduler().status()
    data = api.json()
    assert data["runningCount"] == direct["runningCount"]
    assert data["queueDepth"] == direct["queueDepth"]
    assert data["lifetime"]["submitted"] == direct["lifetime"]["submitted"]
    assert data["lifetime"]["finished"] == direct["lifetime"]["finished"]
    assert data["lifetime"]["failed"] == direct["lifetime"]["failed"]
