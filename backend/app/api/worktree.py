"""Worktree File API — browse and preview files in a task's workspace directory.

Endpoints:
  GET /api/tasks/{task_id}/worktree              → file tree (JSON)
  GET /api/tasks/{task_id}/worktree/{path}       → file content (JSON)
  GET /api/tasks/{task_id}/worktree/raw/{path}   → raw file (HTML/PNG for iframe/img)
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Annotated, Optional

import mimetypes

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from ..config import settings
from ..database import get_db
from ..models.user import User
from ..security import get_pipeline_auth_optional
from ..services.task_workspace import find_task_root, DOC_SPECS
from ..services.visual_asset_repair import (
    find_visual_html_fallback,
    is_visual_asset_path,
    repair_visual_asset,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/tasks", tags=["worktree"])

_TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".html", ".css", ".scss", ".sass", ".less",
    ".json", ".yaml", ".yml", ".toml", ".md", ".txt", ".sh", ".sql", ".ps1", ".bat",
    ".java", ".go", ".rs", ".c", ".cpp", ".h", ".hpp", ".xml", ".csv", ".ini", ".cfg",
    ".env", ".gitignore", ".dockerfile", ".dockerignore", ".editorconfig", ".npmignore",
    ".lock", ".sum", ".mod", ".gradle", ".properties", ".conf", ".log",
    "Dockerfile", "Makefile", "README", "LICENSE", "CHANGELOG",
}

# Extensions considered "source code" (for src_files count)
_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".go", ".rs", ".java", ".kt", ".swift",
    ".cpp", ".c", ".h", ".hpp", ".cs", ".rb", ".php", ".dart", ".scala", ".r", ".m",
    ".sh", ".ps1", ".bat", ".html", ".css", ".scss", ".sass", ".less", ".sql",
}


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in _TEXT_EXTENSIONS or path.name in _TEXT_EXTENSIONS


def _is_code_file(path: Path) -> bool:
    return path.suffix.lower() in _CODE_EXTENSIONS or path.name in _CODE_EXTENSIONS


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except Exception:
        return ""


def _workspace_root() -> Path:
    if settings.workspace_root:
        return Path(settings.workspace_root)
    return Path(__file__).resolve().parent.parent.parent.parent / "data" / "workspace"


def _normalize_worktree_relative_path(file_path: str, task_id: str) -> str:
    """Map legacy absolute visual paths to worktree-relative paths."""
    rel = file_path.replace("\\", "/").lstrip("/")
    marker = f"{task_id}/"
    idx = rel.find(marker)
    if idx >= 0:
        tail = rel[idx + len(marker):]
        if tail.startswith(("ui_mockups/", "architecture_diagrams/")):
            return tail
    for prefix in ("ui_mockups/", "architecture_diagrams/"):
        pos = rel.find(prefix)
        if pos >= 0:
            return rel[pos:]
    return rel


def _resolve_worktree_file(task_id: str, file_path: str) -> Path:
    rel = _normalize_worktree_relative_path(file_path, task_id)
    root = find_task_root(task_id)

    if root and root.exists():
        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            raise HTTPException(403, "Path traversal denied")
        if candidate.is_file():
            return candidate

    # Legacy: visual assets written outside task worktree (/tmp or workspace/{task_id}/)
    legacy_roots = [
        Path("/tmp/agent-hub-ui") / task_id,
        _workspace_root() / task_id,
    ]
    for legacy_root in legacy_roots:
        legacy_candidate = (legacy_root / rel).resolve()
        if legacy_candidate.is_file():
            try:
                legacy_candidate.relative_to(legacy_root.resolve())
            except ValueError:
                continue
            return legacy_candidate

    raw = file_path.replace("\\", "/")
    if raw.startswith("/"):
        legacy_file = Path(raw)
        if legacy_file.is_file():
            for allowed in legacy_roots:
                try:
                    legacy_file.resolve().relative_to(allowed.resolve())
                    return legacy_file.resolve()
                except ValueError:
                    continue

    fallback = find_visual_html_fallback(task_id, file_path)
    if fallback:
        return fallback

    raise HTTPException(404, f"File not found: {file_path}")


def _guess_media_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime
    if path.suffix.lower() == ".html":
        return "text/html; charset=utf-8"
    return "application/octet-stream"


@router.get("/{task_id}/worktree")
async def list_worktree(
    task_id: str,
    _user: Annotated[Optional[User], Depends(get_pipeline_auth_optional)],
):
    """Return the full file tree of a task's workspace."""
    root = find_task_root(task_id)
    if not root or not root.exists():
        raise HTTPException(404, f"Task workspace not found: {task_id}")

    tree = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip archive and hidden directories
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "_archive"]
        rel_dir = Path(dirpath).relative_to(root)
        for fn in sorted(filenames):
            if fn.startswith("."):
                continue
            fp = Path(dirpath) / fn
            rel = rel_dir / fn
            stat = fp.stat()
            tree.append({
                "path": str(rel),
                "name": fn,
                "size": stat.st_size,
                "is_text": _is_text_file(fp),
                "is_code": _is_code_file(fp),
                "hash": _file_hash(fp),
                "modified_at": stat.st_mtime,
            })

    docs_status = []
    for spec in DOC_SPECS:
        doc_path = root / "docs" / spec["name"]
        exists = doc_path.exists()
        size = doc_path.stat().st_size if exists else 0
        has_content = size > 50 if exists else False
        docs_status.append({
            "name": spec["name"],
            "title": spec["title"],
            "exists": exists,
            "has_content": has_content,
            "size": size,
        })

    # Count all code files, not just those under src/
    src_files = [f for f in tree if f.get("is_code")]

    return {
        "task_id": task_id,
        "root": str(root),
        "total_files": len(tree),
        "total_src_files": len(src_files),
        "docs": docs_status,
        "files": tree,
    }


