"""Unit tests for the trustworthy-delivery contract.

Covers ``verify_delivery_evidence`` — the pure checker that gates share-token
issuance and final-accept on real test + real preview + real evidence.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.pipeline import PipelineTask
from app.models.task_artifact import TaskArtifact
from app.services.delivery_contract import (
    EvidenceCheck,
    EvidenceItem,
    verify_delivery_evidence,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(workspace_id=None) -> PipelineTask:
    t = PipelineTask(
        id=uuid.uuid4(),
        title="demo",
        description="",
        status="awaiting_final_acceptance",
        workspace_id=workspace_id,
    )
    return t


def _artifact(type_key: str, content: str, *, meta: dict | None = None,
              stage_id: str | None = None) -> TaskArtifact:
    return TaskArtifact(
        task_id=uuid.uuid4(),
        artifact_type=type_key,
        stage_id=stage_id,
        content=content,
        metadata_json=meta or {},
        is_latest=True,
        status="active",
        version=1,
    )


def _mock_db(artifacts: list[TaskArtifact], *, workspace_allow_draft: bool = False):
    """Build an AsyncSession mock that returns ``artifacts`` for artifact
    queries and a workspace row whose allow_draft_delivery == flag."""

    db = MagicMock()

    # First call: artifact query → list of artifacts.
    # Second call: workspace query → workspace row (or None if no workspace_id).
    artifact_scalars = MagicMock()
    artifact_scalars.all.return_value = artifacts
    artifact_result = MagicMock()
    artifact_result.scalars.return_value = artifact_scalars

    ws_row = MagicMock()
    ws_row.allow_draft_delivery = workspace_allow_draft
    ws_result = MagicMock()
    ws_result.scalar_one_or_none.return_value = ws_row

    db.execute = AsyncMock(side_effect=[artifact_result, ws_result])
    return db


def _full_evidence_artifacts() -> list[TaskArtifact]:
    """Build a complete, passing evidence bundle."""
    qa_meta = {
        "ok": True,
        "build": {"exit_code": 0, "command": "pnpm build"},
        "test": {"exit_code": 0, "command": "pnpm test"},
    }
    preview_payload = {
        "url": "https://preview.example.com/task-abc",
        "provider": "vercel",
        "health_status": "healthy",
        "screenshot_path": "/tmp/shot.png",
        "deployed_at": "2026-05-22T10:00:00",
    }
    return [
        _artifact("test_report", "# QA Report\nbuild ok", meta=qa_meta,
                 stage_id="testing"),
        _artifact("build_log", "pnpm build... exit 0", stage_id="testing"),
        _artifact("test_log", "vitest pass 12/12", stage_id="testing"),
        _artifact("preview_url", json.dumps(preview_payload),
                  meta=preview_payload, stage_id="deployment"),
        _artifact("screenshot", "BASE64DATA", stage_id="deployment",
                  meta={"original_path": "/tmp/deploy_shot.png"}),
        _artifact("acceptance",
                  "已通过最终验收。预览链接 https://preview.example.com/task-abc 通过测试。",
                  stage_id="acceptance"),
    ]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_evidence_passes():
    task = _make_task(workspace_id=uuid.uuid4())
    db = _mock_db(_full_evidence_artifacts())

    result = await verify_delivery_evidence(db, task)

    assert isinstance(result, EvidenceCheck)
    assert result.ok is True, f"missing={result.missing}, items={[(i.key, i.detail) for i in result.items if not i.ok]}"
    assert result.missing == ()
    assert "完整" in result.summary


# ---------------------------------------------------------------------------
# Each category failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_test_report_fails():
    arts = [a for a in _full_evidence_artifacts() if a.artifact_type != "test_report"]
    db = _mock_db(arts)
    result = await verify_delivery_evidence(db, _make_task())

    assert result.ok is False
    assert "test_report" in result.missing


@pytest.mark.asyncio
async def test_build_exit_code_nonzero_fails():
    arts = _full_evidence_artifacts()
    # Mutate test_report metadata to indicate build failure.
    for a in arts:
        if a.artifact_type == "test_report":
            a.metadata_json = {
                "ok": False,
                "build": {"exit_code": 1, "command": "pnpm build"},
                "test": {"exit_code": 0, "command": "pnpm test"},
            }
    db = _mock_db(arts)
    result = await verify_delivery_evidence(db, _make_task())

    assert result.ok is False
    assert "build_exit_code" in result.missing


@pytest.mark.asyncio
async def test_test_log_empty_fails():
    arts = [a for a in _full_evidence_artifacts() if a.artifact_type != "test_log"]
    arts.append(_artifact("test_log", "   ", stage_id="testing"))  # whitespace
    db = _mock_db(arts)
    result = await verify_delivery_evidence(db, _make_task())

    assert result.ok is False
    assert "test_log" in result.missing


@pytest.mark.asyncio
async def test_missing_preview_url_fails():
    arts = [a for a in _full_evidence_artifacts() if a.artifact_type != "preview_url"]
    db = _mock_db(arts)
    result = await verify_delivery_evidence(db, _make_task())

    assert result.ok is False
    assert "preview_url" in result.missing
    assert "preview_health" in result.missing


@pytest.mark.asyncio
async def test_preview_health_unhealthy_fails():
    arts = _full_evidence_artifacts()
    for a in arts:
        if a.artifact_type == "preview_url":
            payload = json.loads(a.content)
            payload["health_status"] = "unhealthy"
            a.content = json.dumps(payload)
            a.metadata_json = payload
    db = _mock_db(arts)
    result = await verify_delivery_evidence(db, _make_task())

    assert result.ok is False
    assert "preview_health" in result.missing


@pytest.mark.asyncio
async def test_missing_acceptance_fails():
    arts = [a for a in _full_evidence_artifacts() if a.artifact_type != "acceptance"]
    db = _mock_db(arts)
    result = await verify_delivery_evidence(db, _make_task())

    assert result.ok is False
    assert "acceptance" in result.missing


@pytest.mark.asyncio
async def test_acceptance_without_cues_fails():
    """A template-only acceptance with no URL/test/preview reference should fail."""
    arts = [a for a in _full_evidence_artifacts() if a.artifact_type != "acceptance"]
    arts.append(_artifact("acceptance", "这是验收记录，请签字。"))
    db = _mock_db(arts)
    result = await verify_delivery_evidence(db, _make_task())

    assert result.ok is False
    assert "acceptance_references_evidence" in result.missing


# ---------------------------------------------------------------------------
# Workspace draft toggle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workspace_allow_draft_flag_propagates():
    """When workspace.allow_draft_delivery=True, ok still reflects evidence
    but workspace_allows_draft surfaces for the API layer to degrade."""
    arts = [a for a in _full_evidence_artifacts() if a.artifact_type != "preview_url"]
    db = _mock_db(arts, workspace_allow_draft=True)
    result = await verify_delivery_evidence(db, _make_task(workspace_id=uuid.uuid4()))

    assert result.ok is False
    assert result.workspace_allows_draft is True


@pytest.mark.asyncio
async def test_workspace_default_blocks():
    arts = [a for a in _full_evidence_artifacts() if a.artifact_type != "preview_url"]
    db = _mock_db(arts, workspace_allow_draft=False)
    result = await verify_delivery_evidence(db, _make_task(workspace_id=uuid.uuid4()))

    assert result.ok is False
    assert result.workspace_allows_draft is False


# ---------------------------------------------------------------------------
# to_dict shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_to_dict_shape():
    db = _mock_db(_full_evidence_artifacts())
    result = await verify_delivery_evidence(db, _make_task())
    d = result.to_dict()

    assert set(d.keys()) >= {"ok", "summary", "workspace_allows_draft", "missing", "items"}
    assert isinstance(d["items"], list)
    for item in d["items"]:
        assert set(item.keys()) == {"category", "key", "ok", "detail"}
        assert item["category"] in {"test", "preview", "evidence"}
