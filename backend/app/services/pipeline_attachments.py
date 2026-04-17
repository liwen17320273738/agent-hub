"""Pipeline task file uploads: store on disk, inject text + images into LLM prompts."""
from __future__ import annotations

import base64
import mimetypes
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.pipeline import PipelineArtifact, PipelineTask

TEXT_MAX_CHARS = 120_000
IMAGE_MAX_BYTES = 4 * 1024 * 1024
MAX_IMAGES_IN_PROMPT = 5

IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

TEXT_EXT = frozenset({
    ".txt", ".md", ".markdown", ".json", ".csv", ".xml", ".yaml", ".yml", ".toml",
    ".html", ".htm", ".css", ".js", ".ts", ".tsx", ".jsx", ".vue", ".mjs", ".cjs",
    ".py", ".rs", ".go", ".java", ".kt", ".swift", ".rb", ".php", ".cs", ".cpp", ".h", ".hpp",
    ".sql", ".sh", ".bash", ".zsh", ".env", ".gitignore", ".svg", ".log",
})


def get_upload_root() -> str:
    base = Path(__file__).resolve().parents[2]
    if settings.pipeline_upload_dir:
        root = settings.pipeline_upload_dir
        if not os.path.isabs(root):
            root = str(base / root)
    else:
        root = str(base / "data" / "pipeline_uploads")
    os.makedirs(root, exist_ok=True)
    return root


def _safe_filename(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^\w.\- \u4e00-\u9fff]", "_", base)
    base = (base[:120] or "file").strip("._")
    return base or "file"


async def save_upload_to_artifact(
    db: AsyncSession,
    task: PipelineTask,
    upload: UploadFile,
) -> PipelineArtifact:
    raw = await upload.read()
    max_b = settings.pipeline_upload_max_mb * 1024 * 1024
    if len(raw) > max_b:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过限制（最大 {settings.pipeline_upload_max_mb}MB）",
        )

    orig = _safe_filename(upload.filename or "upload")
    mime = (upload.content_type or "").split(";")[0].strip().lower()
    if not mime or mime == "application/octet-stream":
        guess, _ = mimetypes.guess_type(orig)
        mime = (guess or "application/octet-stream").lower()

    ext = Path(orig).suffix.lower()
    is_image = mime in IMAGE_MIMES or ext in {".png", ".jpg", ".jpeg", ".gif", ".webp"}

    artifact_id = uuid.uuid4()
    root = get_upload_root()
    sub = f"{task.id}/{artifact_id}_{orig}"
    path = os.path.join(root, sub)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(raw)

    if is_image:
        if mime == "image/jpg":
            mime = "image/jpeg"
        atype = "upload_image"
        text_content = ""
    else:
        atype = "upload_file"
        text_content = ""
        textish = (
            mime.startswith("text/")
            or mime
            in (
                "application/json",
                "application/xml",
                "application/javascript",
                "application/x-yaml",
            )
            or ext in TEXT_EXT
        )
        if textish:
            text_content = raw.decode("utf-8", errors="replace")
            if len(text_content) > TEXT_MAX_CHARS:
                text_content = text_content[:TEXT_MAX_CHARS] + "\n\n…(内容已截断)"

    meta: Dict[str, Any] = {
        "mime": mime,
        "size": len(raw),
        "storage_path": path,
        "original_filename": orig,
    }
    if atype == "upload_file" and not text_content:
        meta["binary_only"] = True

    art = PipelineArtifact(
        id=artifact_id,
        task_id=task.id,
        artifact_type=atype,
        name=orig,
        content=text_content,
        stage_id=task.current_stage_id or "planning",
        metadata_extra=meta,
    )
    db.add(art)
    await db.flush()
    return art


def try_resolve_storage_path(storage_path: str) -> Optional[str]:
    if not storage_path or not os.path.isfile(storage_path):
        return None
    root = Path(get_upload_root()).resolve()
    try:
        resolved = Path(storage_path).resolve()
        resolved.relative_to(root)
    except ValueError:
        return None
    return str(resolved) if resolved.is_file() else None


def resolve_storage_path_or_404(storage_path: str) -> str:
    p = try_resolve_storage_path(storage_path)
    if not p:
        raise HTTPException(status_code=404, detail="文件不存在")
    return p


async def attachment_prompt_extras(
    db: AsyncSession,
    task_id: str,
) -> Tuple[str, List[Tuple[str, str]]]:
    """Build extra user text + (mime, base64) pairs for Anthropic vision."""
    tid = uuid.UUID(task_id)
    stmt = (
        select(PipelineArtifact)
        .where(PipelineArtifact.task_id == tid)
        .where(PipelineArtifact.artifact_type.in_(("upload_image", "upload_file")))
        .order_by(PipelineArtifact.created_at.asc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    text_parts: List[str] = []
    images: List[Tuple[str, str]] = []

    for a in rows:
        meta = a.metadata_extra or {}
        if a.artifact_type == "upload_image":
            path = meta.get("storage_path")
            mime = (meta.get("mime") or "image/png").lower()
            if mime == "image/jpg":
                mime = "image/jpeg"
            if path and len(images) < MAX_IMAGES_IN_PROMPT:
                allowed = try_resolve_storage_path(path)
                if not allowed:
                    continue
                sz = os.path.getsize(allowed)
                if sz > IMAGE_MAX_BYTES:
                    text_parts.append(
                        f"- 图片「{a.name}」过大（{sz // 1024}KB），未嵌入模型上下文；"
                        "可在任务详情下载原图后人工参考。"
                    )
                    continue
                with open(allowed, "rb") as f:
                    b64 = base64.standard_b64encode(f.read()).decode("ascii")
                if mime not in IMAGE_MIMES:
                    mime = "image/png"
                images.append((mime, b64))
        else:
            block = f"### {a.name}\n"
            if a.content:
                block += a.content
            else:
                block += (
                    f"（二进制或不可解码为文本；MIME: {meta.get('mime', 'unknown')}）\n"
                    "可通过任务详情中的下载链接获取原文件。"
                )
            text_parts.append(block)

    text_block = ""
    if text_parts:
        text_block = "\n\n## 用户上传的文件\n" + "\n\n".join(text_parts)
    if images:
        text_block += (
            f"\n\n（另有 {len(images)} 张图片：已按各厂商 API 以多模态形式随最后一条用户消息发送；"
            "若该模型不支持视觉，路由会自动回退为纯文本，请结合上文文件说明理解需求。）"
        )

    return text_block, images
