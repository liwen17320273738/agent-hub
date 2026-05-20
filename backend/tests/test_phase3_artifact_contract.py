"""Phase 3 — artifact contract validation and REST report."""
from __future__ import annotations

import pytest

from app.models.pipeline import PipelineTask
from app.config import settings
from app.services.artifact_contract import (
    build_task_contract_report,
    validate_stage_artifact_contract,
    validate_stage_artifact_contract_rules_strict,
)
from app.services.artifact_writer import write_stage_artifacts_v2
from app.services.manifest_sync import rebuild_manifest


@pytest.mark.asyncio
async def test_validate_planning_requires_brief_and_prd(db, test_user):
    task = PipelineTask(
        title="Contract planning",
        description="phase3",
        org_id=test_user.org_id,
        created_by=str(test_user.id),
    )
    db.add(task)
    await db.flush()
    tid = str(task.id)

    ok0, missing0 = await validate_stage_artifact_contract(db, tid, "planning")
    assert not ok0
    assert set(missing0) == {"brief", "prd"}

    await write_stage_artifacts_v2(
        db,
        task_id=tid,
        task_title=task.title,
        stage_id="planning",
        content=(
            "## 范围（合约测试）\n简述需求占位，填满最小字数用于 Phase3 结构化 PRD 校验。\n\n"
            "## 用户故事\n- US1 占位\n\n"
            "## 验收标准\n- AC1 demo\n\n"
            "## 非目标\n- 多端同步延后\n\n"
            "## 实现备注\n本节用于满足 markdown h2 数量下限。\n"
        ),
    )
    await db.flush()

    ok1, missing1 = await validate_stage_artifact_contract(db, tid, "planning")
    assert ok1
    assert missing1 == []


@pytest.mark.asyncio
async def test_rebuild_manifest_includes_contract_snapshot(db, test_user):
    task = PipelineTask(
        title="Manifest contract",
        description="phase3",
        org_id=test_user.org_id,
        created_by=str(test_user.id),
    )
    db.add(task)
    await db.flush()
    tid = str(task.id)

    await write_stage_artifacts_v2(
        db,
        task_id=tid,
        task_title=task.title,
        stage_id="design",
        content="## UI\nmock spec\n",
    )
    # Also write ui_mockup to satisfy Phase 5 contract
    from app.services.artifact_writer import _write_one_artifact
    await _write_one_artifact(
        db, tid, "design", "ui_mockup",
        "![mock](./screenshots/generated/mock.png)\n",
        "screenshots/mock.png", "test",
    )
    await db.commit()

    m = await rebuild_manifest(tid, db)
    assert "contract" in m
    assert m["contract"]["task_id"] == tid
    design = m["contract"]["stages"]["design"]
    assert design["ok"] is True
    assert "rules_strict" in m["contract"]


@pytest.mark.asyncio
async def test_artifact_contract_api(client, auth_headers):
    create_res = await client.post(
        "/api/pipeline/tasks",
        json={"title": "Contract API task", "description": "phase3"},
        headers=auth_headers,
    )
    assert create_res.status_code == 201
    task_id = create_res.json()["task"]["id"]

    r = await client.get(
        f"/api/pipeline/tasks/{task_id}/artifact-contract",
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == task_id
    assert body["stages"]["planning"]["ok"] is False

    prd_stub = (
        "## 范围\n简述需求占位，补足最小字数用于程序化合约 API 断言。\n\n"
        "## 用户故事\n- US1 demo\n\n"
        "## 验收标准\n- AC1 checklist\n\n"
        "## 非目标\n延后项示例\n\n"
    )
    for atype, blob, title in (
        ("prd", prd_stub, "Manual PRD"),
        (
            "brief",
            "## Brief\n占位摘要：程序化合约 API 用例需要满足最短字符阈值。\n",
            "Brief",
        ),
    ):
        wr = await client.post(
            f"/api/tasks/{task_id}/artifacts/{atype}",
            json={"title": title, "content": blob, "mime_type": "text/markdown"},
            headers=auth_headers,
        )
        assert wr.status_code == 201, wr.text

    r2 = await client.get(
        f"/api/pipeline/tasks/{task_id}/artifact-contract",
        headers=auth_headers,
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["stages"]["planning"]["ok"] is True
    assert body.get("schema_version")
    assert "definitions" in body
    assert "rules_strict" in body
    assert body["rules_strict"] is settings.artifact_contract_rules_strict
    assert "prd" in body["definitions"]
    assert body["stages"]["planning"]["artifact_details"]["prd"]["validation_errors"] == []


@pytest.mark.asyncio
async def test_share_artifact_contract_public(client, auth_headers):
    c = await client.post(
        "/api/pipeline/tasks",
        json={"title": "Share contract", "description": "x"},
        headers=auth_headers,
    )
    task_id = c.json()["task"]["id"]
    tok = (
        await client.post(
            "/api/share/generate",
            json={"task_id": task_id, "ttl_days": 7},
            headers=auth_headers,
        )
    ).json()["token"]
    r = await client.get(f"/api/share/{tok}/artifact-contract")
    assert r.status_code == 200
    j = r.json()
    assert j["task_id"] == task_id
    assert j["enforce"] is True
    assert j.get("rules_strict") == settings.artifact_contract_rules_strict


@pytest.mark.asyncio
async def test_rules_strict_blocks_bad_prd_headings(monkeypatch, db, test_user):
    monkeypatch.setattr(settings, "artifact_contract_rules_strict", True)
    monkeypatch.setattr(settings, "artifact_contract_enforce", True)
    monkeypatch.setattr(settings, "artifact_store_v2", True)

    bad = PipelineTask(
        title="Strict PRD headings",
        description="phase3",
        org_id=test_user.org_id,
        created_by=str(test_user.id),
    )
    db.add(bad)
    await db.flush()
    tid = str(bad.id)

    await write_stage_artifacts_v2(
        db,
        task_id=tid,
        task_title=bad.title,
        stage_id="planning",
        content=(
            "## 范围\n" + "y" * 120 + "\n\n"
            "## 验收标准\n- AC\n\n"
            "## 非目标\n- N\n\n"
            "## Extra\n filler markdown\n\n"
        ),
    )
    await db.commit()

    ok_p, missing = await validate_stage_artifact_contract(db, tid, "planning")
    assert ok_p, missing

    ok_s, errs = await validate_stage_artifact_contract_rules_strict(db, tid, "planning")
    assert not ok_s and errs


@pytest.mark.asyncio
async def test_rules_strict_off_skips_heading_rules(monkeypatch, db):
    monkeypatch.setattr(settings, "artifact_contract_rules_strict", False)

    ok_s, errs = await validate_stage_artifact_contract_rules_strict(db, "", "planning")
    assert ok_s and errs == []


@pytest.mark.asyncio
async def test_prd_keyword_groups_validation_errors_when_heading_missing(db, test_user):
    task = PipelineTask(
        title="PRD headings",
        description="phase3",
        org_id=test_user.org_id,
        created_by=str(test_user.id),
    )
    db.add(task)
    await db.flush()
    tid = str(task.id)

    await write_stage_artifacts_v2(
        db,
        task_id=tid,
        task_title=task.title,
        stage_id="planning",
        content=(
            "## 范围\n" + "x" * 120 + "\n\n"
            "## 验收标准\n- AC\n\n"
            "## 非目标\n- N\n\n"
            "## Extra\n filler\n\n"
        ),
    )
    await db.commit()

    r = await build_task_contract_report(db, tid)
    prd = r["stages"]["planning"]["artifact_details"]["prd"]
    errs = prd["validation_errors"]
    assert any("missing_group" in e for e in errs)
