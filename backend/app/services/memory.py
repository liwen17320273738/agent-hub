"""
Memory Layer — pgvector semantic retrieval + keyword fallback + working memory.

Three layers:
1. Long-term memory (TaskMemory table — pgvector embeddings + keyword search)
2. Working memory (WorkingContext Redis hash — per-task ephemeral state)
3. Learned patterns (LearnedPattern table — extracted best practices)

When pgvector extension is installed, vector similarity search is used.
Otherwise, falls back to PostgreSQL keyword search.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

import httpx
from sqlalchemy import Column, DateTime, String, Text, Integer, Float, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import Base
from ..compat import GUID, JsonDict, utcnow_default
from ..redis_client import get_redis, cache_get, cache_set

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1536
_PGVECTOR_AVAILABLE: Optional[bool] = None
_WORKING_MEMORY_TTL = 3600 * 4  # 4 hours


class TaskMemory(Base):
    """Long-term memory: embeddings + content for semantic retrieval."""
    __tablename__ = "task_memories"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    task_id = Column(String(200), index=True, nullable=False)
    stage_id = Column(String(50), nullable=False)
    role = Column(String(100), nullable=False)
    title = Column(String(500), default="")
    content = Column(Text, default="")
    content_hash = Column(String(64), unique=True, nullable=False)
    summary = Column(Text, default="")
    tags = Column(JsonDict(), default=list)
    quality_score = Column(Float, default=0.0)
    token_count = Column(Integer, default=0)
    embedding_model = Column(String(100), default="")
    metadata_extra = Column(JsonDict(), default=dict)
    created_at = Column(DateTime, server_default=utcnow_default())


class LearnedPattern(Base):
    """Patterns extracted from successful task completions."""
    __tablename__ = "learned_patterns"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    pattern_type = Column(String(50), nullable=False)
    role = Column(String(100), nullable=False)
    stage_id = Column(String(50), nullable=False)
    description = Column(Text, default="")
    example_task_ids = Column(JsonDict(), default=list)
    frequency = Column(Integer, default=1)
    confidence = Column(Float, default=0.5)
    created_at = Column(DateTime, server_default=utcnow_default())
    updated_at = Column(DateTime, server_default=utcnow_default())


# --- Working Memory (Redis-backed ephemeral context) ---

async def set_working_context(task_id: str, key: str, value: Any) -> None:
    """Store ephemeral working context for an active task."""
    r = get_redis()
    redis_key = f"working_memory:{task_id}"
    await r.hset(redis_key, key, json.dumps(value, ensure_ascii=False, default=str))
    await r.expire(redis_key, _WORKING_MEMORY_TTL)


async def get_working_context(task_id: str) -> Dict[str, Any]:
    """Retrieve all working context for a task."""
    r = get_redis()
    redis_key = f"working_memory:{task_id}"
    raw = await r.hgetall(redis_key)
    result = {}
    for k, v in raw.items():
        try:
            result[k] = json.loads(v)
        except (json.JSONDecodeError, TypeError):
            result[k] = v
    return result


async def clear_working_context(task_id: str) -> None:
    r = get_redis()
    await r.delete(f"working_memory:{task_id}")


async def store_memory(
    db: AsyncSession,
    *,
    task_id: str,
    stage_id: str,
    role: str,
    title: str,
    content: str,
    tags: Optional[List[str]] = None,
    quality_score: float = 0.0,
) -> Optional[TaskMemory]:
    """Store a stage output as a searchable memory entry."""
    if not content or len(content.strip()) < 20:
        return None

    content_hash = hashlib.sha256(content.encode()).hexdigest()

    existing = await db.execute(
        select(TaskMemory).where(TaskMemory.content_hash == content_hash)
    )
    if existing.scalar_one_or_none():
        return None

    summary = _extract_summary(content, max_len=500)
    token_count = len(content) // 4  # rough estimate

    memory = TaskMemory(
        task_id=task_id,
        stage_id=stage_id,
        role=role,
        title=title,
        content=content[:50000],  # cap storage
        content_hash=content_hash,
        summary=summary,
        tags=tags or [],
        quality_score=quality_score,
        token_count=token_count,
    )
    db.add(memory)
    await db.flush()
    logger.info(f"[memory] Stored memory for task={task_id} stage={stage_id}")
    return memory


async def search_similar_memories(
    db: AsyncSession,
    *,
    query: str,
    role: Optional[str] = None,
    stage_id: Optional[str] = None,
    limit: int = 5,
    min_quality: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    Search for similar historical task outputs.
    Uses keyword matching (PostgreSQL full-text search) as primary strategy.
    Vector search available when pgvector extension is installed.
    """
    cache_key = f"memory:search:{hashlib.md5(query.encode()).hexdigest()[:12]}:{role}:{stage_id}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    stmt = select(TaskMemory).where(TaskMemory.quality_score >= min_quality)

    if role:
        stmt = stmt.where(TaskMemory.role == role)
    if stage_id:
        stmt = stmt.where(TaskMemory.stage_id == stage_id)

    keywords = _extract_keywords(query)
    if keywords:
        conditions = []
        for kw in keywords[:5]:  # limit to 5 keywords
            conditions.append(TaskMemory.content.ilike(f"%{kw}%"))
        if conditions:
            from sqlalchemy import or_
            stmt = stmt.where(or_(*conditions))

    stmt = stmt.order_by(TaskMemory.quality_score.desc(), TaskMemory.created_at.desc())
    stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    memories = result.scalars().all()

    output = [
        {
            "task_id": m.task_id,
            "stage_id": m.stage_id,
            "role": m.role,
            "title": m.title,
            "summary": m.summary,
            "quality_score": m.quality_score,
            "tags": m.tags,
        }
        for m in memories
    ]

    await cache_set(cache_key, output, ttl=300)
    return output


