"""
Memory API — search, browse, and manage memory layers.

GET  /memory/search        — Keyword / semantic search across long-term memory
GET  /memory/working/:id   — Working context for an active task
POST /memory/working/:id   — Set working context for a task
GET  /memory/patterns      — Learned patterns
GET  /memory/stats         — Memory usage statistics
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..security import get_current_user
from ..services.memory import (
    TaskMemory,
    LearnedPattern,
    search_similar_memories,
    get_working_context,
    set_working_context,
    clear_working_context,
    extract_patterns,
)

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/search")
async def search_memory(
    q: str = Query(..., min_length=2),
    role: Optional[str] = None,
    stage_id: Optional[str] = None,
    limit: int = Query(5, ge=1, le=20),
    min_quality: float = Query(0.0, ge=0, le=1),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    results = await search_similar_memories(
        db, query=q, role=role, stage_id=stage_id,
        limit=limit, min_quality=min_quality,
    )
    return {"results": results, "count": len(results)}


@router.get("/working/{task_id}")
async def get_task_working_memory(
    task_id: str,
    _user: User = Depends(get_current_user),
):
    ctx = await get_working_context(task_id)
    return {"taskId": task_id, "context": ctx}


class WorkingMemoryEntry(BaseModel):
    key: str
    value: str


@router.post("/working/{task_id}")
async def set_task_working_memory(
    task_id: str,
    body: WorkingMemoryEntry,
    _user: User = Depends(get_current_user),
):
    await set_working_context(task_id, body.key, body.value)
    return {"ok": True}


@router.delete("/working/{task_id}")
async def clear_task_working_memory(
    task_id: str,
    _user: User = Depends(get_current_user),
):
    await clear_working_context(task_id)
    return {"ok": True}


@router.get("/patterns")
async def list_patterns(
    role: Optional[str] = None,
    stage_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    stmt = select(LearnedPattern).order_by(LearnedPattern.confidence.desc())
    if role:
        stmt = stmt.where(LearnedPattern.role == role)
    if stage_id:
        stmt = stmt.where(LearnedPattern.stage_id == stage_id)
    stmt = stmt.limit(50)
    result = await db.execute(stmt)
    patterns = result.scalars().all()
    return {
        "patterns": [
            {
                "id": str(p.id), "type": p.pattern_type,
                "role": p.role, "stageId": p.stage_id,
                "description": p.description,
                "confidence": p.confidence, "frequency": p.frequency,
            }
            for p in patterns
        ],
    }


@router.get("/stats")
async def memory_stats(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    mem_count = await db.execute(select(func.count()).select_from(TaskMemory))
    pattern_count = await db.execute(select(func.count()).select_from(LearnedPattern))
    avg_quality = await db.execute(select(func.avg(TaskMemory.quality_score)))

    return {
        "totalMemories": mem_count.scalar() or 0,
        "totalPatterns": pattern_count.scalar() or 0,
        "avgQualityScore": round(avg_quality.scalar() or 0, 3),
    }
