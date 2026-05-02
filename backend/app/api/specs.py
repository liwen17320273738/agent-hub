"""
Spec API — import/export spec-kit compatible specification bundles.

Uses ``spec_driven`` pipeline template and the ``spec_adapter`` service.
"""
from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/specs", tags=["specs"])


class ImportRequest(BaseModel):
    root_path: str
    title: Optional[str] = None


class ExportRequest(BaseModel):
    output_dir: str


@router.post("/import")
async def import_spec_kit(
    body: ImportRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
):
    """Import a spec-kit directory and create a PipelineTask.

    Expects ``root_path`` pointing to a directory containing spec-kit bundles.
    Each bundle is a subdirectory with some/all of:
    ``constitution.md`` / ``spec.md`` / ``plan.md`` / ``tasks.md``

    Returns the created task ID and metadata.
    """
    from ..services.spec_adapter import import_spec_kit_dir

    result = await import_spec_kit_dir(
        db,
        root_path=body.root_path,
        title=body.title,
        org_id=str(_user.org_id) if _user.org_id else None,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Import failed"))
    return result


@router.post("/export/{task_id}")
async def export_task_spec(
    task_id: str,
    body: ExportRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
):
    """Export a PipelineTask's artifacts as a spec-kit directory.

    Outputs to ``output_dir`` on the server filesystem. Creates one
    bundle directory per task with ``spec.md`` / ``plan.md`` / ``tasks.md``
    mapped from the task's latest artifacts.
    """
    from ..services.spec_adapter import export_task_as_spec_kit

    result = await export_task_as_spec_kit(
        db,
        task_id=task_id,
        output_dir=body.output_dir,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Export failed"))
    return result
