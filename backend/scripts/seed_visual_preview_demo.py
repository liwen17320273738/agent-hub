"""Seed a dev task with real UI mockup + architecture diagram in task worktree.

Runs planning / design / architecture via ``execute_stage`` with mocked LLM only.
Prints task detail URL and raw preview paths for manual browser verification.

Usage:
    cd backend && python3 -m scripts.seed_visual_preview_demo
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

from dotenv import load_dotenv

load_dotenv("../.env")
load_dotenv(".env")
os.environ.setdefault("JWT_SECRET", os.environ.get("JWT_SECRET", "dev-secret-key-at-least-32-chars!!"))

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models.pipeline import PipelineTask
from app.models.task_artifact import TaskArtifact
from app.models.user import User
from app.services.cost_governor import BudgetDecision
from app.services.pipeline_engine import execute_stage
from app.services.task_workspace import ensure_task_workspace

HERO_SENTENCE = "做一个待办事项看板，支持新增、完成、删除任务。"
STAGES = ("planning", "design", "architecture")

_LLM: Dict[str, str] = {
    "planning": (
        "## 范围\n待办看板 MVP：新增、完成、删除任务。\n\n"
        "## 验收标准\n- AC1 列表 CRUD\n- AC2 空状态可见\n"
    ),
    "design": (
        "## UI 规格\n主区域待办列表；FAB 新建；每项含标题、完成勾选、删除按钮。\n"
    ),
    "architecture": (
        "## 技术方案\nVue 3 + Vite + Pinia；组件 TodoList / TodoItem。\n"
    ),
}


async def _budget_ok(*_a: Any, **_k: Any) -> BudgetDecision:
    return BudgetDecision(action="ok")


async def _fake_llm(**kwargs: Any) -> Dict[str, Any]:
    sid = _fake_llm.stage_id  # type: ignore[attr-defined]
    content = _LLM.get(sid, f"## {sid}\nstub\n")
    return {
        "content": content,
        "model": "seed-demo",
        "provider": "openai",
        "usage": {"prompt_tokens": 8, "completion_tokens": 32},
    }


async def main() -> int:
    settings.artifact_store_v2 = True
    settings.artifact_contract_enforce = True
    settings.ruflo_enabled = False

    async with async_session() as db:
        row = await db.execute(select(User).where(User.email == "admin@example.com").limit(1))
        admin = row.scalar_one_or_none()
        if admin is None:
            print("ERROR: admin@example.com not found — run make reset-admin", file=sys.stderr)
            return 1

        title = f"Visual preview demo {int(time.time())}"
        task = PipelineTask(
            id=uuid.uuid4(),
            title=title,
            description=HERO_SENTENCE,
            status="running",
            org_id=admin.org_id,
            created_by=str(admin.id),
        )
        db.add(task)
        await db.flush()
        task_id = str(task.id)
        await ensure_task_workspace(task_id, title)
        await db.commit()

    previous: Dict[str, str] = {}
    stage_holder = {"id": "planning"}

    async def _llm(**kwargs: Any) -> Dict[str, Any]:
        _fake_llm.stage_id = stage_holder["id"]  # type: ignore[attr-defined]
        return await _fake_llm(**kwargs)

    patches = [
        patch("app.services.cost_governor.pre_check_budget", _budget_ok),
        patch("app.services.llm_router.chat_completion_with_fallback", _llm),
        patch("app.services.pipeline_engine.llm_chat_with_fallback", _llm),
        patch("app.services.pipeline_engine._top_up_stage_output", lambda **_k: ""),
        patch("app.services.pipeline_engine.detect_build_command", lambda _wt: None),
    ]

    for p in patches:
        p.start()
    try:
        async with async_session() as db:
            for sid in STAGES:
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
                if not result.get("ok"):
                    # Mark the seeded task failed so it doesn't sit forever in
                    # 'running' status confusing the Inbox.
                    seeded = await db.get(PipelineTask, uuid.UUID(task_id))
                    if seeded is not None:
                        seeded.status = "failed"
                        seeded.current_stage_id = sid
                        await db.commit()
                    print(f"ERROR stage {sid} failed ({elapsed:.1f}s): {result}", file=sys.stderr)
                    return 1
                previous[sid] = result.get("content") or ""
                print(f"  ✓ {sid} ({elapsed:.1f}s)")

            # execute_stage() only writes artifacts; it does NOT drive the
            # PipelineTask status lifecycle (that's the pipeline_engine /
            # task_scheduler responsibility). Without this finalize the
            # seeded task is stuck at status='running' forever and shows up
            # as a fake "执行中" zombie in the Inbox.
            seeded = await db.get(PipelineTask, uuid.UUID(task_id))
            if seeded is not None:
                seeded.status = "done"
                seeded.current_stage_id = "done"
            await db.commit()

            rows = await db.execute(
                select(TaskArtifact).where(
                    TaskArtifact.task_id == uuid.UUID(task_id),
                    TaskArtifact.is_latest.is_(True),
                )
            )
            arts = rows.scalars().all()
    finally:
        for p in patches:
            p.stop()

    ui_mockup = next((a for a in arts if a.artifact_type == "ui_mockup"), None)
    arch = next((a for a in arts if a.artifact_type == "architecture_diagram"), None)

    def _file_path(art: TaskArtifact | None) -> str:
        if art is None:
            return ""
        meta = art.metadata_json or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except json.JSONDecodeError:
                meta = {}
        return str(meta.get("filePath") or art.storage_path or "")

    ui_path = _file_path(ui_mockup)
    arch_path = _file_path(arch)

    print()
    print("=== Visual preview demo ready ===")
    print(f"Task ID:   {task_id}")
    print(f"Title:     {title}")
    print(f"UI mockup: {ui_path or '(missing)'}")
    print(f"Arch diag: {arch_path or '(missing)'}")
    print()
    print("Browser:")
    print(f"  http://127.0.0.1:5200/#/pipeline/task/{task_id}")
    print()
    print("Raw API (after login):")
    if ui_path and not ui_path.startswith("/"):
        print(f"  /api/tasks/{task_id}/worktree/raw/{ui_path}")
    if arch_path and not arch_path.startswith("/"):
        print(f"  /api/tasks/{task_id}/worktree/raw/{arch_path}")

    if ui_path.startswith("/") or arch_path.startswith("/"):
        print("\nWARN: artifact paths are absolute — raw preview may need repair on first load.", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
