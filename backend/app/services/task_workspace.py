"""Task-level workspace directory service (issuse21 Phase 1).

Physical layout per task:
    {WORKSPACE_ROOT}/tasks/TASK-{id}-{slug}/
        manifest.json
        docs/
            00-brief.md
            01-prd.md
            02-ui-spec.md
            03-architecture.md
            04-implementation-notes.md
            05-test-report.md
            06-acceptance.md
            07-ops-runbook.md
        screenshots/
        logs/
        artifacts/
    {WORKSPACE_ROOT}/shared/templates/   (canonical doc templates)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..config import settings

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

DOC_SPECS: list[dict[str, str]] = [
    {"name": "00-brief.md",                "title": "Brief"},
    {"name": "01-prd.md",                  "title": "PRD"},
    {"name": "02-ui-spec.md",              "title": "UI Spec"},
    {"name": "03-architecture.md",         "title": "Architecture"},
    {"name": "04-implementation-notes.md", "title": "Implementation Notes"},
    {"name": "05-test-report.md",          "title": "Test Report"},
    {"name": "06-acceptance.md",           "title": "Acceptance"},
    {"name": "07-ops-runbook.md",          "title": "Ops Runbook"},
]

STAGE_TO_DOC = {
    "planning":      "01-prd.md",
    "design":        "02-ui-spec.md",
    "architecture":  "03-architecture.md",
    "development":   "04-implementation-notes.md",
    "testing":       "05-test-report.md",
    "reviewing":     "06-acceptance.md",
    "deployment":    "07-ops-runbook.md",
}

_SUBDIRS = ("docs", "screenshots", "logs", "artifacts")


def _placeholder_doc_content(spec: dict[str, str]) -> str:
    return f"# {spec['title']}\n\n*(模板待填写)*\n"


def ensure_global_workspace_dirs() -> Path:
    """Create workspace root, tasks/, shared/templates at process startup (issuse23)."""
    root = _workspace_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "tasks").mkdir(parents=True, exist_ok=True)
    _ensure_shared_templates()
    return root


def _workspace_root() -> Path:
    if settings.workspace_root:
        return Path(settings.workspace_root)
    return _REPO_ROOT / "data" / "workspace"


def _slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]", "-", text.strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:max_len] or "untitled"


def task_dir_name(task_id: str, title: str = "") -> str:
    slug = _slugify(title) if title else "untitled"
    return f"TASK-{task_id}-{slug}"


def find_task_root(task_id: str) -> Optional[Path]:
    tasks_dir = _workspace_root() / "tasks"
    if not tasks_dir.exists():
        return None
    prefix = f"TASK-{task_id}"
    matches = sorted(
        d for d in tasks_dir.iterdir()
        if d.is_dir() and d.name.startswith(prefix)
    )
    return matches[0] if matches else None


def get_task_root(task_id: str, title: str = "") -> Path:
    exact = _workspace_root() / "tasks" / task_dir_name(task_id, title)
    if exact.exists():
        return exact
    existing = find_task_root(task_id)
    return existing or exact


def get_shared_templates_dir() -> Path:
    return _workspace_root() / "shared" / "templates"


def _ensure_shared_templates() -> Path:
    """Create canonical placeholder templates in shared/templates/."""
    tpl_dir = get_shared_templates_dir()
    tpl_dir.mkdir(parents=True, exist_ok=True)
    for spec in DOC_SPECS:
        dest = tpl_dir / spec["name"]
        if dest.exists():
            continue
        dest.write_text(_placeholder_doc_content(spec), encoding="utf-8")
    return tpl_dir


def _write_manifest(task_path: Path, task_id: str, title: str) -> None:
    manifest = {
        "task_id": task_id,
        "title": title,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "docs": {},
    }
    for spec in DOC_SPECS:
        doc_path = task_path / "docs" / spec["name"]
        manifest["docs"][spec["name"]] = {
            "title": spec["title"],
            "exists": doc_path.exists(),
            "updated_at": (
                datetime.fromtimestamp(doc_path.stat().st_mtime, tz=timezone.utc).isoformat()
                if doc_path.exists() else None
            ),
        }
    (task_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def ensure_task_workspace(task_id: str, title: str = "") -> Path:
    """Create (or return existing) per-task workspace directory.

    Idempotent: safe to call on every stage transition.
    """
    def _create() -> Path:
        task_path = get_task_root(task_id, title)

        if task_path.exists():
            (task_path / "docs").mkdir(exist_ok=True)
            for spec in DOC_SPECS:
                dest = task_path / "docs" / spec["name"]
                if not dest.exists():
                    dest.write_text(_placeholder_doc_content(spec), encoding="utf-8")
            for extra in ("src", "config", "deploy"):
                (task_path / extra).mkdir(exist_ok=True)
            _write_manifest(task_path, task_id, title)
            return task_path

        task_path.mkdir(parents=True, exist_ok=True)
        for sub in _SUBDIRS:
            (task_path / sub).mkdir(exist_ok=True)
        for extra in ("src", "config", "deploy"):
            (task_path / extra).mkdir(exist_ok=True)

        for spec in DOC_SPECS:
            dest = task_path / "docs" / spec["name"]
            dest.write_text(_placeholder_doc_content(spec), encoding="utf-8")

        _write_manifest(task_path, task_id, title)
        logger.info("Created task workspace: %s", task_path)
        return task_path

    return await asyncio.to_thread(_create)


async def write_task_doc(
    task_id: str,
    title: str,
    doc_name: str,
    content: str,
) -> Path:
    """Write content to a specific doc inside a task workspace."""
    def _write() -> Path:
        task_path = get_task_root(task_id, title)
        if not task_path.exists():
            raise FileNotFoundError(f"Task workspace not found: {task_path}")
        doc_path = task_path / "docs" / doc_name
        doc_path.write_text(content, encoding="utf-8")
        _write_manifest(task_path, task_id, title)
        return doc_path

    return await asyncio.to_thread(_write)


async def read_task_doc(task_id: str, title: str, doc_name: str) -> Optional[str]:
    def _read() -> Optional[str]:
        doc_path = get_task_root(task_id, title) / "docs" / doc_name
        if doc_path.exists():
            return doc_path.read_text(encoding="utf-8")
        return None

    return await asyncio.to_thread(_read)


async def list_task_docs(task_id: str, title: str) -> list[dict[str, Any]]:
    def _list() -> list[dict[str, Any]]:
        task_path = get_task_root(task_id, title)
        result: list[dict[str, Any]] = []
        for spec in DOC_SPECS:
            doc_path = task_path / "docs" / spec["name"]
            result.append({
                "name": spec["name"],
                "title": spec["title"],
                "exists": doc_path.exists(),
                "updated_at": (
                    doc_path.stat().st_mtime * 1000 if doc_path.exists() else None
                ),
            })
        return result

    return await asyncio.to_thread(_list)


async def write_stage_output_v2(
    task_id: str, title: str, stage_id: str, content: str
) -> Optional[Path]:
    """Write pipeline stage output into the task-scoped doc (replaces global write_stage_output)."""
    doc_name = STAGE_TO_DOC.get(stage_id)
    if not doc_name:
        return None
    await ensure_task_workspace(task_id, title)
    return await write_task_doc(task_id, title, doc_name, content)
