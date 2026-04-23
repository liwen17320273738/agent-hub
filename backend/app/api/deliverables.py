"""
Deliverables API — zip download of task delivery docs.
"""
from __future__ import annotations

import io
import uuid
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.pipeline import PipelineTask
from ..services.task_workspace import get_task_root, DOC_SPECS
from ..services.share_token import verify_share_token
from ..security import get_pipeline_auth

router = APIRouter(tags=["deliverables"])


@router.get("/api/tasks/{task_id}/deliverables.zip")
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

    return _build_zip(task_id, task.title or "untitled", task.title)


@router.get("/api/share/{token}/deliverables.zip")
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

    return _build_zip(task_id, task.title or "untitled", task.title)


def _build_zip(task_id: str, title: str, task_title: str) -> StreamingResponse:
    task_root = get_task_root(task_id, title)
    docs_dir = task_root / "docs"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "task_id": task_id,
            "title": task_title,
            "exported_at": datetime.utcnow().isoformat(),
            "docs": [],
        }

        for spec in DOC_SPECS:
            doc_path = docs_dir / spec["name"]
            if doc_path.exists():
                content = doc_path.read_text(encoding="utf-8")
                zf.writestr(f"docs/{spec['name']}", content)
                manifest["docs"].append(spec["name"])
            else:
                zf.writestr(f"docs/{spec['name']}", f"# {spec.get('title', spec['name'])}\n\n> 待填写\n")

        screenshots_dir = task_root / "screenshots"
        if screenshots_dir.exists():
            for img in screenshots_dir.iterdir():
                if img.is_file() and img.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                    zf.write(str(img), f"screenshots/{img.name}")

        import json
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
