"""
Memory Layer — pgvector semantic retrieval + keyword fallback + working memory.

Three layers:
1. Long-term memory (TaskMemory table — pgvector embeddings + keyword search)
2. Working memory (WorkingContext Redis hash — per-task ephemeral state)
3. Learned patterns (LearnedPattern table — extracted best practices)

When pgvector extension is installed, vector similarity search is used.
Otherwise, falls back to in-process cosine similarity or keyword search.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

import httpx
from sqlalchemy import select, func, text, String as SAString
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.memory import TaskMemory, LearnedPattern
from ..models.pipeline import PipelineTask
from ..redis_client import get_redis, cache_get, cache_set

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1536
_pgvector_checked = False
_pgvector_available = False
_WORKING_MEMORY_TTL = 3600 * 4  # 4 hours
_EMBEDDING_CACHE_TTL = 3600 * 24 * 7  # 7 days


async def _check_pgvector(db: AsyncSession) -> bool:
    """Check once if pgvector extension is available in the current database."""
    global _pgvector_checked, _pgvector_available
    if _pgvector_checked:
        return _pgvector_available
    _pgvector_checked = True
    try:
        from ..config import settings
        if "sqlite" in settings.database_url:
            _pgvector_available = False
            return False
        result = await db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
        _pgvector_available = result.scalar() is not None
        if _pgvector_available:
            logger.info("[memory] pgvector extension detected — using native vector search")
        else:
            logger.info("[memory] pgvector not installed — using in-process cosine similarity")
    except Exception as e:
        logger.warning(f"[memory] pgvector check failed: {e}")
        _pgvector_available = False
    return _pgvector_available


# --- Embedding helpers ---

def _cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


_EMBEDDING_PROVIDERS = [
    {
        "name": "zhipu",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "embedding-3",
    },
    {
        "name": "dashscope",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "text-embedding-v3",
    },
    {
        "name": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "text-embedding-3-small",
    },
]


async def _get_embedding(text: str) -> Optional[List[float]]:
    """Generate embedding via the first available provider with an API key."""
    from ..config import settings

    provider_keys = settings.get_provider_keys()
    if not provider_keys:
        return None

    for provider in _EMBEDDING_PROVIDERS:
        api_key = provider_keys.get(provider["name"])
        if not api_key:
            continue

        embed_url = f"{provider['base_url'].rstrip('/')}/embeddings"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    embed_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": provider["model"], "input": text[:8000]},
                )
                resp.raise_for_status()
                data = resp.json()
                return data["data"][0]["embedding"]
        except Exception as e:
            logger.warning(f"[memory] Embedding via {provider['name']} failed: {e}")
            continue

    return None


async def _cache_embedding(content_hash: str, embedding: List[float]) -> None:
    """Cache an embedding vector in Redis keyed by content hash."""
    r = get_redis()
    key = f"memory:embedding:{content_hash}"
    await r.set(key, json.dumps(embedding), ex=_EMBEDDING_CACHE_TTL)


async def _get_cached_embedding(content_hash: str) -> Optional[List[float]]:
    """Retrieve a cached embedding vector from Redis."""
    r = get_redis()
    raw = await r.get(f"memory:embedding:{content_hash}")
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


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

    embedding = await _get_embedding(f"{title} {summary}")

    memory = TaskMemory(
        task_id=task_id,
        stage_id=stage_id,
        role=role,
        title=title,
        content=content[:50000],
        content_hash=content_hash,
        summary=summary,
        tags=tags or [],
        quality_score=quality_score,
        token_count=token_count,
        embedding=embedding,
        embedding_model="text-embedding-3-small" if embedding else "",
    )
    db.add(memory)
    await db.flush()

    if embedding:
        await _cache_embedding(content_hash, embedding)
        logger.info(f"[memory] Stored memory + embedding for task={task_id} stage={stage_id}")
    else:
        logger.info(f"[memory] Stored memory (no embedding) for task={task_id} stage={stage_id}")

    return memory


async def search_similar_memories(
    db: AsyncSession,
    *,
    query: str,
    role: Optional[str] = None,
    stage_id: Optional[str] = None,
    limit: int = 5,
    min_quality: float = 0.0,
    org_id: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    Search for similar historical task outputs.

    Strategy (ordered by preference):
    1. pgvector: native cosine distance ordering in PostgreSQL (fastest, most accurate)
    2. In-process: fetch keyword candidates, re-rank by cosine similarity against DB/cached embeddings
    3. Keyword-only: quality + recency ordering when no embeddings available
    """
    cache_key = f"memory:search:{hashlib.md5(query.encode()).hexdigest()[:12]}:{role}:{stage_id}:{org_id}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    use_pgvector = await _check_pgvector(db)
    query_embedding = await _get_embedding(query)

    # --- Strategy 1: pgvector native search ---
    if use_pgvector and query_embedding:
        memories = await _pgvector_search(
            db, query_embedding,
            role=role, stage_id=stage_id, limit=limit,
            min_quality=min_quality, org_id=org_id,
        )
        if memories:
            output = _format_memory_results(memories)
            await cache_set(cache_key, output, ttl=300)
            return output

    # --- Strategy 2 & 3: keyword candidates + optional re-ranking ---
    candidate_limit = max(limit * 4, 20)
    stmt = select(TaskMemory).where(TaskMemory.quality_score >= min_quality)

    if org_id:
        org_task_ids = (
            select(func.cast(PipelineTask.id, SAString))
            .where(PipelineTask.org_id == org_id)
        )
        stmt = stmt.where(TaskMemory.task_id.in_(org_task_ids))
    if role:
        stmt = stmt.where(TaskMemory.role == role)
    if stage_id:
        stmt = stmt.where(TaskMemory.stage_id == stage_id)

    keywords = _extract_keywords(query)
    if keywords:
        conditions = []
        for kw in keywords[:5]:
            conditions.append(TaskMemory.content.ilike(f"%{kw}%"))
        if conditions:
            from sqlalchemy import or_
            stmt = stmt.where(or_(*conditions))

    stmt = stmt.order_by(TaskMemory.quality_score.desc(), TaskMemory.created_at.desc())
    stmt = stmt.limit(candidate_limit)

    result = await db.execute(stmt)
    memories = list(result.scalars().all())

    if not memories:
        await cache_set(cache_key, [], ttl=300)
        return []

    if query_embedding:
        scored: List[tuple] = []
        for m in memories:
            mem_embedding = m.embedding
            if not mem_embedding:
                mem_embedding = await _get_cached_embedding(m.content_hash)
            if mem_embedding:
                sim = _cosine_similarity(query_embedding, mem_embedding)
                blended = 0.7 * sim + 0.3 * m.quality_score
                scored.append((m, blended))
            else:
                scored.append((m, 0.3 * m.quality_score))
        scored.sort(key=lambda x: x[1], reverse=True)
        memories = [m for m, _ in scored[:limit]]
    else:
        memories = memories[:limit]

    output = _format_memory_results(memories)
    await cache_set(cache_key, output, ttl=300)
    return output


