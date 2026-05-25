"""Artifact contract quality gates — reject mock/stub delivery rows."""
from __future__ import annotations

import pytest

from app.models.pipeline import PipelineTask
from app.services.artifact_contract import (
    artifact_quality_errors,
    build_task_contract_report,
)
from app.services.artifact_writer import _write_one_artifact


@pytest.mark.parametrize(
    "content",
    [
        "PNG placeholder for UI mockup.\n",
        "[HERO_PATH_E2E_MOCK] pnpm build\nexit code: 0\n",
        '{"url":"http://127.0.0.1:4173/mock-preview","provider":"mock-local"}\n',
    ],
)
def test_artifact_quality_errors_reject_mock_markers(content: str):
    errs = artifact_quality_errors("ui_mockup", "image", content)
    assert errs


@pytest.mark.asyncio
async def test_quality_contract_passes_real_visual_and_diagram(db, test_user):
    task = PipelineTask(
        title="Quality contract pass",
        description="anti-mock",
        org_id=test_user.org_id,
        created_by=str(test_user.id),
    )
    db.add(task)
    await db.flush()
    tid = str(task.id)

    prd = (
        "## 范围\n待办看板 MVP，支持新增、完成、删除任务；首版仅 Web 端，不含账号体系与多端同步。\n\n"
        "## 用户故事\n- US1 新增\n- US2 完成\n- US3 删除\n\n"
        "## 验收标准\n- AC1 CRUD 可用\n- AC2 空状态与错误提示可见\n\n"
        "## 非目标\n- 多端同步\n- 团队协作\n\n"
    )
    await _write_one_artifact(db, tid, "planning", "brief", "## 简报\n待办看板需求摘要，供设计与开发阶段对齐范围与验收标准。\n", "docs/00-brief.md")
    await _write_one_artifact(db, tid, "planning", "prd", prd, "docs/01-prd.md")
    await _write_one_artifact(
        db,
        tid,
        "design",
        "ui_spec",
        "## UI 规格\n主列表区展示待办项，右下角 FAB 新建；每项含完成勾选与删除操作。\n",
        "docs/02-ui-spec.md",
    )
    await _write_one_artifact(
        db,
        tid,
        "design",
        "ui_mockup",
        "data:image/png;base64,iVBORw0KGgo=",
        "screenshots/ui-mockup.png",
        metadata_json={"filePath": "screenshots/ui-mockup.png"},
    )
    await _write_one_artifact(
        db,
        tid,
        "architecture",
        "architecture",
        "## 架构\nVue 3 + Vite SPA；Pinia 管理待办状态；Vue Router 负责页面路由与深链；组件层拆分列表、表单与空状态。\n",
        "docs/03-architecture.md",
    )
    await _write_one_artifact(
        db,
        tid,
        "architecture",
        "architecture_diagram",
        "```mermaid\nflowchart LR\n  U[User]-->V[Vue SPA]\n```\n",
        "docs/architecture.html",
        metadata_json={"filePath": "docs/architecture.html"},
    )
    await db.commit()

    report = await build_task_contract_report(db, tid)
    assert report["stages"]["planning"]["ok"] is True
    assert report["stages"]["design"]["ok"] is True
    assert report["stages"]["architecture"]["ok"] is True
    assert report["all_required_satisfied"] is False  # dev/testing/deploy still empty


@pytest.mark.asyncio
async def test_quality_contract_flags_mock_hero_bundle(db, test_user):
    task = PipelineTask(
        title="Quality contract mock",
        description="hero mock bundle",
        org_id=test_user.org_id,
        created_by=str(test_user.id),
    )
    db.add(task)
    await db.flush()
    tid = str(task.id)

    await _write_one_artifact(
        db, tid, "design", "ui_mockup", "PNG placeholder for UI mockup.\n", "ui_mockup.txt",
    )
    await _write_one_artifact(
        db,
        tid,
        "testing",
        "build_log",
        "[HERO_E2E] pnpm build: exit 0\n",
        "build.log",
    )
    await db.commit()

    report = await build_task_contract_report(db, tid)
    design = report["stages"]["design"]
    assert design["ok"] is False
    assert "ui_mockup" in design["invalid"]
    assert report["all_required_satisfied"] is False
