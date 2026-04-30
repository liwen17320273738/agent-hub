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
from ..security import get_pipeline_auth_optional
from ..services.task_workspace import get_task_root, find_task_root, DOC_SPECS

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


@router.get("/{task_id}/worktree/{file_path:path}")
async def read_worktree_file(
    task_id: str,
    file_path: str,
    _user: Annotated[Optional[User], Depends(get_pipeline_auth_optional)],
    max_size: int = Query(default=500_000, le=2_000_000),
):
    """Read a single file from the task's workspace."""
    root = find_task_root(task_id)
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
