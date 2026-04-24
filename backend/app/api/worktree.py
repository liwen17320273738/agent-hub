"""Worktree File API — browse and preview files in a task's workspace directory.

Endpoints:
  GET /api/tasks/{task_id}/worktree         → file tree
  GET /api/tasks/{task_id}/worktree/{path}  → file content
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from .pipeline import get_pipeline_auth
from ..services.task_workspace import get_task_root, DOC_SPECS

router = APIRouter(prefix="/tasks", tags=["worktree"])

_TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".html", ".css", ".scss",
    ".json", ".yaml", ".yml", ".toml", ".md", ".txt", ".sh", ".sql",
    ".java", ".go", ".rs", ".c", ".cpp", ".h", ".xml", ".csv",
    ".env", ".gitignore", ".dockerfile", "Dockerfile",
}


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in _TEXT_EXTENSIONS or path.name in _TEXT_EXTENSIONS


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except Exception:
        return ""


def _find_task_root(task_id: str) -> Optional[Path]:
    """Find the task root directory by scanning the workspace/tasks/ folder."""
    from ..services.task_workspace import _workspace_root
    tasks_dir = _workspace_root() / "tasks"
    if not tasks_dir.exists():
        return None
    prefix = f"TASK-{task_id}"
    for d in tasks_dir.iterdir():
        if d.is_dir() and d.name.startswith(prefix):
            return d
    return None


@router.get("/{task_id}/worktree")
async def list_worktree(
    task_id: str,
    _user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    """Return the full file tree of a task's workspace."""
    root = _find_task_root(task_id)
    if not root or not root.exists():
        raise HTTPException(404, f"Task workspace not found: {task_id}")

    tree = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        for fn in sorted(filenames):
            fp = Path(dirpath) / fn
            rel = rel_dir / fn
            stat = fp.stat()
            tree.append({
                "path": str(rel),
                "name": fn,
                "size": stat.st_size,
                "is_text": _is_text_file(fp),
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

    src_files = [f for f in tree if f["path"].startswith("src/")]

    return {
        "task_id": task_id,
        "root": str(root),
        "total_files": len(tree),
        "total_src_files": len(src_files),
        "docs": docs_status,
        "files": tree,
    }


@router.get("/{task_id}/worktree/{file_path:path}")
async def read_worktree_file(
    task_id: str,
    file_path: str,
    _user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    max_size: int = Query(default=500_000, le=2_000_000),
):
    """Read a single file from the task's workspace."""
    root = _find_task_root(task_id)
    if not root or not root.exists():
        raise HTTPException(404, f"Task workspace not found: {task_id}")

    target = (root / file_path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(403, "Path traversal denied")

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
