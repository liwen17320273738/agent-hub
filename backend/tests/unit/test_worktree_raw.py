"""Tests for worktree raw file serving (visual artifact preview)."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.pipeline import PipelineTask
from app.models.task_artifact import TaskArtifact
from app.models.user import User


@pytest.mark.asyncio
async def test_worktree_raw_serves_legacy_visual_html():
    task_id = "5146d599-cadd-4595-a71b-42913886101e"
    legacy_root = Path("/tmp/agent-hub-ui") / task_id / "ui_mockups"
    legacy_root.mkdir(parents=True, exist_ok=True)
    html_file = legacy_root / "ui-prototype-demo.html"
    html_file.write_text("<!DOCTYPE html><html><body>mock</body></html>", encoding="utf-8")

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get(
                f"/api/tasks/{task_id}/worktree/raw/ui_mockups/ui-prototype-demo.html",
            )

        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
        assert "mock" in res.text
    finally:
        shutil.rmtree(Path("/tmp/agent-hub-ui") / task_id, ignore_errors=True)


@pytest.mark.asyncio
async def test_worktree_raw_repairs_missing_visual_html(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
):
    task_id = str(uuid.uuid4())
    task = PipelineTask(
        id=uuid.UUID(task_id),
        title="Repair Demo",
        description="demo",
        status="running",
        org_id=test_user.org_id,
        created_by=str(test_user.id),
    )
    db.add(task)
    db.add(
        TaskArtifact(
            task_id=uuid.UUID(task_id),
            artifact_type="ui_spec",
            title="ui_spec",
            content="# Design\nPrimary color blue\nLogin screen with hero",
            version=1,
            is_latest=True,
            status="active",
        ),
    )
    db.add(
        TaskArtifact(
            task_id=uuid.UUID(task_id),
            artifact_type="ui_mockup_html",
            title="ui_mockup_html",
            content="UI prototype",
            storage_path=(
                f"/tmp/agent-hub-ui/{task_id}/ui_mockups/ui-prototype-Repair Demo.html"
            ),
            version=1,
            is_latest=True,
            status="active",
            metadata_json={
                "filePath": (
                    f"/tmp/agent-hub-ui/{task_id}/ui_mockups/ui-prototype-Repair Demo.html"
                ),
            },
        ),
    )
    await db.commit()

    workspace_tasks = Path(__file__).resolve().parents[2] / "data" / "workspace" / "tasks"
    prefix = f"TASK-{task_id}"
    try:
        res = await client.get(
            f"/api/tasks/{task_id}/worktree/raw/ui_mockups/ui-prototype-Repair%20Demo.html",
        )

        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
        assert "<html" in res.text.lower()
    finally:
        for d in workspace_tasks.glob(f"{prefix}-*"):
            shutil.rmtree(d, ignore_errors=True)


@pytest.mark.asyncio
async def test_worktree_raw_rejects_path_traversal():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/api/tasks/5146d599-cadd-4595-a71b-42913886101e/worktree/raw/../../etc/passwd",
        )
    assert res.status_code in (403, 404)
