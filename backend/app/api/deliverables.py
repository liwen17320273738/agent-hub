"""
Deliverables API — zip download of task delivery docs.
"""
from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.pipeline import PipelineTask
from ..models.task_artifact import TaskArtifact
from ..services.task_workspace import get_task_root, DOC_SPECS
from ..services.share_token import verify_share_token
from ..security import get_pipeline_auth

# Map DOC_SPEC doc names → TaskArtifact.artifact_type
_DOC_NAME_TO_ARTIFACT_TYPE: dict[str, str] = {
    "00-brief.md":               "brief",
    "01-prd.md":                 "prd",
    "02-ui-spec.md":             "ui_spec",
    "03-architecture.md":        "architecture",
    "04-implementation-notes.md":"implementation",
    "05-test-report.md":         "test_report",
    "06-acceptance.md":          "acceptance",
    "07-ops-runbook.md":         "ops_runbook",
}

router = APIRouter(tags=["deliverables"])


@router.get("/tasks/{task_id}/deliverables.zip")
async def download_deliverables_zip(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_pipeline_auth),
):
    row = await db.execute(
        select(PipelineTask).where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return await _build_zip(db, task_id, task.title or "untitled", task.title)


@router.get("/share/{token}/deliverables.zip")
async def download_shared_deliverables_zip(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    task_id = verify_share_token(token)
    if not task_id:
        raise HTTPException(status_code=403, detail="分享链接无效或已过期")

    row = await db.execute(
        select(PipelineTask).where(PipelineTask.id == uuid.UUID(task_id))
    )
    task = row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return await _build_zip(db, task_id, task.title or "untitled", task.title)


async def _build_zip(db: AsyncSession, task_id: str, title: str, task_title: str) -> StreamingResponse:
    """Build a ZIP of task deliverables, reading from DB TaskArtifact when available,
    falling back to filesystem docs."""
    task_root = get_task_root(task_id, title)
    docs_dir = task_root / "docs"

    # Gather latest TaskArtifact content keyed by artifact_type
    tid = uuid.UUID(task_id) if isinstance(task_id, str) else task_id
    rows = await db.execute(
        select(TaskArtifact).where(
            and_(
                TaskArtifact.task_id == tid,
                TaskArtifact.is_latest.is_(True),
                TaskArtifact.status == "active",
            )
        )
    )
    artifacts_by_type: dict[str, TaskArtifact] = {a.artifact_type: a for a in rows.scalars().all()}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "task_id": task_id,
            "title": task_title,
            "exported_at": datetime.utcnow().isoformat(),
            "docs": [],
            "source": "db_task_artifact",
        }

        for spec in DOC_SPECS:
            doc_name = spec["name"]
            doc_path = docs_dir / doc_name

            # 1. Try DB TaskArtifact first
            art_type = _DOC_NAME_TO_ARTIFACT_TYPE.get(doc_name)
            artifact_content: str | None = None
            if art_type and art_type in artifacts_by_type:
                raw = artifacts_by_type[art_type].content
                if raw and raw.strip() and "(模板待填写)" not in raw:
                    artifact_content = raw

            if artifact_content:
                content = artifact_content
                manifest["docs"].append(doc_name)
            # 2. Fall back to filesystem (real written content)
            elif doc_path.exists():
                content = doc_path.read_text(encoding="utf-8")
                if "(模板待填写)" not in content or doc_name not in _DOC_NAME_TO_ARTIFACT_TYPE:
                    manifest["docs"].append(doc_name)
                else:
                    content = f"# {spec.get('title', doc_name)}\n\n> 待填写\n"
            # 3. Last resort: placeholder
            else:
                content = f"# {spec.get('title', doc_name)}\n\n> 待填写\n"

            zf.writestr(f"docs/{doc_name}", content)

        # Also include deploy artifacts: screenshot, preview_url, deploy_manifest
        for art_type_str in ("screenshot", "preview_url", "deploy_manifest", "build_log", "test_log", "source_manifest"):
            if art_type_str in artifacts_by_type:
                art = artifacts_by_type[art_type_str]
                subdir = "screenshots" if art_type_str == "screenshot" else "artifacts"
                ext = ".png" if art_type_str == "screenshot" else ".json" if art_type_str in ("preview_url", "deploy_manifest") else ".md"
                zf.writestr(f"{subdir}/{art_type_str}{ext}", art.content)
                manifest.setdefault("extra_artifacts", []).append(f"{subdir}/{art_type_str}{ext}")

        screenshots_dir = task_root / "screenshots"
        if screenshots_dir.exists():
            for img in screenshots_dir.iterdir():
                if img.is_file() and img.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                    zip_path = f"screenshots/{img.name}"
                    if zip_path not in zf.namelist():
                        zf.write(str(img), zip_path)

        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    buf.seek(0)
    safe_title = task_id[:8]
    from urllib.parse import quote
    display_name = task_title.replace("/", "-").replace("\\", "-")[:50] if task_title else safe_title
    filename_ascii = f"deliverables-{safe_title}.zip"
    filename_utf8 = quote(f"deliverables-{display_name}.zip")

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{filename_ascii}\"; "
                f"filename*=UTF-8''{filename_utf8}"
            ),
        },
    )
