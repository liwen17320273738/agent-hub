"""E2E 测试：无 API Key 环境下的降级路径验证。

验证 pipeline 在没有任何外部 API Key（OpenAI、Gemini 等）配置时：
1. 资源检查正确标记为 degraded 模式
2. UI mockup 只产出 HTML 保底，不谎报 ok
3. 架构图资源检查标记 CDN-only 降级
4. 全链路 pipeline advance 不阻塞，但 degraded 标记可追溯
5. artifact_contract_rules_strict 正确拒绝低质量内容
6. artifact_contract_rules_strict 正确接受合规内容

这些测试填补了 analysis/pipeline-quality-issues.md 中识别的 P1-6 盲区：
"缺乏无 API Key 环境的端到端测试"。
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import zipfile
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.asyncio


# ── 辅助函数 ──────────────────────────────────────────────────────────────


def _clear_api_keys() -> dict:
    """清除所有 LLM/图片生成相关的 API Key 环境变量。"""
    cleared = {}
    keys_to_clear = [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
        "GOOGLE_API_KEY", "GEMINI_API_KEY", "ZHIPU_API_KEY",
        "QWEN_API_KEY", "LLM_API_KEY", "ANTHROPIC_AUTH_TOKEN",
        "HF_API_KEY", "FIRECRAWL_API_KEY", "VERCEL_TOKEN",
        "FIGMA_ACCESS_TOKEN",
    ]
    for k in keys_to_clear:
        if k in os.environ:
            cleared[k] = os.environ[k]
        os.environ[k] = ""
    return cleared


def _restore_api_keys(cleared: dict):
    """恢复被清除的环境变量。"""
    for k, v in cleared.items():
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


# ── Task 1: 资源检查降级 — 设计阶段 ──────────────────────────────────────


class TestDesignResourceCheckDegraded:

    async def test_check_design_resources_degraded_without_api_keys(self):
        """无任何 API Key 时，check_design_resources 返回 ok=True 但 degraded=True。"""
        from app.services.ui_visualizer import UiVisualizer

        cleared = _clear_api_keys()
        try:
            viz = UiVisualizer(workspace_root="/tmp/_test_degraded_design")
            result = await viz.check_design_resources()
        finally:
            _restore_api_keys(cleared)

        assert result["ok"] is True, "HTML 保底应使资源检查通过"
        assert result["degraded"] is True, (
            "无图片生成 API Key 时应标记为 degraded"
        )
        assert "no_image_gen_api" in result.get("degraded_reason", ""), (
            f"degraded_reason 应说明缺少哪些 Key，实际: {result.get('degraded_reason')}"
        )
        assert "html_prototype" in result["available"], "HTML 保底应始终可用"
        assert "openai_images" not in result["available"], "无 Key 不应标记 OpenAI 可用"

    async def test_check_design_resources_degraded_reason_lists_missing_keys(self):
        """degraded_reason 应列出 OPENAI_API_KEY 和 GEMINI_API_KEY 缺失。"""
        from app.services.ui_visualizer import UiVisualizer

        cleared = _clear_api_keys()
        try:
            viz = UiVisualizer(workspace_root="/tmp/_test_degraded_reason")
            result = await viz.check_design_resources()
        finally:
            _restore_api_keys(cleared)

        reason = result.get("degraded_reason", "")
        assert "OPENAI_API_KEY" in reason or "GEMINI_API_KEY" in reason, (
            f"降级原因应提及缺失的 Key 名称: {reason}"
        )

    async def test_check_design_resources_not_degraded_with_openai_key(self):
        """有 OPENAI_API_KEY 时不应标记为 degraded（即使 Gemini 未配置）。"""
        from app.services.ui_visualizer import UiVisualizer

        cleared = _clear_api_keys()
        try:
            os.environ["OPENAI_API_KEY"] = "sk-test-real-key"
            viz = UiVisualizer(workspace_root="/tmp/_test_not_degraded")
            result = await viz.check_design_resources()
        finally:
            _restore_api_keys(cleared)
            os.environ.pop("OPENAI_API_KEY", None)

        assert result["degraded"] is False, (
            f"有真实图片生成 Key 时不应 degraded: {result.get('degraded_reason', '')}"
        )


# ── Task 2: UI Mockup 降级产出 ───────────────────────────────────────────


class TestMockupDegradedOutput:

    async def test_generate_mockup_degraded_without_image_api(self):
        """无图片 API 时 generate_mockup 返回 ok=False, degraded=True, 仅 HTML。"""
        from app.services.ui_visualizer import UiVisualizer

        tmpdir = tempfile.mkdtemp(prefix="_test_mockup_degraded_")
        try:
            cleared = _clear_api_keys()
            try:
                viz = UiVisualizer(workspace_root=tmpdir)
                result = await viz.generate_mockup(
                    task_id="test-task-degraded",
                    stage_id="design",
                    design_spec="## 医疗管理系统\n主色 #1a73e8，包含患者列表、预约管理、药品库存",
                    project_name="MedicalSystem",
                )
            finally:
                _restore_api_keys(cleared)

            assert result["ok"] is False, (
                "无图片 API 时 generate_mockup 应返回 ok=False"
            )
            assert result["degraded"] is True, (
                "HTML 保底可用时应标记 degraded=True"
            )
            assert result["imageExists"] is False, "不应有 PNG 图片"
            assert result["htmlExists"] is True, "应有 HTML 保底"
            assert result["htmlPath"], "HTML 路径不应为空"
            assert result["htmlPath"].startswith("ui_mockups/"), "应返回 worktree 相对路径"
            abs_html = os.path.join(tmpdir, "test-task-degraded", result["htmlPath"])
            assert os.path.isfile(abs_html), f"HTML 文件应存在: {abs_html}"
            with open(abs_html, "r", encoding="utf-8") as f:
                html = f.read()
            assert "<html" in html.lower()
            assert "MedicalSystem" in html, "HTML 应包含项目名称"
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    async def test_generate_mockup_ok_with_mocked_image(self):
        """当 _generate_image 返回有效路径时，generate_mockup 返回 ok=True。"""
        from app.services.ui_visualizer import UiVisualizer

        tmpdir = tempfile.mkdtemp(prefix="_test_mockup_ok_")
        png_path = os.path.join(tmpdir, "test-task-ok", "mockups", "ui-mockup-test.png")
        os.makedirs(os.path.dirname(png_path), exist_ok=True)
        with open(png_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")  # minimal PNG header

        try:
            viz = UiVisualizer(workspace_root=tmpdir)
            with patch.object(viz, "_generate_image", return_value=png_path):
                result = await viz.generate_mockup(
                    task_id="test-task-ok",
                    stage_id="design",
                    design_spec="## Dashboard\nPrimary #3366ff",
                    project_name="TestApp",
                )

            assert result["ok"] is True, f"有真实图片时应 ok=True: {result}"
            assert result["degraded"] is False, "不应标记 degraded"
            assert result["imageExists"] is True
            assert result["imagePath"] == "ui_mockups/ui-mockup-test.png"
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── Task 3: 架构图资源检查降级 ────────────────────────────────────────────


class TestDiagramResourceCheckDegraded:

    async def test_check_diagram_resources_degraded_without_mermaid_cli(self):
        """无 mmdc CLI 时 diagram 资源检查应标记 degraded=True (CDN-only)。"""
        from app.services.ui_visualizer import UiVisualizer

        viz = UiVisualizer(workspace_root="/tmp/_test_diagram_degraded")
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = await viz.check_diagram_resources()

        assert result["ok"] is True, "HTML 渲染始终可用"
        assert result["degraded"] is True, (
            "无本地 mmdc CLI 时应标记 degraded (仅 CDN)"
        )
        assert "mermaid_cli_not_installed" in result.get("degraded_reason", ""), (
            f"degraded_reason 应提及 mermaid CLI 缺失: {result.get('degraded_reason')}"
        )

    async def test_check_diagram_resources_not_degraded_with_mermaid_cli(self):
        """有 mmdc CLI 时不应标记 degraded。"""
        from app.services.ui_visualizer import UiVisualizer

        viz = UiVisualizer(workspace_root="/tmp/_test_diagram_ok")
        with patch("subprocess.run", return_value=type("r", (), {"returncode": 0})()):
            result = await viz.check_diagram_resources()

        assert result["degraded"] is False, "有本地 mmdc 时不应 degraded"


# ── Task 4: 全链路 Pipeline 降级路径 ──────────────────────────────────────


class TestFullPipelineDegradedPath:

    async def test_pipeline_design_stage_advances_in_degraded_mode(
        self, client, auth_headers,
    ):
        """无 API Key 时 design 阶段应正常推进，手动写入 degraded ui_mockup 后合约可验证。

        advance API 使用 stub 输出推进状态机，不会触发 Layer 9.5 真实图片生成。
        本测试验证：即使只有降级 HTML，ui_mockup 合约依然可满足，任务不阻塞。
        """
        cleared = _clear_api_keys()
        try:
            # 1. 创建任务
            create_res = await client.post(
                "/api/pipeline/tasks",
                json={
                    "title": "[Degraded E2E] 医疗管理系统",
                    "description": "做一个医疗管理系统，包含患者列表、预约管理、药品库存功能",
                },
                headers=auth_headers,
            )
            assert create_res.status_code == 201, f"创建任务失败: {create_res.text}"
            task_id = create_res.json()["task"]["id"]

            # 2. 获取任务详情确认 stages
            detail = await client.get(
                f"/api/pipeline/tasks/{task_id}", headers=auth_headers,
            )
            assert detail.status_code == 200
            stages = detail.json()["task"]["stages"]
            stage_ids = {s["stage_id"] for s in stages}
            assert "design" in stage_ids, f"应有 design 阶段: {stage_ids}"

            # 3. 推进 planning 阶段
            adv = await client.post(
                f"/api/pipeline/tasks/{task_id}/advance",
                json={
                    "output": "## 方案\n医疗管理系统 MVP，包含患者/预约/药品三大模块。",
                },
                headers=auth_headers,
            )
            assert adv.status_code == 200, f"advance planning 失败: {adv.text}"

            # 4. 推进 design 阶段 — 关键：无 API Key 时不应阻塞
            adv2 = await client.post(
                f"/api/pipeline/tasks/{task_id}/advance",
                json={
                    "output": (
                        "## UI 规格\n"
                        "主色 #1a73e8，白色背景，侧边栏导航。\n"
                        "## 患者列表页\n表格展示，支持搜索和筛选。\n"
                        "## 预约管理页\n日历视图，拖拽调整时间。\n"
                        "## 药品库存页\n卡片网格，低库存警告。\n"
                    ),
                },
                headers=auth_headers,
            )
            assert adv2.status_code == 200, (
                f"无 API Key 时 design 阶段不应阻塞: {adv2.text}"
            )

            # 5. 手动写入降级 ui_mockup（模拟 degraded 模式产出）
            degraded_content = (
                "[降级] UI 设计稿（HTML 保底模板，非真实设计稿）\n"
                "/tmp/degraded-mockup/ui-prototype-TestApp.html"
            )
            wr = await client.post(
                f"/api/tasks/{task_id}/artifacts/ui_mockup",
                json={
                    "title": "UI 设计稿（降级）",
                    "content": degraded_content,
                    "mime_type": "text/markdown",
                },
                headers=auth_headers,
            )
            assert wr.status_code == 201, f"写入 ui_mockup 失败: {wr.text}"

            # 6. 验证 ui_mockup artifact 存在且有内容
            art_list = await client.get(
                f"/api/tasks/{task_id}/artifacts", headers=auth_headers,
            )
            assert art_list.status_code == 200
            items = {x["type_key"]: x for x in art_list.json().get("artifacts", [])}

            assert "ui_mockup" in items, (
                f"应有 ui_mockup artifact: {list(items.keys())}"
            )
            mockup = items["ui_mockup"]
            assert mockup.get("has_content") is True, "ui_mockup 应有内容"

            # 获取 artifact 详情以验证降级标记
            art_detail = await client.get(
                f"/api/tasks/{task_id}/artifacts/ui_mockup", headers=auth_headers,
            )
            assert art_detail.status_code == 200
            detail_content = art_detail.json().get("content", "")
            assert (
                "降级" in detail_content
                or "degraded" in detail_content.lower()
                or "保底" in detail_content
            ), f"降级 ui_mockup 应有降级标记: {detail_content[:200]}"

            # 7. 验证 artifact contract 中 design 阶段状态
            contract_res = await client.get(
                f"/api/pipeline/tasks/{task_id}/artifact-contract",
                headers=auth_headers,
            )
            assert contract_res.status_code == 200
            contract = contract_res.json()
            design_status = (contract.get("stages") or {}).get("design", {})
            assert design_status.get("present", {}).get("ui_mockup") is True, (
                "contract 应报告 ui_mockup 存在"
            )

        finally:
            _restore_api_keys(cleared)

    async def test_pipeline_architecture_stage_advances_without_api_keys(
        self, client, auth_headers,
    ):
        """无 API Key 时 architecture 阶段正常推进，手动写入 architecture_diagram 后合约可验证。"""
        cleared = _clear_api_keys()
        try:
            # 1. 创建任务
            create_res = await client.post(
                "/api/pipeline/tasks",
                json={
                    "title": "[Degraded Arch] 电商平台",
                    "description": "做一个电商平台，包含商品列表、购物车、订单管理",
                },
                headers=auth_headers,
            )
            assert create_res.status_code == 201, f"创建任务失败: {create_res.text}"
            task_id = create_res.json()["task"]["id"]

            # 2. 推进 planning → design → architecture
            for stage_output in [
                "## 方案\n电商平台 MVP，商品/购物车/订单三大模块。",
                "## UI 规格\n商品卡片网格，购物车侧边栏，订单列表。",
                "## 架构\nFrontend: Vue 3 SPA, Backend API: FastAPI, Database: PostgreSQL。",
            ]:
                adv = await client.post(
                    f"/api/pipeline/tasks/{task_id}/advance",
                    json={"output": stage_output},
                    headers=auth_headers,
                )
                assert adv.status_code == 200, f"advance 失败: {adv.text}"

            # 3. 手动写入 architecture_diagram
            arch_content = (
                "```mermaid\nflowchart LR\n"
                "  U[User]-->FE[Vue 3 SPA]\n"
                "  FE-->API[FastAPI]\n"
                "  API-->DB[(PostgreSQL)]\n"
                "```\n"
            )
            wr = await client.post(
                f"/api/tasks/{task_id}/artifacts/architecture_diagram",
                json={
                    "title": "架构图",
                    "content": arch_content,
                    "mime_type": "text/markdown",
                },
                headers=auth_headers,
            )
            assert wr.status_code == 201, f"写入 architecture_diagram 失败: {wr.text}"

            # 4. 验证 architecture_diagram artifact 存在且有内容
            art_list = await client.get(
                f"/api/tasks/{task_id}/artifacts", headers=auth_headers,
            )
            assert art_list.status_code == 200
            items = {x["type_key"]: x for x in art_list.json().get("artifacts", [])}

            assert "architecture_diagram" in items, (
                f"应有 architecture_diagram: {list(items.keys())}"
            )
            arch_diagram = items["architecture_diagram"]
            assert arch_diagram.get("has_content") is True

        finally:
            _restore_api_keys(cleared)


# ── Task 5: Artifact Contract Rules Strict 验证 ──────────────────────────


class TestArtifactContractRulesStrict:

    async def test_rules_strict_rejects_prd_too_short(self, client, auth_headers):
        """rules_strict=True 时，低于 min_chars 的 PRD 应被拒绝。"""
        from app.config import settings

        # 确认 rules_strict 已开启
        assert settings.artifact_contract_rules_strict is True, (
            "默认应开启 rules_strict"
        )

        # 1. 创建任务并写入过短的 PRD（<80 字符）
        create_res = await client.post(
            "/api/pipeline/tasks",
            json={"title": "[Strict] Short PRD", "description": "test"},
            headers=auth_headers,
        )
        assert create_res.status_code == 201
        task_id = create_res.json()["task"]["id"]

        # 写入极短的 PRD
        short_prd = "Short PRD"  # 仅 9 字符，远低于 80 min_chars
        wr = await client.post(
            f"/api/tasks/{task_id}/artifacts/prd",
            json={
                "title": "Bad PRD",
                "content": short_prd,
                "mime_type": "text/markdown",
            },
            headers=auth_headers,
        )
        assert wr.status_code == 201, f"写入 artifact 失败: {wr.text}"

        # 2. 检查 contract
        contract_res = await client.get(
            f"/api/pipeline/tasks/{task_id}/artifact-contract",
            headers=auth_headers,
        )
        assert contract_res.status_code == 200
        contract = contract_res.json()

        # 3. PRD 应被标记为 invalid（rules_strict 拒绝）
        planning_status = (contract.get("stages") or {}).get("planning", {})
        prd_detail = (planning_status.get("artifact_details") or {}).get("prd", {})
        assert prd_detail.get("present") is True, "PRD 应存在"
        assert len(prd_detail.get("validation_errors", [])) > 0, (
            f"短 PRD 应有 validation_errors: {prd_detail}"
        )
        assert "prd" in planning_status.get("invalid", []), (
            f"短 PRD 应在 invalid 列表中: {planning_status}"
        )

    async def test_rules_strict_accepts_valid_prd(self, client, auth_headers):
        """rules_strict=True 时，符合规范的 PRD 应通过验证。"""
        # 1. 创建任务并写入合规 PRD
        create_res = await client.post(
            "/api/pipeline/tasks",
            json={"title": "[Strict] Valid PRD", "description": "test"},
            headers=auth_headers,
        )
        assert create_res.status_code == 201
        task_id = create_res.json()["task"]["id"]

        # 写入 >80 字符且包含多个 markdown 标题的合规 PRD
        valid_prd = (
            "## 范围\n待办看板 MVP，支持新增、完成、删除任务。\n\n"
            "## 用户故事\n- US1: 用户可以新增待办任务\n"
            "- US2: 用户可以标记任务为已完成\n"
            "- US3: 用户可以删除不需要的任务\n\n"
            "## 验收标准\n- AC1: 新增任务后立即出现在列表中\n"
            "- AC2: 完成任务后显示删除线\n"
            "- AC3: 删除任务后从列表消失\n\n"
            "## 非目标\n- 多端同步暂不实现\n"
            "- 子任务功能暂不实现\n\n"
            "## 技术约束\n- 前端使用 Vue 3\n"
            "- 数据存储使用 localStorage\n"
            "- 无需后端服务\n"
        )
        assert len(valid_prd) >= 80, f"测试数据应 >80 字符: {len(valid_prd)}"

        wr = await client.post(
            f"/api/tasks/{task_id}/artifacts/prd",
            json={
                "title": "Good PRD",
                "content": valid_prd,
                "mime_type": "text/markdown",
            },
            headers=auth_headers,
        )
        assert wr.status_code == 201, f"写入 artifact 失败: {wr.text}"

        # 2. 检查 contract
        contract_res = await client.get(
            f"/api/pipeline/tasks/{task_id}/artifact-contract",
            headers=auth_headers,
        )
        assert contract_res.status_code == 200
        contract = contract_res.json()

        # 3. PRD 应通过验证
        planning_status = (contract.get("stages") or {}).get("planning", {})
        prd_detail = (planning_status.get("artifact_details") or {}).get("prd", {})
        assert prd_detail.get("present") is True, "PRD 应存在"
        assert prd_detail.get("validation_errors") == [], (
            f"合规 PRD 不应有 validation_errors: {prd_detail.get('validation_errors')}"
        )

    async def test_rules_strict_rejects_ui_spec_too_short(
        self, client, auth_headers,
    ):
        """rules_strict=True 时，低于 min_chars(40) 的 ui_spec 应被拒绝。"""
        create_res = await client.post(
            "/api/pipeline/tasks",
            json={"title": "[Strict] Short UI Spec", "description": "test"},
            headers=auth_headers,
        )
        assert create_res.status_code == 201
        task_id = create_res.json()["task"]["id"]

        # 写入极短的 ui_spec
        wr = await client.post(
            f"/api/tasks/{task_id}/artifacts/ui_spec",
            json={
                "title": "Bad UI",
                "content": "Short spec",
                "mime_type": "text/markdown",
            },
            headers=auth_headers,
        )
        assert wr.status_code == 201

        contract_res = await client.get(
            f"/api/pipeline/tasks/{task_id}/artifact-contract",
            headers=auth_headers,
        )
        contract = contract_res.json()
        design_status = (contract.get("stages") or {}).get("design", {})
        ui_detail = (design_status.get("artifact_details") or {}).get("ui_spec", {})

        assert len(ui_detail.get("validation_errors", [])) > 0, (
            f"短 ui_spec 应有 validation_errors: {ui_detail}"
        )


# ── Task 6: 边界情况 ──────────────────────────────────────────────────────


class TestDegradedEdgeCases:

    async def test_generate_mockup_fails_completely_when_all_blocked(self):
        """当 HTML 生成也失败时，generate_mockup 返回 ok=False, degraded=False。"""
        from app.services.ui_visualizer import UiVisualizer

        tmpdir = tempfile.mkdtemp(prefix="_test_mockup_fail_")
        try:
            cleared = _clear_api_keys()
            try:
                viz = UiVisualizer(workspace_root=tmpdir)
                with patch.object(viz, "_generate_html", return_value=""):
                    result = await viz.generate_mockup(
                        task_id="test-total-fail",
                        stage_id="design",
                        design_spec="## Test",
                        project_name="Test",
                    )
            finally:
                _restore_api_keys(cleared)

            assert result["ok"] is False, "所有渠道失败时应 ok=False"
            assert result["degraded"] is False, "无任何产出时不应标记 degraded"
            assert result["imageExists"] is False
            assert result["htmlExists"] is False
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    async def test_degraded_is_not_blocked(self):
        """degraded ≠ blocked：degraded 表示降级可用，blocked 表示完全不可用。"""
        from app.services.ui_visualizer import UiVisualizer

        cleared = _clear_api_keys()
        try:
            viz = UiVisualizer(workspace_root="/tmp/_test_distinguish")
            result = await viz.check_design_resources()

            assert result["ok"] is True, "有 HTML 保底时不应 blocked"
            assert result["degraded"] is True, "无图片 API 时应 degraded"
            assert result.get("fallbacks") == ["html_prototype"], (
                f"应有 HTML 保底作为 fallback: {result.get('fallbacks')}"
            )
        finally:
            _restore_api_keys(cleared)


# ── Task 7: Share + Deliverables 在降级模式下仍然可用 ─────────────────────


class TestShareAndDeliverablesDegraded:

    async def test_share_and_zip_available_in_degraded_mode(
        self, client, auth_headers,
    ):
        """降级模式下 share token 和 deliverables ZIP 仍应可用。"""
        cleared = _clear_api_keys()
        try:
            # 1. 创建并推进任务
            create_res = await client.post(
                "/api/pipeline/tasks",
                json={
                    "title": "[Degraded Share] 待办看板",
                    "description": "做一个待办事项看板，支持新增、完成、删除任务。",
                },
                headers=auth_headers,
            )
            assert create_res.status_code == 201
            task_id = create_res.json()["task"]["id"]

            # 推进所有阶段
            stages = [
                "planning", "design", "architecture",
                "development", "testing", "deployment",
            ]
            for stage_id in stages:
                adv = await client.post(
                    f"/api/pipeline/tasks/{task_id}/advance",
                    json={"output": f"## {stage_id}\nStub output for degraded test."},
                    headers=auth_headers,
                )
                if adv.status_code != 200:
                    # 任务可能已完成，检查状态
                    task_check = await client.get(
                        f"/api/pipeline/tasks/{task_id}", headers=auth_headers,
                    )
                    if task_check.json()["task"]["status"] == "done":
                        break

            # 2. 写入最小 artifacts
            minimal_artifacts = [
                ("brief", "## 简报\n待办看板。\n"),
                ("prd", (
                    "## 范围\n待办看板 MVP。\n\n"
                    "## 用户故事\n- US1 新增\n- US2 完成\n- US3 删除\n\n"
                    "## 验收标准\n- AC1 基本功能\n\n"
                    "## 非目标\n无\n"
                )),
                ("ui_spec", "## UI 规格\n列表 + FAB 按钮，每项含勾选和删除。\n"),
                ("ui_mockup", "降级 HTML 保底模板\n"),
                ("architecture", "## 架构\nVue 3 SPA，localStorage 存储。\n"),
                ("architecture_diagram", "```mermaid\nflowchart LR\n  U-->App\n```\n"),
                ("implementation", "## 实现\n关键组件：TodoList, TodoItem。\n"),
                ("test_report", "## 测试报告\n- 构建通过\n- 冒烟测试通过\n"),
                ("test_log", "[DEGRADED_PATH_MOCK] pnpm test output\nPASS tests/unit/test.spec.ts\nTests: 1 passed, 1 total\n"),
                ("build_log", "[DEGRADED_PATH_MOCK] pnpm install\nexit code: 0\n[DEGRADED_PATH_MOCK] pnpm build\nexit code: 0\n"),
                ("acceptance", "## 验收\n- [x] AC1: 测试通过、构建OK、截图已确认\n"),
                ("code_link", '{"repo":"local","branch":"main"}\n'),
                ("screenshot", "[DEGRADED_PATH_MOCK] screenshot placeholder\n"),
                ("deploy_manifest", '{"preview_url":"http://127.0.0.1:4173/mock","provider":"mock"}\n'),
                ("ops_runbook", "## 运维手册（mock）\n回滚：保留上一 tag。\n"),
                ("source_manifest", '{"created_files":["src/App.vue"],"build_command":"pnpm build","run_command":"pnpm preview"}\n'),
                ("preview_url", '{"url":"http://127.0.0.1:4173/mock","provider":"mock-local","health_status":"healthy"}\n'),
            ]
            for atype, content in minimal_artifacts:
                await client.post(
                    f"/api/tasks/{task_id}/artifacts/{atype}",
                    json={
                        "title": atype, "content": content,
                        "mime_type": "text/markdown",
                    },
                    headers=auth_headers,
                )

            # 3. Share token
            shr = await client.post(
                "/api/share/generate",
                json={"task_id": task_id, "ttl_days": 7},
                headers=auth_headers,
            )
            assert shr.status_code == 200, f"share generate 失败: {shr.text}"
            token = shr.json().get("token")
            assert token

            pub = await client.get(f"/api/share/{token}")
            assert pub.status_code == 200

            # 4. Deliverables ZIP
            z = await client.get(
                f"/api/tasks/{task_id}/deliverables.zip", headers=auth_headers,
            )
            assert z.status_code == 200
            with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
                assert "manifest.json" in zf.namelist()

        finally:
            _restore_api_keys(cleared)
