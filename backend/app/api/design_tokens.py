"""Backend: Design Tokens API — reads .pen artifact and extracts design tokens.

GET /tasks/{task_id}/design-tokens → structured JSON of color/typography/spacing tokens.
"""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.task_artifact import TaskArtifact
from ..security import get_pipeline_auth_optional
from ..services.task_workspace import find_task_root

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["design-tokens"])


def _pen_variables_to_tokens(variables: list) -> dict:
    """Convert .pen variables array into categorized design tokens."""
    tokens: dict = {
        "colors": {},
        "typography": {},
        "spacing": {},
        "raw": variables,
    }
    for var in variables:
        name: str = var.get("name", "")
        value: str = var.get("value", "")
        if name.startswith("颜色/"):
            key = name.replace("颜色/", "")
            tokens["colors"][key] = value
        elif name.startswith("字体/"):
            key = name.replace("字体/", "")
            tokens["typography"][key] = value
        elif name.startswith("布局/"):
            key = name.replace("布局/", "")
            tokens["spacing"][key] = value
    return tokens


@router.get("/{task_id}/design-tokens")
async def get_design_tokens(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_pipeline_auth_optional),
):
    """Return structured design tokens for a task from the .pen artifact.

    Tries metadata cache first; falls back to reading the .pen file from disk.
    Returns empty tokens dict (not 404) when no design tokens exist yet.
    """
    # Check if tokens are already cached in artifact metadata
    result = await db.execute(
        select(TaskArtifact)
        .where(TaskArtifact.task_id == uuid.UUID(task_id))
        .where(TaskArtifact.artifact_type == "attachment")
        .where(TaskArtifact.is_latest.is_(True))
        .order_by(TaskArtifact.created_at.desc())
        .limit(5)
    )
    pen_artifacts = [
        a for a in result.scalars().all()
        if a.metadata_json.get("format") == "pen"
    ]

    if not pen_artifacts:
        return {"task_id": task_id, "tokens": {"colors": {}, "typography": {}, "spacing": {}}}

    pen_artifact = pen_artifacts[0]

    # Try metadata cache first
    cached = pen_artifact.metadata_json.get("designTokens")
    if cached:
        return {"task_id": task_id, "tokens": cached, "cached": True}

    # Fallback: read .pen file from worktree
    rel_path = pen_artifact.metadata_json.get("relativePath", "")
    root = find_task_root(task_id)

    if root and rel_path:
        pen_file = (root / rel_path).resolve()
        try:
            pen_file.relative_to(root.resolve())
        except ValueError:
            pen_file = None

        if pen_file and pen_file.is_file():
            try:
                doc = json.loads(pen_file.read_text(encoding="utf-8"))
                variables = doc.get("variables", [])
                tokens = _pen_variables_to_tokens(variables)

                # Cache for next time
                pen_artifact.metadata_json["designTokens"] = tokens
                db.add(pen_artifact)
                try:
                    await db.flush()
                except Exception:
                    await db.rollback()

                return {"task_id": task_id, "tokens": tokens, "cached": False}
            except Exception as e:
                logger.warning("[design-tokens] Failed to parse .pen file: %s", e)

    return {"task_id": task_id, "tokens": {"colors": {}, "typography": {}, "spacing": {}}}
