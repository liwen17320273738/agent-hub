"""Regenerate missing UI mockup / architecture HTML when worktree or /tmp copies are gone."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.pipeline import PipelineTask
from ..models.task_artifact import TaskArtifact
from .task_workspace import ensure_task_workspace

logger = logging.getLogger(__name__)

_VISUAL_PREFIXES = ("ui_mockups/", "architecture_diagrams/")


def is_visual_asset_path(file_path: str) -> bool:
    rel = _normalize_visual_relative_path(file_path, "")
    return rel.startswith(_VISUAL_PREFIXES) and rel.lower().endswith(".html")


def _normalize_visual_relative_path(file_path: str, task_id: str) -> str:
    rel = file_path.replace("\\", "/").lstrip("/")
    if task_id:
        marker = f"{task_id}/"
        idx = rel.find(marker)
        if idx >= 0:
            tail = rel[idx + len(marker):]
            if tail.startswith(_VISUAL_PREFIXES):
                return tail
    for prefix in _VISUAL_PREFIXES:
        pos = rel.find(prefix)
        if pos >= 0:
            return rel[pos:]
    return rel


def find_visual_html_fallback(task_id: str, file_path: str) -> Optional[Path]:
    """Return any matching HTML in visual dirs when the exact stored filename drifted."""
    rel = _normalize_visual_relative_path(file_path, task_id)
    if not rel.startswith(_VISUAL_PREFIXES):
        return None

    subdir, _, basename = rel.partition("/")
    if not basename:
        return None

    roots: list[Path] = []
    from .task_workspace import find_task_root

    root = find_task_root(task_id)
    if root and root.exists():
        roots.append(root)

    workspace_root = Path(settings.workspace_root) if settings.workspace_root else (
        Path(__file__).resolve().parent.parent.parent.parent / "data" / "workspace"
    )
    roots.extend([
        Path("/tmp/agent-hub-ui") / task_id,
        workspace_root / task_id,
    ])

    stem = Path(basename).stem.lower()
    for base in roots:
        visual_dir = base / subdir
        if not visual_dir.is_dir():
            continue
        exact = visual_dir / basename
        if exact.is_file():
            return exact
        for candidate in sorted(visual_dir.glob("*.html")):
            if candidate.stem.lower() == stem:
                return candidate
        prefix = "ui-prototype-" if subdir == "ui_mockups" else "architecture-"
        for candidate in sorted(visual_dir.glob(f"{prefix}*.html")):
            return candidate
    return None


async def repair_visual_asset(
    db: AsyncSession,
    task_id: str,
    file_path: str,
) -> Optional[Path]:
    """Recreate missing visual HTML under the task worktree from stored stage artifacts."""
    rel = _normalize_visual_relative_path(file_path, task_id)
    if not rel.startswith(_VISUAL_PREFIXES):
        return None

    subdir = rel.split("/", 1)[0]
    row = await db.execute(
        select(PipelineTask).where(PipelineTask.id == uuid.UUID(task_id)),
    )
    task = row.scalar_one_or_none()
    if not task:
        return None

    worktree = await ensure_task_workspace(task_id, task.title or "untitled")
    from .ui_visualizer import UiVisualizer

    viz = UiVisualizer(
        workspace_root=settings.workspace_root,
        task_worktree=str(worktree),
    )

    if subdir == "ui_mockups":
        spec_row = await db.execute(
            select(TaskArtifact)
            .where(TaskArtifact.task_id == uuid.UUID(task_id))
            .where(TaskArtifact.artifact_type == "ui_spec")
            .where(TaskArtifact.is_latest.is_(True))
            .order_by(TaskArtifact.version.desc())
            .limit(1),
        )
        spec_art = spec_row.scalar_one_or_none()
        if not spec_art or not spec_art.content:
            return None
        result = await viz.generate_mockup(
            task_id=task_id,
            stage_id="design",
            design_spec=spec_art.content,
            project_name=task.title or "mockup",
        )
        html_rel = result.get("htmlPath") or ""
    else:
        spec_row = await db.execute(
            select(TaskArtifact)
            .where(TaskArtifact.task_id == uuid.UUID(task_id))
            .where(TaskArtifact.artifact_type == "architecture")
            .where(TaskArtifact.is_latest.is_(True))
            .order_by(TaskArtifact.version.desc())
            .limit(1),
        )
        spec_art = spec_row.scalar_one_or_none()
        if not spec_art or not spec_art.content:
            return None
        diagram = await viz.generate_architecture_diagram(
            task_id=task_id,
            stage_id="architecture",
            arch_spec=spec_art.content,
            project_name=task.title or "diagram",
        )
        html_rel = diagram.get("htmlPath") or ""

    if not html_rel:
        return None

    target = (worktree / html_rel).resolve()
    if target.is_file():
        logger.info("[visual-repair] regenerated %s for task %s", html_rel, task_id[:12])
        return target
    return None
