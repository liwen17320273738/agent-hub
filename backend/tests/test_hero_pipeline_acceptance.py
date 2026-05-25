"""Hero Path pipeline acceptance — real ``execute_stage`` + quality contract.

Unlike ``test_hero_delivery_path.py`` (state-machine smoke via ``/advance``),
this drives the actual pipeline engine with mocked LLM / external tools and
asserts v2 artifacts are written by the engine (not manual API stubs) and
pass the quality-aware artifact contract.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("AGENTHUB_TEST_MINIMAL_LIFESPAN", "1")
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.services.artifact_contract import build_task_contract_report
from app.services.cost_governor import BudgetDecision
from app.services.pipeline_engine import execute_stage

HERO_SENTENCE = "做一个待办事项看板，支持新增、完成、删除任务。"

CORE_STAGES = (
    "planning",
    "design",
    "architecture",
    "development",
    "testing",
    "reviewing",
    "deployment",
)

_PRD = (
    "## 范围\n"
    "待办看板 MVP：支持新增、完成、删除任务；首版 Web SPA，不含账号与多端同步。\n\n"
    "## 用户故事\n"
    "- US1 新增任务\n- US2 标记完成\n- US3 删除任务\n\n"
    "## 验收标准\n"
    "- AC1 列表 CRUD 可用\n- AC2 空状态与错误提示可见\n\n"
    "## 非目标\n"
    "- 团队协作\n- 移动端原生应用\n\n"
)

HERO_LLM_OUTPUTS: Dict[str, str] = {
    "planning": _PRD,
    "design": (
        "## UI 规格\n"
        "主区域为待办列表；右下角 FAB 新建；每项含标题、完成勾选、删除按钮；"
        "支持空状态与加载中状态。\n"
    ),
    "architecture": (
        "## 技术方案\n"
        "Vue 3 + Vite + Pinia + Vue Router；组件 TodoList / TodoItem / TodoForm；"
        "状态本地持久化至 localStorage。\n"
    ),
    "development": "## 实现说明\nTodoList 组件完成 CRUD，Pinia store 管理 items。\n",
    "testing": "## 测试摘要\npnpm install/build/test 全部通过；浏览器 smoke 截图已采集。\n",
    "reviewing": "## 验收记录\n- [x] PRD AC1 CRUD\n- [x] PRD AC2 空状态\n",
    "deployment": (
        "## 运维手册\n"
        "预览：`pnpm preview`；回滚：保留上一构建产物；健康检查 GET /。\n"
    ),
}


def _install_hero_pipeline_mocks(monkeypatch: pytest.MonkeyPatch, asset_dir: Path) -> Dict[str, str]:
    """Mock LLM + Phase 5/6/7 external deps; keep real execute_stage + artifact writer."""
    monkeypatch.setattr(settings, "artifact_store_v2", True)
    monkeypatch.setattr(settings, "artifact_contract_enforce", True)
    monkeypatch.setattr(settings, "ruflo_enabled", False)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-hero-acceptance")
    monkeypatch.setattr(settings, "llm_api_key", "sk-test-hero-acceptance")
    monkeypatch.setattr(settings, "llm_api_url", "http://mock-llm.test/v1")
    monkeypatch.setattr(
        "app.services.llm_router.get_provider_health",
        lambda: {"openai": True},
    )

    async def _budget_ok(*_a: Any, **_k: Any) -> BudgetDecision:
        return BudgetDecision(action="ok")

    monkeypatch.setattr("app.services.cost_governor.pre_check_budget", _budget_ok)

    stage_holder: Dict[str, str] = {"id": "planning"}

    async def _fake_llm(**kwargs: Any) -> Dict[str, Any]:
        sid = stage_holder["id"]
        content = HERO_LLM_OUTPUTS.get(sid, f"## {sid}\nhero acceptance stub\n")
        return {
            "content": content,
            "model": "mock-hero",
            "provider": "openai",
            "usage": {"prompt_tokens": 12, "completion_tokens": 48},
        }

    monkeypatch.setattr(
        "app.services.llm_router.chat_completion_with_fallback",
        _fake_llm,
    )
    monkeypatch.setattr("app.services.agent_runtime.chat_completion", _fake_llm)
    monkeypatch.setattr("app.services.pipeline_engine.llm_chat_with_fallback", _fake_llm)

    async def _fake_runtime_execute(self, db, **kwargs: Any) -> Dict[str, Any]:
        sid = stage_holder["id"]
        content = HERO_LLM_OUTPUTS.get(sid, f"## {sid}\nhero acceptance stub\n")
        return {"ok": True, "content": content, "steps": 1}

    monkeypatch.setattr("app.services.agent_runtime.AgentRuntime.execute", _fake_runtime_execute)

    async def _noop_top_up(**_kwargs: Any) -> str:
        return _kwargs.get("partial_content") or ""

    monkeypatch.setattr("app.services.pipeline_engine._top_up_stage_output", _noop_top_up)
    monkeypatch.setattr("app.services.pipeline_engine.detect_build_command", lambda _wt: None)

    png_path = asset_dir / "ui-mockup.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    html_path = asset_dir / "ui-prototype.html"
    html_path.write_text("<!doctype html><html><body>Todo</body></html>", encoding="utf-8")
    arch_html = asset_dir / "architecture.html"
    arch_html.write_text("<!doctype html><html><body>arch</body></html>", encoding="utf-8")
    qa_png = asset_dir / "qa-screenshot.png"
    qa_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x01" * 64)
    deploy_png = asset_dir / "deploy-screenshot.png"
    deploy_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x02" * 64)

    async def _rc_ok(_self, *_a: Any, **_k: Any) -> Dict[str, Any]:
        return {"ok": True, "available": ["html"], "fallbacks": True, "channels": {"html": True}}

    async def _mock_mockup(
        _self,
        *,
        task_id: str,
        stage_id: str,
        design_spec: str,
        project_name: str,
        **_k: Any,
    ):
        return {
            "ok": True,
            "imagePath": str(png_path),
            "htmlPath": str(html_path),
            "prompt": "hero-acceptance",
        }

    async def _mock_arch_all(
        _self,
        *,
        task_id: str,
        stage_id: str,
        arch_spec: str,
        project_name: str,
        **_k: Any,
    ):
        return {
            "diagram": {
                "ok": True,
                "htmlPath": str(arch_html),
                "mermaidRaw": {"architecture": "flowchart LR\n  User-->Vue"},
                "componentCount": 2,
                "flowCount": 1,
            },
            "consistency_ok": True,
            "consistency_issues": [],
            "api_contract": {"endpoints": ["/api/todos"]},
            "data_model": {"tables": ["todos"]},
            "file_plan": {"dirs": ["src/"]},
        }

    monkeypatch.setattr("app.services.ui_visualizer.UiVisualizer.check_design_resources", _rc_ok)
    monkeypatch.setattr("app.services.ui_visualizer.UiVisualizer.check_diagram_resources", _rc_ok)
    monkeypatch.setattr("app.services.ui_visualizer.UiVisualizer.generate_mockup", _mock_mockup)
    monkeypatch.setattr(
        "app.services.ui_visualizer.UiVisualizer.generate_all_architecture_artifacts",
        _mock_arch_all,
    )
    monkeypatch.setattr("app.services.ui_visualizer.UiVisualizer.generate_design_tokens", lambda _self, _c: {})
    monkeypatch.setattr("app.services.ui_visualizer.UiVisualizer.generate_screen_plan", lambda _self, _c: {})

    async def _fake_codegen(self, task_id, task_title, pipeline_outputs, **kwargs: Any):
        project_dir = kwargs.get("existing_project_dir")
        if not project_dir or not os.path.isdir(project_dir):
            return {"ok": False, "error": "missing worktree"}
        src = os.path.join(project_dir, "src")
        os.makedirs(src, exist_ok=True)
        app_vue = os.path.join(src, "App.vue")
        with open(app_vue, "w", encoding="utf-8") as f:
            f.write("<template><div class=\"todo-app\">Todo</div></template>\n")
        manifest = {
            "created_files": ["src/App.vue"],
            "build_command": "pnpm install && pnpm build && pnpm test",
            "run_command": "pnpm preview",
            "test_command": "pnpm test",
        }
        with open(os.path.join(project_dir, "source_manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        with open(os.path.join(project_dir, "build.log"), "w", encoding="utf-8") as f:
            f.write("pnpm install\nexit code: 0\npnpm build\nexit code: 0\n")
        return {
            "ok": True,
            "files_written": ["src/App.vue"],
            "job_id": "hero-acceptance-codegen",
            "engine": "test-double",
            "claude_output": "codegen ok",
            "build_success": True,
        }

    monkeypatch.setattr(
        "app.services.codegen.codegen_agent.CodeGenAgent.generate_from_pipeline",
        _fake_codegen,
    )

    async def _fake_claude_code(**_kwargs: Any) -> Dict[str, Any]:
        return {"ok": True, "output": "hero acceptance claude stub", "job_id": "hero-claude"}

    monkeypatch.setattr("app.services.executor_bridge.execute_claude_code", _fake_claude_code)

    async def _fake_qa(_self):
        return {
            "ok": True,
            "blocked": False,
            "resource_check": {
                "node_available": True,
                "pnpm_available": True,
                "playwright_available": True,
                "has_source_manifest": True,
            },
            "install": {
                "command": "pnpm install",
                "exit_code": 0,
                "duration_ms": 800,
                "ok": True,
                "stdout_summary": "packages installed",
                "stderr_summary": "",
            },
            "build": {
                "command": "pnpm build",
                "exit_code": 0,
                "duration_ms": 2200,
                "ok": True,
                "stdout_summary": "build ok",
                "stderr_summary": "",
            },
            "test": {
                "command": "pnpm test",
                "exit_code": 0,
                "duration_ms": 1500,
                "ok": True,
                "stdout_summary": "tests passed",
                "stderr_summary": "",
            },
            "browser": {
                "page_opened": True,
                "status_code": 200,
                "screenshot_path": str(qa_png),
                "console_errors": [],
                "page_text_preview": "Todo",
            },
        }

    monkeypatch.setattr("app.services.qa_executor.QaExecutor.run_full_qa", _fake_qa)

    monkeypatch.setattr(
        "app.services.deploy.local_preview.check_deploy_resources",
        lambda: {"any_available": True, "local": True, "vercel": False},
    )

    async def _fake_local_deploy(_self):
        return MagicMock(
            ok=True,
            url="http://127.0.0.1:4173/",
            health_status="healthy",
            deployed_at="2026-05-20T00:00:00Z",
            screenshot_path=str(deploy_png),
            error="",
            port_used=4173,
        )

    async def _fake_close(_self):
        return None

    monkeypatch.setattr("app.services.deploy.local_preview.LocalPreview.deploy", _fake_local_deploy)
    monkeypatch.setattr("app.services.deploy.local_preview.LocalPreview.close", _fake_close)

    return stage_holder


@pytest.mark.asyncio
async def test_hero_pipeline_execute_stage_passes_quality_contract(
    client, db, auth_headers, monkeypatch, tmp_path,
):
    stage_holder = _install_hero_pipeline_mocks(monkeypatch, tmp_path)

    create_res = await client.post(
        "/api/pipeline/tasks",
        json={
            "title": "[Hero acceptance] Todo board",
            "description": HERO_SENTENCE,
        },
        headers=auth_headers,
    )
    assert create_res.status_code == 201, create_res.text
    task = create_res.json()["task"]
    task_id = task["id"]
    title = task["title"]

    previous: Dict[str, str] = {}
    for sid in CORE_STAGES:
        stage_holder["id"] = sid
        t0 = time.monotonic()
        result = await execute_stage(
            db,
            task_id=task_id,
            task_title=title,
            task_description=HERO_SENTENCE,
            stage_id=sid,
            previous_outputs=dict(previous),
        )
        elapsed = time.monotonic() - t0
        assert result.get("ok") is True, f"stage {sid} failed after {elapsed:.1f}s: {result}"
        previous[sid] = result.get("content") or ""

    await db.commit()

    contract = await build_task_contract_report(db, task_id)
    assert contract.get("all_required_satisfied") is True, contract

    for sid in CORE_STAGES:
        block = contract["stages"][sid]
        assert block["ok"] is True, f"stage {sid} contract: {block}"
        assert not block.get("missing"), sid
        assert not block.get("invalid"), sid

    lst = await client.get(f"/api/tasks/{task_id}/artifacts", headers=auth_headers)
    assert lst.status_code == 200
    by_key = {x["type_key"]: x for x in lst.json().get("artifacts", [])}
    for required in (
        "brief",
        "prd",
        "ui_spec",
        "ui_mockup",
        "architecture",
        "architecture_diagram",
        "implementation",
        "code_link",
        "source_manifest",
        "build_log",
        "test_report",
        "screenshot",
        "acceptance",
        "preview_url",
        "deploy_manifest",
        "ops_runbook",
    ):
        row = by_key.get(required)
        assert row and row.get("has_content"), f"missing artifact content: {required}"