@router.get("/{task_id}/worktree/raw/{file_path:path}")
async def read_worktree_file_raw(
    task_id: str,
    file_path: str,
    _user: Annotated[Optional[User], Depends(get_pipeline_auth_optional)],
    db: AsyncSession = Depends(get_db),
):
    """Serve a worktree file with correct Content-Type for img/iframe preview."""
    try:
        target = _resolve_worktree_file(task_id, file_path)
    except HTTPException as exc:
        if exc.status_code == 404 and is_visual_asset_path(file_path):
            repaired = await repair_visual_asset(db, task_id, file_path)
            if repaired:
                target = repaired
            else:
                raise
        else:
            raise
    # NOTE: do NOT pass `filename=` to FileResponse — Starlette would then
    # emit `Content-Disposition: attachment; filename=...`, which forces the
    # browser to download the file instead of rendering it inline. The whole
    # point of /worktree/raw/ is iframe/<img> preview, so we omit the header
    # entirely and let `media_type` drive rendering (text/html → render,
    # image/png → display, application/octet-stream → fall-through download).
    return FileResponse(target, media_type=_guess_media_type(target))


@router.get("/{task_id}/worktree/{file_path:path}")
async def read_worktree_file(
    task_id: str,
    file_path: str,
    _user: Annotated[Optional[User], Depends(get_pipeline_auth_optional)],
    max_size: int = Query(default=500_000, le=2_000_000),
):
    """Read a single file from the task's workspace."""
    if file_path.startswith("raw/"):
        raise HTTPException(404, f"File not found: {file_path}")

    try:
        target = _resolve_worktree_file(task_id, file_path)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        root = find_task_root(task_id)
        if not root or not root.exists():
            raise HTTPException(404, f"Task workspace not found: {task_id}") from exc
        target = (root / file_path).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            raise HTTPException(403, "Path traversal denied") from exc
        if not target.exists():
            raise HTTPException(404, f"File not found: {file_path}") from exc

    if not target.exists():
        raise HTTPException(404, f"File not found: {file_path}")

    if not target.is_file():
        raise HTTPException(400, f"Not a file: {file_path}")

    stat = target.stat()
    if stat.st_size > max_size:
        raise HTTPException(413, f"File too large: {stat.st_size} bytes (max {max_size})")

    if not _is_text_file(target):
        return {
            "path": file_path,
            "size": stat.st_size,
            "is_text": False,
            "content": None,
            "message": "Binary file, content not returned",
        }

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(500, f"Failed to read file: {e}")

    return {
        "path": file_path,
        "size": stat.st_size,
        "is_text": True,
        "hash": _file_hash(target),
        "content": content,
    }