async def _pgvector_search(
    db: AsyncSession,
    query_embedding: List[float],
    *,
    role: Optional[str] = None,
    stage_id: Optional[str] = None,
    limit: int = 5,
    min_quality: float = 0.0,
    org_id: Optional[Any] = None,
) -> List[TaskMemory]:
    """Native pgvector cosine distance search."""
    try:
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        where_clauses = [
            "embedding IS NOT NULL",
            "quality_score >= :min_quality",
        ]
        if role:
            where_clauses.append("role = :role")
        if stage_id:
            where_clauses.append("stage_id = :stage_id")
        if org_id:
            where_clauses.append(
                "task_id IN (SELECT CAST(id AS VARCHAR) FROM pipeline_tasks WHERE org_id = :org_id)"
            )

        where_sql = " AND ".join(where_clauses)
        sql = text(f"""
            SELECT *, (embedding <=> :embedding::vector) AS distance
            FROM task_memories
            WHERE {where_sql}
            ORDER BY distance ASC
            LIMIT :limit
        """)

        params: Dict[str, Any] = {"embedding": embedding_str, "limit": limit, "min_quality": min_quality}
        if role:
            params["role"] = role
        if stage_id:
            params["stage_id"] = stage_id
        if org_id:
            params["org_id"] = str(org_id)

        result = await db.execute(sql, params)
        rows = result.fetchall()

        memories = []
        for row in rows:
            m = await db.get(TaskMemory, row.id)
            if m:
                memories.append(m)
        return memories
    except Exception as e:
        logger.warning(f"[memory] pgvector search failed, falling back: {e}")
        return []


def _format_memory_results(memories: List[TaskMemory]) -> List[Dict[str, Any]]:
    return [
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
        ).order_by(TaskMemory.created_at.desc())
        .limit(1)
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


async def store_learned_pattern(
    db: AsyncSession,
    *,
    role: str,
    stage_id: str,
    pattern_type: str,
    description: str,
    task_id: str,
) -> Optional[LearnedPattern]:
    """Store or update a learned pattern from successful task completion."""
    existing = await db.execute(
        select(LearnedPattern).where(
            LearnedPattern.role == role,
            LearnedPattern.stage_id == stage_id,
            LearnedPattern.description == description,
        )
    )
    pattern = existing.scalar_one_or_none()

    if pattern:
        pattern.frequency += 1
        pattern.confidence = min(1.0, pattern.confidence + 0.05)
        examples = pattern.example_task_ids or []
        if task_id not in examples:
            examples.append(task_id)
            pattern.example_task_ids = examples[-20:]  # keep last 20
        await db.flush()
        return pattern

    pattern = LearnedPattern(
        pattern_type=pattern_type,
        role=role,
        stage_id=stage_id,
        description=description,
        example_task_ids=[task_id],
        frequency=1,
        confidence=0.5,
    )
    db.add(pattern)
    await db.flush()
    return pattern
