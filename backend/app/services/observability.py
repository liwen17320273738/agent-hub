"""
Observability — Pipeline Trace + Token 用量 + 耗时可视化

Dual-write architecture:
- Redis: hot cache for fast reads, TTL-based auto-expiry
- PostgreSQL: permanent store for historical queries and analytics

Redis keys:
- trace:{trace_id}            → PipelineTrace JSON (TTL 24h)
- span:{span_id}              → TraceSpan JSON (TTL 1h active, 24h completed)
- trace:{trace_id}:span_ids   → list of span IDs belonging to the trace
- traces:recent               → sorted set scored by started_at
- traces:task:{task_id}       → set of trace IDs for a task
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional, Dict, Any, List

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.observability import TraceRecord, SpanRecord
from ..database import async_session
from ..redis_client import get_redis, cache_get, cache_set

logger = logging.getLogger(__name__)

TRACE_TTL = 86400  # 24 hours
SPAN_ACTIVE_TTL = 3600  # 1 hour
SPAN_COMPLETED_TTL = 86400  # 24 hours


class TraceSpan(BaseModel):
    span_id: str = ""
    parent_span_id: Optional[str] = None
    trace_id: str = ""

    task_id: str
    stage_id: str
    role: str
    model: str = ""
    tier: str = ""

    status: str = "running"
    error: Optional[str] = None

    started_at: float = 0.0
    completed_at: float = 0.0
    duration_ms: int = 0

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0

    verify_status: Optional[str] = None
    verify_checks: List[Dict[str, Any]] = []

    guardrail_level: Optional[str] = None
    approval_id: Optional[str] = None

    input_length: int = 0
    output_length: int = 0
    retry_count: int = 0
    metadata: Dict[str, Any] = {}

    def __init__(self, **data):
        super().__init__(**data)
        if not self.span_id:
            self.span_id = str(uuid.uuid4())[:8]
        if not self.started_at:
            self.started_at = time.time()


class PipelineTrace(BaseModel):
    """Full trace of a pipeline execution."""
    trace_id: str = ""
    task_id: str
    task_title: str = ""

    status: str = "running"
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_ms: int = 0

    spans: List[TraceSpan] = []

    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_llm_calls: int = 0
    total_retries: int = 0

    models_used: Dict[str, int] = {}
    stage_durations: Dict[str, int] = {}

    def __init__(self, **data):
        super().__init__(**data)
        if not self.trace_id:
            self.trace_id = str(uuid.uuid4())[:12]
        if not self.started_at:
            self.started_at = time.time()


# ---------------------------------------------------------------------------
# DB persistence helpers (fire-and-forget, never block Redis path)
# ---------------------------------------------------------------------------

_db_persist_failure_count = 0
_DB_PERSIST_WARN_THRESHOLD = 5


async def _persist_trace_to_db(trace: PipelineTrace) -> None:
    global _db_persist_failure_count
    try:
        async with async_session() as db:
            result = await db.execute(
                select(TraceRecord).where(TraceRecord.trace_id == trace.trace_id)
            )
            record = result.scalar_one_or_none()
            if record:
                record.status = trace.status
                record.completed_at = trace.completed_at
                record.duration_ms = trace.duration_ms
                record.total_prompt_tokens = trace.total_prompt_tokens
                record.total_completion_tokens = trace.total_completion_tokens
                record.total_tokens = trace.total_tokens
                record.total_cost_usd = trace.total_cost_usd
                record.total_llm_calls = trace.total_llm_calls
                record.total_retries = trace.total_retries
                record.models_used = trace.models_used
                record.stage_durations = trace.stage_durations
            else:
                record = TraceRecord(
                    trace_id=trace.trace_id,
                    task_id=trace.task_id,
                    task_title=trace.task_title,
                    status=trace.status,
                    started_at=trace.started_at,
                    completed_at=trace.completed_at,
                    duration_ms=trace.duration_ms,
                    total_prompt_tokens=trace.total_prompt_tokens,
                    total_completion_tokens=trace.total_completion_tokens,
                    total_tokens=trace.total_tokens,
                    total_cost_usd=trace.total_cost_usd,
                    total_llm_calls=trace.total_llm_calls,
                    total_retries=trace.total_retries,
                    models_used=trace.models_used,
                    stage_durations=trace.stage_durations,
                )
                db.add(record)
            await db.commit()
            _db_persist_failure_count = 0
    except Exception as e:
        _db_persist_failure_count += 1
        level = logging.ERROR if _db_persist_failure_count >= _DB_PERSIST_WARN_THRESHOLD else logging.WARNING
        logger.log(level, f"[trace] DB persist trace failed ({_db_persist_failure_count}x): {e}")


async def _persist_span_to_db(span: TraceSpan) -> None:
    try:
        async with async_session() as db:
            result = await db.execute(
                select(SpanRecord).where(SpanRecord.span_id == span.span_id)
            )
            record = result.scalar_one_or_none()
            if record:
                record.status = span.status
                record.error = span.error
                record.completed_at = span.completed_at
                record.duration_ms = span.duration_ms
                record.prompt_tokens = span.prompt_tokens
                record.completion_tokens = span.completion_tokens
                record.total_tokens = span.total_tokens
                record.cost_usd = span.cost_usd
                record.output_length = span.output_length
                record.verify_status = span.verify_status
                record.verify_checks = span.verify_checks
                record.guardrail_level = span.guardrail_level
                record.approval_id = span.approval_id
                record.retry_count = span.retry_count
            else:
                record = SpanRecord(
                    span_id=span.span_id,
                    trace_id=span.trace_id,
                    parent_span_id=span.parent_span_id,
                    task_id=span.task_id,
                    stage_id=span.stage_id,
                    role=span.role,
                    model=span.model,
                    tier=span.tier,
                    status=span.status,
                    error=span.error,
                    started_at=span.started_at,
                    completed_at=span.completed_at,
                    duration_ms=span.duration_ms,
                    prompt_tokens=span.prompt_tokens,
                    completion_tokens=span.completion_tokens,
                    total_tokens=span.total_tokens,
                    cost_usd=span.cost_usd,
                    input_length=span.input_length,
                    output_length=span.output_length,
                    verify_status=span.verify_status,
                    verify_checks=span.verify_checks,
                    guardrail_level=span.guardrail_level,
                    approval_id=span.approval_id,
                    retry_count=span.retry_count,
                    metadata_extra=span.metadata,
                )
                db.add(record)
            await db.commit()
    except Exception as e:
        logger.error(f"[trace] DB persist span failed: {e}")


async def _load_trace_from_db(trace_id: str) -> Optional[PipelineTrace]:
    """Fall back to DB when Redis cache has expired."""
    try:
        async with async_session() as db:
            result = await db.execute(
                select(TraceRecord).where(TraceRecord.trace_id == trace_id)
            )
            record = result.scalar_one_or_none()
            if not record:
                return None
            return PipelineTrace(
                trace_id=record.trace_id,
                task_id=record.task_id,
                task_title=record.task_title,
                status=record.status,
                started_at=record.started_at,
                completed_at=record.completed_at,
                duration_ms=record.duration_ms,
                total_prompt_tokens=record.total_prompt_tokens,
                total_completion_tokens=record.total_completion_tokens,
                total_tokens=record.total_tokens,
                total_cost_usd=record.total_cost_usd,
                total_llm_calls=record.total_llm_calls,
                total_retries=record.total_retries,
                models_used=record.models_used or {},
                stage_durations=record.stage_durations or {},
            )
    except Exception as e:
        logger.warning(f"[trace] DB load trace failed: {e}")
        return None


async def _load_spans_from_db(trace_id: str) -> List[TraceSpan]:
    """Load all spans for a trace from DB."""
    try:
        async with async_session() as db:
            result = await db.execute(
                select(SpanRecord).where(SpanRecord.trace_id == trace_id)
                .order_by(SpanRecord.started_at)
            )
            records = result.scalars().all()
            return [
                TraceSpan(
                    span_id=r.span_id,
                    trace_id=r.trace_id,
                    parent_span_id=r.parent_span_id,
                    task_id=r.task_id,
                    stage_id=r.stage_id,
                    role=r.role,
                    model=r.model,
                    tier=r.tier,
                    status=r.status,
                    error=r.error,
                    started_at=r.started_at,
                    completed_at=r.completed_at,
                    duration_ms=r.duration_ms,
                    prompt_tokens=r.prompt_tokens,
                    completion_tokens=r.completion_tokens,
                    total_tokens=r.total_tokens,
                    cost_usd=r.cost_usd,
                    input_length=r.input_length,
                    output_length=r.output_length,
                    verify_status=r.verify_status,
                    verify_checks=r.verify_checks or [],
                    guardrail_level=r.guardrail_level,
                    approval_id=r.approval_id,
                    retry_count=r.retry_count,
                    metadata=r.metadata_extra or {},
                )
                for r in records
            ]
    except Exception as e:
        logger.warning(f"[trace] DB load spans failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Redis cache helpers
# ---------------------------------------------------------------------------

async def _save_trace(trace: PipelineTrace) -> None:
    """Persist trace to Redis + DB."""
    data = trace.model_dump()
    data["spans"] = []
    await cache_set(f"trace:{trace.trace_id}", data, ttl=TRACE_TTL)
    await _persist_trace_to_db(trace)


async def _load_trace(trace_id: str) -> Optional[PipelineTrace]:
    """Load trace: try Redis first, fall back to DB."""
    data = await cache_get(f"trace:{trace_id}")
    if data is not None:
        data["spans"] = []
        return PipelineTrace(**data)
    return await _load_trace_from_db(trace_id)


async def _load_span(span_id: str) -> Optional[TraceSpan]:
    data = await cache_get(f"span:{span_id}")
    if data is None:
        return None
    return TraceSpan(**data)


async def _get_trace_span_ids(trace_id: str) -> List[str]:
    r = get_redis()
    raw = await r.lrange(f"trace:{trace_id}:span_ids", 0, -1)
    return [sid.decode() if isinstance(sid, bytes) else sid for sid in (raw or [])]


async def _load_all_spans(trace_id: str) -> List[TraceSpan]:
    """Load spans: try Redis first, fall back to DB."""
    span_ids = await _get_trace_span_ids(trace_id)
    if span_ids:
        spans: List[TraceSpan] = []
        for sid in span_ids:
            span = await _load_span(sid)
            if span:
                spans.append(span)
        if spans:
            return spans
    return await _load_spans_from_db(trace_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def start_trace(task_id: str, task_title: str = "") -> PipelineTrace:
    """Start a new pipeline trace."""
    trace = PipelineTrace(task_id=task_id, task_title=task_title)

    r = get_redis()
    await _save_trace(trace)
    await r.zadd("traces:recent", {trace.trace_id: trace.started_at})
    await r.sadd(f"traces:task:{task_id}", trace.trace_id)

    logger.info(f"[trace] Started trace {trace.trace_id} for task {task_id}")
    return trace


async def start_span(
    trace_id: str,
    task_id: str,
    stage_id: str,
    role: str,
    model: str = "",
    tier: str = "",
    parent_span_id: Optional[str] = None,
    input_length: int = 0,
) -> TraceSpan:
    """Start a new span within a trace."""
    span = TraceSpan(
        trace_id=trace_id,
        task_id=task_id,
        stage_id=stage_id,
        role=role,
        model=model,
        tier=tier,
        parent_span_id=parent_span_id,
        input_length=input_length,
    )

    r = get_redis()
    await cache_set(f"span:{span.span_id}", span.model_dump(), ttl=SPAN_ACTIVE_TTL)
    await r.rpush(f"trace:{trace_id}:span_ids", span.span_id)
    await r.expire(f"trace:{trace_id}:span_ids", TRACE_TTL)

    await _persist_span_to_db(span)

    return span


async def complete_span(
    span_id: str,
    *,
    status: str = "completed",
    output_length: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_usd: float = 0.0,
    error: Optional[str] = None,
    verify_status: Optional[str] = None,
    verify_checks: Optional[List[Dict[str, Any]]] = None,
    guardrail_level: Optional[str] = None,
    approval_id: Optional[str] = None,
    retry_count: int = 0,
) -> Optional[TraceSpan]:
    """Complete a span with results."""
    span = await _load_span(span_id)
    if not span:
        logger.warning(f"[trace] Span {span_id} not found")
        return None

    span.status = status
    span.error = error
    span.completed_at = time.time()
    span.duration_ms = int((span.completed_at - span.started_at) * 1000)
    span.output_length = output_length
    span.prompt_tokens = prompt_tokens
    span.completion_tokens = completion_tokens
    span.total_tokens = prompt_tokens + completion_tokens
    span.cost_usd = cost_usd
    span.verify_status = verify_status
    span.verify_checks = verify_checks or []
    span.guardrail_level = guardrail_level
    span.approval_id = approval_id
    span.retry_count = retry_count

    await cache_set(f"span:{span_id}", span.model_dump(), ttl=SPAN_COMPLETED_TTL)
    await _persist_span_to_db(span)

    trace = await _load_trace(span.trace_id)
    if trace:
        _update_trace_aggregates(trace, span)
        await _save_trace(trace)

    return span


async def complete_trace(trace_id: str, status: str = "completed") -> Optional[PipelineTrace]:
    """Complete a pipeline trace."""
    trace = await _load_trace(trace_id)
    if not trace:
        return None

    trace.status = status
    trace.completed_at = time.time()
    trace.duration_ms = int((trace.completed_at - trace.started_at) * 1000)

    await _save_trace(trace)

    logger.info(
        f"[trace] Completed trace {trace_id}: "
        f"duration={trace.duration_ms}ms, "
        f"tokens={trace.total_tokens}, "
        f"cost=${trace.total_cost_usd:.4f}"
    )

    return trace


async def get_trace(trace_id: str) -> Optional[PipelineTrace]:
    return await _load_trace(trace_id)


async def get_task_traces(task_id: str) -> List[PipelineTrace]:
    """Get all traces for a task — Redis first, DB fallback."""
    r = get_redis()
    trace_ids = await r.smembers(f"traces:task:{task_id}")
    traces: List[PipelineTrace] = []

    if trace_ids:
        for tid in trace_ids:
            tid_str = tid.decode() if isinstance(tid, bytes) else tid
            trace = await _load_trace(tid_str)
            if trace:
                trace.spans = await _load_all_spans(tid_str)
                traces.append(trace)
        if traces:
            return traces

    try:
        async with async_session() as db:
            result = await db.execute(
                select(TraceRecord).where(TraceRecord.task_id == task_id)
                .order_by(TraceRecord.started_at.desc())
            )
            records = result.scalars().all()
            for rec in records:
                t = PipelineTrace(
                    trace_id=rec.trace_id, task_id=rec.task_id,
                    task_title=rec.task_title, status=rec.status,
                    started_at=rec.started_at, completed_at=rec.completed_at,
                    duration_ms=rec.duration_ms,
                    total_prompt_tokens=rec.total_prompt_tokens,
                    total_completion_tokens=rec.total_completion_tokens,
                    total_tokens=rec.total_tokens, total_cost_usd=rec.total_cost_usd,
                    total_llm_calls=rec.total_llm_calls, total_retries=rec.total_retries,
                    models_used=rec.models_used or {}, stage_durations=rec.stage_durations or {},
                )
                t.spans = await _load_spans_from_db(rec.trace_id)
                traces.append(t)
    except Exception as e:
        logger.warning(f"[trace] DB fallback for task traces failed: {e}")

    return traces


async def get_recent_traces(limit: int = 20) -> List[Dict[str, Any]]:
    """Get recent traces — Redis sorted set first, DB fallback."""
    r = get_redis()
    raw = await r.zrevrange("traces:recent", 0, limit - 1)
    trace_ids = [tid.decode() if isinstance(tid, bytes) else tid for tid in (raw or [])]

    results: List[Dict[str, Any]] = []

    if trace_ids:
        for tid in trace_ids:
            trace = await _load_trace(tid)
            if not trace:
                continue
            span_ids = await _get_trace_span_ids(tid)
            results.append({
                "trace_id": trace.trace_id,
                "task_id": trace.task_id,
                "task_title": trace.task_title,
                "status": trace.status,
                "duration_ms": trace.duration_ms,
                "total_tokens": trace.total_tokens,
                "total_cost_usd": trace.total_cost_usd,
                "total_llm_calls": trace.total_llm_calls,
                "models_used": trace.models_used,
                "stage_durations": trace.stage_durations,
                "span_count": len(span_ids),
                "started_at": trace.started_at,
                "completed_at": trace.completed_at,
            })
        if results:
            return results

    try:
        async with async_session() as db:
            result = await db.execute(
                select(TraceRecord).order_by(TraceRecord.started_at.desc()).limit(limit)
            )
            for rec in result.scalars().all():
                results.append({
                    "trace_id": rec.trace_id,
                    "task_id": rec.task_id,
                    "task_title": rec.task_title,
                    "status": rec.status,
                    "duration_ms": rec.duration_ms,
                    "total_tokens": rec.total_tokens,
                    "total_cost_usd": rec.total_cost_usd,
                    "total_llm_calls": rec.total_llm_calls,
                    "models_used": rec.models_used or {},
                    "stage_durations": rec.stage_durations or {},
                    "span_count": 0,
                    "started_at": rec.started_at,
                    "completed_at": rec.completed_at,
                })
    except Exception as e:
        logger.warning(f"[trace] DB fallback for recent traces failed: {e}")

    return results


async def get_trace_detail(trace_id: str) -> Optional[Dict[str, Any]]:
    """Get full trace detail including all spans."""
    trace = await _load_trace(trace_id)
    if not trace:
        return None

    spans = await _load_all_spans(trace_id)

    return {
        "trace_id": trace.trace_id,
        "task_id": trace.task_id,
        "task_title": trace.task_title,
        "status": trace.status,
        "duration_ms": trace.duration_ms,
        "total_tokens": trace.total_tokens,
        "total_cost_usd": trace.total_cost_usd,
        "total_llm_calls": trace.total_llm_calls,
        "total_retries": trace.total_retries,
        "models_used": trace.models_used,
        "stage_durations": trace.stage_durations,
        "started_at": trace.started_at,
        "completed_at": trace.completed_at,
        "spans": [
            {
                "span_id": s.span_id,
                "parent_span_id": s.parent_span_id,
                "stage_id": s.stage_id,
                "role": s.role,
                "model": s.model,
                "tier": s.tier,
                "status": s.status,
                "error": s.error,
                "duration_ms": s.duration_ms,
                "prompt_tokens": s.prompt_tokens,
                "completion_tokens": s.completion_tokens,
                "total_tokens": s.total_tokens,
                "cost_usd": s.cost_usd,
                "verify_status": s.verify_status,
                "verify_checks": s.verify_checks,
                "guardrail_level": s.guardrail_level,
                "approval_id": s.approval_id,
                "retry_count": s.retry_count,
                "input_length": s.input_length,
                "output_length": s.output_length,
                "started_at": s.started_at,
                "completed_at": s.completed_at,
            }
            for s in spans
        ],
    }


def _update_trace_aggregates(trace: PipelineTrace, span: TraceSpan) -> None:
    """Update trace aggregate metrics when a span completes."""
    trace.total_prompt_tokens += span.prompt_tokens
    trace.total_completion_tokens += span.completion_tokens
    trace.total_tokens += span.total_tokens
    trace.total_cost_usd += span.cost_usd
    trace.total_llm_calls += 1
    trace.total_retries += span.retry_count

    if span.model:
        trace.models_used[span.model] = trace.models_used.get(span.model, 0) + 1

    if span.stage_id:
        existing = trace.stage_durations.get(span.stage_id, 0)
        trace.stage_durations[span.stage_id] = existing + span.duration_ms
