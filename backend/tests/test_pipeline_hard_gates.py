"""Regression tests for hard delivery gates in the pipeline engine."""
from __future__ import annotations

from typing import Any, Dict

import pytest

from app.services.pipeline_engine import execute_stage

from .test_hero_pipeline_acceptance import (
    HERO_SENTENCE,
    _install_hero_pipeline_mocks,
)


async def _create_task(client, auth_headers, title: str) -> Dict[str, Any]:
    res = await client.post(
        "/api/pipeline/tasks",
        json={"title": title, "description": HERO_SENTENCE},
        headers=auth_headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["task"]


@pytest.mark.asyncio
async def test_testing_stage_blocks_when_real_qa_is_blocked(
    client, db, auth_headers, monkeypatch, tmp_path,
):
    stage_holder = _install_hero_pipeline_mocks(monkeypatch, tmp_path)

    async def _blocked_qa(_self):
        return {
            "ok": False,
            "blocked": True,
            "error": "qa_blocked_no_source_manifest",
            "resource_check": {
                "has_source_manifest": False,
                "node_available": True,
                "pnpm_available": True,
            },
        }

    monkeypatch.setattr("app.services.qa_executor.QaExecutor.run_full_qa", _blocked_qa)

    task = await _create_task(client, auth_headers, "[Hard gate] QA blocked")
    stage_holder["id"] = "testing"

    result = await execute_stage(
        db,
        task_id=task["id"],
        task_title=task["title"],
        task_description=HERO_SENTENCE,
        stage_id="testing",
        previous_outputs={"development": "## 实现说明\n已有代码。"},
    )

    assert result["ok"] is False
    assert result.get("blocked") is True
    assert "QA blocked" in result.get("error", "")


@pytest.mark.asyncio
async def test_testing_stage_fails_when_real_qa_fails(
    client, db, auth_headers, monkeypatch, tmp_path,
):
    stage_holder = _install_hero_pipeline_mocks(monkeypatch, tmp_path)

    async def _failed_qa(_self):
        return {
            "ok": False,
            "blocked": False,
            "failed_step": "browser_smoke",
            "error": "Browser smoke failed: page not reachable",
            "resource_check": {
                "has_source_manifest": True,
                "node_available": True,
                "pnpm_available": True,
            },
            "browser": {"page_opened": False, "error": "page not reachable"},
        }

    monkeypatch.setattr("app.services.qa_executor.QaExecutor.run_full_qa", _failed_qa)

    task = await _create_task(client, auth_headers, "[Hard gate] QA failed")
    stage_holder["id"] = "testing"

    result = await execute_stage(
        db,
        task_id=task["id"],
        task_title=task["title"],
        task_description=HERO_SENTENCE,
        stage_id="testing",
        previous_outputs={"development": "## 实现说明\n已有代码。"},
    )

    assert result["ok"] is False
    assert "QA failed at browser_smoke" in result.get("error", "")


@pytest.mark.asyncio
async def test_deployment_stage_blocks_when_no_deploy_channel(
    client, db, auth_headers, monkeypatch, tmp_path,
):
    stage_holder = _install_hero_pipeline_mocks(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "app.services.deploy.local_preview.check_deploy_resources",
        lambda: {"any_available": False, "local_available": False, "vercel_available": False},
    )

    task = await _create_task(client, auth_headers, "[Hard gate] No deploy channel")
    stage_holder["id"] = "deployment"

    result = await execute_stage(
        db,
        task_id=task["id"],
        task_title=task["title"],
        task_description=HERO_SENTENCE,
        stage_id="deployment",
        previous_outputs={"reviewing": "APPROVED\n"},
    )

    assert result["ok"] is False
    assert result.get("blocked") is True
    assert "No deploy channel" in result.get("error", "")


@pytest.mark.asyncio
async def test_local_preview_success_is_detached_not_closed(
    client, db, auth_headers, monkeypatch, tmp_path,
):
    stage_holder = _install_hero_pipeline_mocks(monkeypatch, tmp_path)
    calls = {"detach": 0, "close": 0}

    def _detach(_self):
        calls["detach"] += 1

    async def _close(_self):
        calls["close"] += 1

    monkeypatch.setattr("app.services.deploy.local_preview.LocalPreview.detach", _detach)
    monkeypatch.setattr("app.services.deploy.local_preview.LocalPreview.close", _close)

    task = await _create_task(client, auth_headers, "[Hard gate] Preview detach")
    stage_holder["id"] = "deployment"

    result = await execute_stage(
        db,
        task_id=task["id"],
        task_title=task["title"],
        task_description=HERO_SENTENCE,
        stage_id="deployment",
        previous_outputs={"reviewing": "APPROVED\n"},
    )

    assert result["ok"] is True
    assert calls["detach"] == 1
    assert calls["close"] == 0
