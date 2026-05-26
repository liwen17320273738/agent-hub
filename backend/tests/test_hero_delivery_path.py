"""Hero Path programmatic delivery bundle — Phase 1 execution doc.

Runs without real LLM: advances all default pipeline stages via ``/advance``,
writes v2 task artifacts via API, verifies share + deliverables ZIP.

This is a **smoke** test for state machine + artifact storage wiring.
Mock/stub artifacts must **not** pass the quality-aware artifact contract.

See: ``docs/analysis/ai-legion-execution/phase-1-hero-path-e2e.md``
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest

HERO_SENTENCE = "做一个待办事项看板，支持新增、完成、删除任务。"

# Minimal set aligned with Artifact Contract roadmap (phase-3 doc).
_REQUIRED_ARTIFACT_TYPES = frozenset(
    {
        "brief",
        "prd",
        "ui_spec",
        "ui_mockup",
        "architecture",
        "architecture_diagram",
        "implementation",
        "test_report",
        "acceptance",
        "code_link",
        "screenshot",
        "deploy_manifest",
        "ops_runbook",
        "source_manifest",
        "build_log",
        "preview_url",
    },
)


@pytest.mark.asyncio
async def test_hero_delivery_path_smoke_without_llm(client, db, auth_headers):
    # 1. Create task (one sentence)
    create_res = await client.post(
        "/api/pipeline/tasks",
        json={
            "title": "[Hero delivery E2E] Todo board",
            "description": HERO_SENTENCE,
        },
        headers=auth_headers,
    )
    assert create_res.status_code == 201, f"create task: {create_res.text}"
    task_id = create_res.json()["task"]["id"]

    detail = await client.get(f"/api/pipeline/tasks/{task_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    task_blob = detail.json()["task"]
    stages = task_blob.get("stages") or []
    stage_count = len(stages)

    assert stage_count >= 6, (
        "expected full default pipeline stages; collaboration template may have changed"
    )
    assert {"planning", "design", "deployment"}.issubset(
        {s.get("stage_id") or s.get("stageId") for s in stages}
    ), "missing expected stage ids"

    # 2. Advance through every stage (real state machine transitions, stub outputs)
    for i in range(stage_count + 2):
        d2 = await client.get(f"/api/pipeline/tasks/{task_id}", headers=auth_headers)
        assert d2.status_code == 200, d2.text
        t2 = d2.json()["task"]
        if t2.get("status") == "done":
            break
        cur = t2.get("current_stage_id")
        advancing_from = cur
        adv = await client.post(
            f"/api/pipeline/tasks/{task_id}/advance",
            json={"output": f"## Stub\ncompleted stage `{cur}` iteration {i} (hero-delivery-path)."},
            headers=auth_headers,
        )
        adv_detail = ""
        try:
            adv_js = adv.json()
            adv_detail = adv_js.get("detail") or json.dumps(adv_js, ensure_ascii=False)[:2000]
        except Exception:
            adv_detail = adv.text[:2000]
        assert adv.status_code == 200, (
            f"advance iteration={i} advancing_from={advancing_from!r} "
            f"task_current_before={cur!r} status={adv.status_code} body={adv_detail}"
        )
        refreshed = adv.json().get("task") or {}
        active_rows = [
            s for s in (refreshed.get("stages") or []) if (s.get("status") == "active")
        ]
        for ar in active_rows:
            sid = ar.get("stage_id") or ar.get("id")
            snap = ar.get("input_snapshot")
            assert snap is not None, (
                f"iteration={i}: active stage {sid!r} missing input_snapshot (durable handoff)"
            )
            assert snap.get("source") == "advance", snap
            assert snap.get("after_stage_id") == advancing_from, snap

    done_get = await client.get(f"/api/pipeline/tasks/{task_id}", headers=auth_headers)
    assert done_get.status_code == 200
    final_task = done_get.json()["task"]
    assert final_task["status"] == "done", f"task stuck: {final_task.get('current_stage_id')}"

    all_done = all(
        (s.get("status") == "done") for s in (final_task.get("stages") or [])
    )
    assert all_done, "every stage row should be done after advancing to task done"

    # 3. v2 artifacts — structured delivery evidence (+ explicit mock markers in prose)
    _samples: list[tuple[str, str, str]] = [
        (
            "brief",
            "## 简报\n用户需求：待办看板。\n",
            "需求简报",
        ),
        (
            "prd",
            "## 范围（Hero Path）\n待办看板 MVP；本段用于程序化 E2E 覆盖 PRD contract 占位。\n\n"
            "## 用户故事\n- US1 新增任务\n- US2 标记完成\n- US3 删除任务\n\n"
            "## 验收标准\n- AC1 Demo 占位\n\n"
            "## 非目标（mock）\n- 多端同步延后\n\n",
            "PRD",
        ),
        (
            "ui_spec",
            "## UI 规格\n主列表区 + FAB 新建；每项含完成勾选与删除。\n",
            "UI Spec",
        ),
        (
            "ui_mockup",
            "PNG placeholder — replace with generated asset in Phase 5.\n",
            "UI Mockup stub",
        ),
        (
            "architecture",
            "## 架构\nVue 3 + Vite SPA；前端状态 Pinia。\n",
            "Architecture",
        ),
        (
            "architecture_diagram",
            "```mermaid\nflowchart LR\n  U[User]-->V[Vue SPA]\n```\n",
            "Architecture diagram",
        ),
        (
            "implementation",
            "## 实现说明（mock）\n关键组件：TodoList，TodoItem。\n",
            "Implementation",
        ),
        (
            "test_report",
            "```\n"
            "[HERO_PATH_E2E_MOCK] npm install\nexit code: 0\n"
            "[HERO_PATH_E2E_MOCK] npm run build\nexit code: 0\n"
            "[HERO_PATH_E2E_MOCK] npm run test\nexit code: 0\n"
            "```\n",
            "Test report (mock CLI)",
        ),
        (
            "test_log",
            "[HERO_PATH_E2E_MOCK] pnpm test output\nPASS tests/unit/TodoList.spec.ts\nPASS tests/unit/TodoItem.spec.ts\nTests: 2 passed, 2 total\n",
            "Test log",
        ),
        (
            "acceptance",
            "## 验收\n- [x] 所有 PRD AC 逐项核对\n- [x] 浏览器截图已确认 UI 正确\n- [x] 测试通过：build ok + test passed\n- [x] 预览已访问：http://127.0.0.1:4173/mock-preview\n",
            "Acceptance",
        ),
        (
            "code_link",
            "{\n"
            '"repo":"local-task-worktree",\n'
            '"branch":"hero-delivery-path",\n'
            '"path":"."\n}\n',
            "Code stub",
        ),
        (
            "screenshot",
            "[HERO_PATH_E2E_MOCK] playwright screenshot PNG bytes not inlined in markdown test.\n",
            "Screenshot stub",
        ),
        (
            "deploy_manifest",
            "{\n"
            '"preview_url":"http://127.0.0.1:4173/mock-preview",\n'
            '"provider":"mock-local",\n'
            '"health_status":"skipped_in_ci"\n}\n',
            "Deploy manifest (mock)",
        ),
        (
            "ops_runbook",
            "## 运维手册（mock）\n回滚：保留上一 tag；数据库迁移需单独执行。\n",
            "Ops runbook stub",
        ),
        (
            "source_manifest",
            '{\n"created_files":["src/App.vue","src/main.ts","src/views/Home.vue"],\n"build_command":"pnpm install && pnpm build && pnpm test",\n"run_command":"pnpm preview",\n"test_command":"pnpm test"\n}\n',
            "Source manifest stub",
        ),
        (
            "build_log",
            "[HERO_PATH_E2E_MOCK] pnpm install\nexit code: 0\n[HERO_PATH_E2E_MOCK] pnpm build\nexit code: 0\n[HERO_PATH_E2E_MOCK] pnpm test\nexit code: 0\n",
            "Build log stub",
        ),
        (
            "preview_url",
            '{\n"url":"http://127.0.0.1:4173/mock-preview",\n"provider":"mock-local",\n"health_status":"healthy",\n"deployed_at":"2026-05-19T00:00:00Z"\n}\n',
            "Preview URL stub",
        ),
    ]

    for atype, content, title in _samples:
        mime = "text/markdown"
        if atype in ("source_manifest",):
            mime = "application/json"
        elif atype in ("build_log",):
            mime = "text/plain"
        wr = await client.post(
            f"/api/tasks/{task_id}/artifacts/{atype}",
            json={"title": title, "content": content, "mime_type": mime},
            headers=auth_headers,
        )
        assert wr.status_code == 201, f"artifact {atype}: {wr.text}"

    lst = await client.get(f"/api/tasks/{task_id}/artifacts", headers=auth_headers)
    assert lst.status_code == 200, lst.text
    items_by_key = {x["type_key"]: x for x in lst.json().get("artifacts", [])}
    missing = sorted(_REQUIRED_ARTIFACT_TYPES - items_by_key.keys())
    assert not missing, f"registry missing keys: {missing}"

    for rk in sorted(_REQUIRED_ARTIFACT_TYPES):
        row = items_by_key[rk]
        assert row.get("has_content") is True, f"artifact {rk} lacks content ({row})"

    # 4. Share token + public read
    shr = await client.post(
        "/api/share/generate",
        json={"task_id": task_id, "ttl_days": 7},
        headers=auth_headers,
    )
    assert shr.status_code == 200, shr.text
    token = shr.json().get("token")
    assert token, "share token missing"

    pub = await client.get(f"/api/share/{token}")
    assert pub.status_code == 200, pub.text
    pub_body = pub.json()
    pid = pub_body.get("task_id") or (pub_body.get("task") or {}).get("id")
    assert str(pid) == str(task_id), "public share mismatch"

    # 5. Deliverables ZIP (auth)
    z = await client.get(f"/api/tasks/{task_id}/deliverables.zip", headers=auth_headers)
    assert z.status_code == 200, z.text
    assert z.headers.get("content-type", "").startswith("application/zip")
    blob = z.content
    assert len(blob) > 80, "zip unexpectedly tiny"

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
        assert "manifest.json" in names, f"ZIP missing manifest: {names[:20]}"
        assert "docs/01-prd.md" in names, f"ZIP missing canonical PRD path: {names[:20]}"
        mani = json.loads(zf.read("manifest.json"))
        assert mani.get("task_id") == task_id or str(mani.get("task_id")) == str(task_id)

    hero_contract = await client.get(
        f"/api/pipeline/tasks/{task_id}/artifact-contract",
        headers=auth_headers,
    )
    assert hero_contract.status_code == 200
    contract_body = hero_contract.json()
    assert contract_body.get("all_required_satisfied") is False, (
        "mock/stub artifacts must not satisfy quality-aware contract"
    )
    invalid_stages = [
        sid
        for sid, block in (contract_body.get("stages") or {}).items()
        if block.get("invalid")
    ]
    assert invalid_stages, "expected at least one stage flagged invalid for mock content"


@pytest.mark.asyncio
async def test_hero_path_advance_rejected_after_task_done(client, auth_headers):
    create_res = await client.post(
        "/api/pipeline/tasks",
        json={"title": "[Hero Path neg] Advance after done", "description": ""},
        headers=auth_headers,
    )
    assert create_res.status_code == 201, create_res.text
    task_id = create_res.json()["task"]["id"]

    detail = await client.get(f"/api/pipeline/tasks/{task_id}", headers=auth_headers)
    stage_count = len(detail.json()["task"]["stages"] or [])
    assert stage_count >= 1

    for _ in range(stage_count + 3):
        d2 = await client.get(f"/api/pipeline/tasks/{task_id}", headers=auth_headers)
        assert d2.status_code == 200
        t2 = d2.json()["task"]
        if t2.get("status") == "done":
            break
        await client.post(
            f"/api/pipeline/tasks/{task_id}/advance",
            json={"output": "## stub"},
            headers=auth_headers,
        )

    bad = await client.post(
        f"/api/pipeline/tasks/{task_id}/advance",
        json={"output": "## should_not_apply"},
        headers=auth_headers,
    )
    assert bad.status_code == 400
    bd = bad.json()
    detail_s = str(bd.get("detail") or json.dumps(bd, ensure_ascii=False))
    assert "已完成" in detail_s or "done" in detail_s.lower()
