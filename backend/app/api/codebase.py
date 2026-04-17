"""Codebase semantic-index admin & search API.

Endpoints:
  POST   /codebase/reindex   — walk a project_dir, embed, upsert chunks
  POST   /codebase/search    — natural-language → top-K code chunks
  GET    /codebase/stats     — chunk count, file count, embedding model
  DELETE /codebase/{project_id} — purge all chunks for a project

`project_id` defaults to the absolute project_dir so the index doubles as
its own namespace. Override only when you want multiple snapshots of the
same path (e.g. branch-specific indexes).
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..security import get_current_user, require_admin
from ..services import codebase_indexer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/codebase", tags=["codebase"])


class ReindexBody(BaseModel):
    project_dir: str = Field(..., description="Absolute path or workspace path to index")
    project_id: Optional[str] = Field(None, description="Override (default: project_dir)")
    max_files: Optional[int] = Field(None, description="Cap on indexed files")
    embedding_model: Optional[str] = Field(None)
    embedding_provider: Optional[str] = Field(None)
    drop_first: bool = Field(False, description="Delete existing chunks before reindexing")


class SearchBody(BaseModel):
    project_id: Optional[str] = None
    project_dir: Optional[str] = None
    query: str = Field(..., min_length=1)
    top_k: int = 5
    embedding_model: Optional[str] = None
    embedding_provider: Optional[str] = None


@router.post("/reindex")
async def reindex(
    body: ReindexBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_admin)],
) -> Dict[str, Any]:
    if body.drop_first:
        pid = body.project_id or body.project_dir
        await codebase_indexer.drop_project(db, pid)
    result = await codebase_indexer.reindex_project(
        db,
        project_dir=body.project_dir,
        project_id=body.project_id,
        max_files=body.max_files,
        embedding_model=body.embedding_model or "",
        embedding_provider=body.embedding_provider or "",
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "reindex failed")
    return result


@router.post("/search")
async def search(
    body: SearchBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Dict[str, Any]:
    pid = body.project_id or body.project_dir or ""
    if not pid:
        raise HTTPException(status_code=400, detail="project_id or project_dir is required")
    result = await codebase_indexer.semantic_search(
        db,
        project_id=pid,
        query=body.query,
        top_k=body.top_k,
        embedding_model=body.embedding_model or "",
        embedding_provider=body.embedding_provider or "",
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "search failed")
    return result


@router.get("/stats")
async def stats(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Dict[str, Any]:
    return await codebase_indexer.project_stats(db, project_id)


@router.delete("/{project_id:path}")
async def drop(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_admin)],
) -> Dict[str, Any]:
    return await codebase_indexer.drop_project(db, project_id)
