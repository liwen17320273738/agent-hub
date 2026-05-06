"""
Spec Adapter — import/export spec-kit compatible specification bundles.

Spec-Kit directory structure:
::
    specs/
    ├── 001-feature-name/
    │   ├── constitution.md    # Project principles & constraints
    │   ├── spec.md            # Specification / PRD
    │   ├── plan.md            # Technical plan / architecture
    │   └── tasks.md           # Task breakdown

Agent Hub mapping:
    spec.md   ↔  01-prd.md      (artifact type "prd")
    plan.md   ↔  03-architecture.md  (artifact type "architecture")
    tasks.md  ↔  task breakdown      (artifact type "implementation")
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.pipeline import PipelineTask, PipelineStage
from ..models.task_artifact import TaskArtifact
from ..services.artifact_writer import write_taskartifact

logger = logging.getLogger(__name__)

# ── Spec-kit file names ──────────────────────────────────────────────────

CONSTITUTION_FILE = "constitution.md"
SPEC_FILE = "spec.md"
PLAN_FILE = "plan.md"
TASKS_FILE = "tasks.md"

SPEC_FILES = {CONSTITUTION_FILE, SPEC_FILE, PLAN_FILE, TASKS_FILE}

# ── Mapping: spec-kit filename → agent-hub artifact type ────────────────

FILE_TO_ARTIFACT_TYPE = {
    CONSTITUTION_FILE: "brief",          # Project brief / principles
    SPEC_FILE: "prd",                    # PRD / specification
    PLAN_FILE: "architecture",           # Architecture / tech plan
    TASKS_FILE: "implementation",        # Implementation / task breakdown
}

# ── Mapping: agent-hub artifact type → spec-kit filename ────────────────

ARTIFACT_TYPE_TO_FILE = {v: k for k, v in FILE_TO_ARTIFACT_TYPE.items()}


# ── Import: spec-kit directory → PipelineTask ───────────────────────────


async def import_spec_kit_dir(
    db: AsyncSession,
    *,
    root_path: str,
    title: Optional[str] = None,
    org_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Scan a spec-kit directory and create a PipelineTask from it.

    Expects a root directory containing subdirectories, each of which
    is a spec-kit feature bundle (e.g. ``001-login/spec.md``).

    If a single spec-kit bundle directory is given (contains at least one
    of the SPEC_FILES), treats it as the only feature. Otherwise scans
    subdirectories and merges them.
    """
    root = Path(root_path).resolve()
    if not root.is_dir():
        return {"ok": False, "error": f"Directory not found: {root_path}"}

    # 1. Discover spec-kit bundles (directories containing spec-kit files)
    bundles: List[Path] = []
    if _is_spec_bundle_dir(root):
        bundles = [root]
    else:
        for sub_dir in sorted(root.iterdir()):
            if sub_dir.is_dir() and _is_spec_bundle_dir(sub_dir):
                bundles.append(sub_dir)

    if not bundles:
        return {"ok": False, "error": f"No spec-kit bundles found in {root_path}"}

    # 2. Read all files across bundles
    merged: Dict[str, List[str]] = {
        CONSTITUTION_FILE: [],
        SPEC_FILE: [],
        PLAN_FILE: [],
        TASKS_FILE: [],
    }
    feature_names: List[str] = []
    for bundle_dir in bundles:
        feature_names.append(bundle_dir.name)
        for fname in SPEC_FILES:
            fp = bundle_dir / fname
            if fp.exists():
                try:
                    content = fp.read_text(encoding="utf-8").strip()
                    if content:
                        merged[fname].append(f"## {bundle_dir.name}\n\n{content}")
                except Exception as e:
                    logger.warning(f"[spec-adapter] Failed to read {fp}: {e}")

    if not any(v for v in merged.values()):
        return {"ok": False, "error": "Spec-kit bundles exist but all files are empty"}

    # 3. Create PipelineTask with spec_driven template
    task_title = title or feature_names[0] if feature_names else "Spec-Driven Task"
    spec_content = "\n\n---\n\n".join(merged[SPEC_FILE]) if merged[SPEC_FILE] else ""
    plan_content = "\n\n---\n\n".join(merged[PLAN_FILE]) if merged[PLAN_FILE] else ""
    tasks_content = "\n\n---\n\n".join(merged[TASKS_FILE]) if merged[TASKS_FILE] else ""

    description = (
        f"# 规格\n\n{spec_content}" if spec_content else ""
    )
    if plan_content:
        description += f"\n\n# 技术计划\n\n{plan_content}"
    if tasks_content:
        description += f"\n\n# 任务\n\n{tasks_content}"

    from ..services.collaboration import PIPELINE_STAGES
    from uuid import uuid4

    task = PipelineTask(
        id=uuid4(),
        title=task_title,
        description=description,
        template="spec_driven",
        source="spec_import",
        created_by="spec_adapter",
        org_id=org_id,
        workspace_id=workspace_id,
    )
    db.add(task)
    await db.flush()

    # Create stages from spec_driven template
    for i, s in enumerate(PIPELINE_STAGES):
        stage = PipelineStage(
            task_id=task.id,
            stage_id=s["id"],
            label=s["label"],
            owner_role=s["role"],
            sort_order=i,
            status="active" if i == 0 else "pending",
        )
        db.add(stage)

    await db.flush()

    # 4. Write constitution + spec + plan as artifacts
    for fname, content_list in merged.items():
        if not content_list:
            continue
        full_content = "\n\n---\n\n".join(content_list)
        artifact_type = FILE_TO_ARTIFACT_TYPE.get(fname, "attachment")
        await write_taskartifact(
            db,
            task_id=str(task.id),
            artifact_type=artifact_type,
            content=full_content,
            stage_id="planning" if fname in (CONSTITUTION_FILE, SPEC_FILE) else "architecture",
            title=f"{task_title} — {fname.replace('.md', '')}",
        )

    await db.flush()
    logger.info(f"[spec-adapter] Imported {len(bundles)} bundles as task {task.id}")

    return {
        "ok": True,
        "task_id": str(task.id),
        "title": task_title,
        "bundles": [b.name for b in bundles],
        "stages_created": len(PIPELINE_STAGES),
    }