async def get_context_from_history(
    db: AsyncSession,
    *,
    task_title: str,
    task_description: str,
    current_stage: str,
    current_role: str,
    task_id: Optional[str] = None,
    max_examples: int = 3,
) -> str:
    """Build a context string from working memory + similar historical tasks."""
    parts: List[str] = []

    # 1. Working memory (ephemeral, current task)
    if task_id:
        working_ctx = await get_working_context(task_id)
        if working_ctx:
            wm_lines = ["## 当前任务上下文"]
            for k, v in working_ctx.items():
                if isinstance(v, str) and len(v) > 500:
                    v = v[:500] + "..."
                wm_lines.append(f"- {k}: {v}")
            parts.append("\n".join(wm_lines))

    # 2. Learned patterns
    patterns = await extract_patterns(db, current_role, current_stage)
    if patterns:
        pat_lines = ["## 已学习模式"]
        for p in patterns[:3]:
            pat_lines.append(f"- [{p['type']}] {p['description']} (置信度: {p['confidence']:.0%})")
        parts.append("\n".join(pat_lines))

    # 3. Similar historical outputs
    query = f"{task_title} {task_description}"
    memories = await search_similar_memories(
        db,
        query=query,
        role=current_role,
        stage_id=current_stage,
        limit=max_examples,
        min_quality=0.3,
    )
    if memories:
        mem_lines = ["## 历史经验参考\n以下是类似任务的历史产出，仅供参考："]
        for i, mem in enumerate(memories, 1):
            mem_lines.append(
                f"### 参考 {i}: {mem['title']}\n"
                f"- 质量评分: {mem['quality_score']:.1f}\n"
                f"- 摘要: {mem['summary']}"
            )
        parts.append("\n".join(mem_lines))

    return "\n\n".join(parts)


async def update_quality_score(
    db: AsyncSession,
    task_id: str,
    stage_id: str,
    score: float,
) -> None:
    """Update quality score based on downstream stage success."""
    result = await db.execute(
        select(TaskMemory).where(
            TaskMemory.task_id == task_id,
            TaskMemory.stage_id == stage_id,
        )
    )
    memory = result.scalar_one_or_none()
    if memory:
        memory.quality_score = max(0.0, min(1.0, score))
        await db.flush()


async def extract_patterns(
    db: AsyncSession,
    role: str,
    stage_id: str,
    min_samples: int = 5,
) -> List[Dict[str, Any]]:
    """Extract learned patterns from high-quality historical outputs."""
    result = await db.execute(
        select(LearnedPattern).where(
            LearnedPattern.role == role,
            LearnedPattern.stage_id == stage_id,
            LearnedPattern.confidence >= 0.5,
        ).order_by(LearnedPattern.confidence.desc()).limit(10)
    )
    patterns = result.scalars().all()
    return [
        {
            "type": p.pattern_type,
            "description": p.description,
            "confidence": p.confidence,
            "frequency": p.frequency,
        }
        for p in patterns
    ]


def _extract_summary(content: str, max_len: int = 500) -> str:
    """Extract first meaningful paragraph as summary."""
    lines = content.strip().split("\n")
    summary_parts = []
    char_count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if summary_parts:
                break
            continue
        summary_parts.append(stripped)
        char_count += len(stripped)
        if char_count >= max_len:
            break
    return " ".join(summary_parts)[:max_len]


def _extract_keywords(text: str) -> List[str]:
    """Extract meaningful keywords for search."""
    import re
    words = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]{3,}', text)
    stopwords = {"the", "and", "for", "that", "this", "with", "from", "are", "was", "been"}
    return [w for w in words if w.lower() not in stopwords][:10]
