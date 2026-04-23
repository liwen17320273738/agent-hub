"""Workflow Builder save slot CRUD.

REST surface (all under ``/api/workflows``)
==========================================
* ``GET    /``               — list this caller's workflows (org-scoped)
* ``POST   /``               — create a workflow from a ``WorkflowDoc``
* ``GET    /{wf_id}``        — fetch one
* ``PATCH  /{wf_id}``        — partial update (name / description / doc)
* ``DELETE /{wf_id}``        — hard delete (no soft-delete; the doc is
                                cheap and the user explicitly asked)

The ``doc`` field is the verbatim ``WorkflowDoc`` from
``src/services/workflowBuilder.ts``. We deliberately do NOT validate
its inner shape on the server: the builder owns that schema, and a
strict server-side check would silently reject forwards-compatible
extensions (``runStatus`` overlays, future ``model_override`` keys,
etc.). We DO require the top-level keys we'd need to render a list:
``name`` (sanity) and ``doc`` being a JSON object.

Auth
====
Reuses ``get_pipeline_auth``: same bearer / API-key model the rest of
``/api/pipeline/*`` already uses. Org isolation matches
``pipeline.py``: rows with ``org_id IS NULL`` are visible to
unscoped callers (API keys); rows belonging to another org are never
returned.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..models.workflow import Workflow
from ..security import get_pipeline_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workflows", tags=["workflows"])


# ── Request / response shapes ─────────────────────────────────────

class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    doc: Dict[str, Any] = Field(default_factory=dict)


class WorkflowUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    doc: Optional[Dict[str, Any]] = None


def _serialize(wf: Workflow) -> Dict[str, Any]:
    return {
        "id": str(wf.id),
        "name": wf.name,
        "description": wf.description or "",
        "doc": wf.doc or {},
        "createdBy": wf.created_by,
        "orgId": str(wf.org_id) if wf.org_id else None,
        "createdAt": wf.created_at.isoformat() if wf.created_at else None,
        "updatedAt": wf.updated_at.isoformat() if wf.updated_at else None,
    }


def _scope_query(stmt, user: Optional[User]):
    """Apply the same org-isolation rule as ``pipeline.py``."""
    if user and user.org_id:
        stmt = stmt.where(Workflow.org_id == user.org_id)
    elif user is None:
        stmt = stmt.where(Workflow.org_id.is_(None))
    return stmt


def _parse_id(wf_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(wf_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 workflow id")


async def _get_or_404(
    db: AsyncSession, wf_id: str, user: Optional[User],
) -> Workflow:
    stmt = _scope_query(select(Workflow).where(Workflow.id == _parse_id(wf_id)), user)
    res = await db.execute(stmt)
    wf = res.scalar_one_or_none()
    if not wf:
        raise HTTPException(status_code=404, detail="workflow 不存在")
    return wf


# ── Routes ────────────────────────────────────────────────────────

@router.get("/")
async def list_workflows(
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    stmt = _scope_query(
        select(Workflow).order_by(Workflow.updated_at.desc()), user,
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {"workflows": [_serialize(w) for w in rows]}


@router.post("/", status_code=201)
async def create_workflow(
    body: WorkflowCreate,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not isinstance(body.doc, dict):
        raise HTTPException(status_code=400, detail="doc 必须是 JSON 对象")
    wf = Workflow(
        name=body.name.strip(),
        description=body.description or "",
        doc=body.doc,
        created_by=str(user.id) if user else "api",
        org_id=user.org_id if user else None,
    )
    db.add(wf)
    await db.flush()
    return {"workflow": _serialize(wf)}


@router.get("/{wf_id}")
async def get_workflow(
    wf_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    wf = await _get_or_404(db, wf_id, user)
    return {"workflow": _serialize(wf)}


@router.patch("/{wf_id}")
async def update_workflow(
    wf_id: str,
    body: WorkflowUpdate,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    wf = await _get_or_404(db, wf_id, user)
    if body.name is not None:
        wf.name = body.name.strip()
    if body.description is not None:
        wf.description = body.description
    if body.doc is not None:
        if not isinstance(body.doc, dict):
            raise HTTPException(status_code=400, detail="doc 必须是 JSON 对象")
        wf.doc = body.doc
    wf.updated_at = datetime.utcnow()
    await db.flush()
    return {"workflow": _serialize(wf)}


@router.delete("/{wf_id}", status_code=204)
async def delete_workflow(
    wf_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    wf = await _get_or_404(db, wf_id, user)
    await db.delete(wf)
    return None


@router.post("/{wf_id}/run")
async def run_workflow_endpoint(
    wf_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Compile and execute a saved workflow."""
    from ..services.workflow_compiler import compile_workflow
    from ..services.workflow_runner import run_workflow

    wf = await _get_or_404(db, wf_id, user)
    doc = wf.doc or {}

    if not doc.get("nodes"):
        raise HTTPException(status_code=400, detail="Workflow has no nodes")

    try:
        compiled = compile_workflow(doc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Compile error: {e}") from None

    result = await run_workflow(compiled)
    return {"run": result.to_dict()}