def _is_spec_bundle_dir(path: Path) -> bool:
    """Check if a directory contains spec-kit files."""
    if not path.is_dir():
        return False
    return any((path / f).exists() for f in SPEC_FILES)


# ── Export: PipelineTask → spec-kit directory ───────────────────────────


async def export_task_as_spec_kit(
    db: AsyncSession,
    task_id: str,
    output_dir: str,
) -> Dict[str, Any]:
    """Export a PipelineTask's artifacts as a spec-kit directory tree.

    The output structure:
    ::
        {output_dir}/
        ├── 001-{task-title}/
        │   ├── spec.md          (from artifact type "prd")
        │   ├── plan.md          (from artifact type "architecture")
        │   └── tasks.md         (from artifact type "implementation")
    """
    task = await db.get(PipelineTask, task_id)
    if not task:
        return {"ok": False, "error": f"Task not found: {task_id}"}

    # Fetch latest artifacts
    result = await db.execute(
        select(TaskArtifact).where(
            TaskArtifact.task_id == task_id,
            TaskArtifact.is_latest.is_(True),
        )
    )
    artifacts = result.scalars().all()

    if not artifacts:
        return {"ok": False, "error": "Task has no artifacts to export"}

    # Build output directory
    safe_title = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff\-]", "_", task.title)[:50]
    bundle_name = f"001-{safe_title}"
    bundle_dir = Path(output_dir) / bundle_name
    bundle_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for art in artifacts:
        target_file = ARTIFACT_TYPE_TO_FILE.get(art.artifact_type)
        if not target_file:
            continue
        fp = bundle_dir / target_file
        try:
            fp.write_text(art.content or "", encoding="utf-8")
            written += 1
        except Exception as e:
            logger.warning(f"[spec-adapter] Failed to write {fp}: {e}")

    if written == 0:
        return {"ok": False, "error": "No artifacts matched spec-kit types"}
    # Always write a constitution place holder if missing
    if not (bundle_dir / CONSTITUTION_FILE).exists():
        (bundle_dir / CONSTITUTION_FILE).write_text(
            f"# Constitution: {task.title}\n\n"
            f"Derived from agent-hub task {task_id}.\n"
            f"See spec.md for requirements and plan.md for technical approach.\n",
            encoding="utf-8",
        )

    logger.info(f"[spec-adapter] Exported task {task_id} → {bundle_dir}")
    return {
        "ok": True,
        "task_id": task_id,
        "output_path": str(bundle_dir),
        "files_written": written,
    }
