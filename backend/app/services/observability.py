"""
Observability — Pipeline Trace + Token 用量 + 耗时可视化

每一步 pipeline 执行生成一条 Trace，包含:
- span_id: 唯一标识
- parent_span_id: 父级 (用于 subtask 树状展示)
- stage/role/model 信息
- token 用量 (prompt + completion)
- 耗时 (ms)
- 验证结果
- 错误信息

Trace 数据结构设计为可直接对接 OpenTelemetry 或自定义 Dashboard。
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List

from pydantic import BaseModel

from ..redis_client import cache_get, cache_set

logger = logging.getLogger(__name__)


class TraceSpan(BaseModel):
    span_id: str = ""
    parent_span_id: Optional[str] = None
    trace_id: str = ""

    task_id: str
    stage_id: str
    role: str
    model: str = ""
    tier: str = ""  # planning / execution / routine

    status: str = "running"  # running / completed / failed / blocked
    error: Optional[str] = None

    # Timing
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_ms: int = 0

    # Token usage
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0

    # Verification
    verify_status: Optional[str] = None  # pass / warn / fail
    verify_checks: List[Dict[str, Any]] = []

    # Guardrail
    guardrail_level: Optional[str] = None
    approval_id: Optional[str] = None

    # Metadata
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

    status: str = "running"  # running / completed / failed
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_ms: int = 0

    spans: List[TraceSpan] = []

    # Aggregated metrics
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_llm_calls: int = 0
    total_retries: int = 0

    models_used: Dict[str, int] = {}  # model_id -> count
    stage_durations: Dict[str, int] = {}  # stage_id -> duration_ms

    def __init__(self, **data):
        super().__init__(**data)
        if not self.trace_id:
            self.trace_id = str(uuid.uuid4())[:12]
        if not self.started_at:
            self.started_at = time.time()


# In-memory trace store (production: write to DB or OpenTelemetry)
_traces: Dict[str, PipelineTrace] = {}
_active_spans: Dict[str, TraceSpan] = {}


def start_trace(task_id: str, task_title: str = "") -> PipelineTrace:
    """Start a new pipeline trace."""
    trace = PipelineTrace(task_id=task_id, task_title=task_title)
    _traces[trace.trace_id] = trace
    logger.info(f"[trace] Started trace {trace.trace_id} for task {task_id}")
    return trace


def start_span(
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
    _active_spans[span.span_id] = span

    trace = _traces.get(trace_id)
    if trace:
        trace.spans.append(span)

    return span


def complete_span(
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
    span = _active_spans.pop(span_id, None)
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

    trace = _traces.get(span.trace_id)
    if trace:
        _update_trace_aggregates(trace, span)

    return span


def complete_trace(trace_id: str, status: str = "completed") -> Optional[PipelineTrace]:
    """Complete a pipeline trace."""
    trace = _traces.get(trace_id)
    if not trace:
        return None

    trace.status = status
    trace.completed_at = time.time()
    trace.duration_ms = int((trace.completed_at - trace.started_at) * 1000)

    logger.info(
        f"[trace] Completed trace {trace_id}: "
        f"duration={trace.duration_ms}ms, "
        f"tokens={trace.total_tokens}, "
        f"cost=${trace.total_cost_usd:.4f}, "
        f"spans={len(trace.spans)}"
    )

    return trace


def get_trace(trace_id: str) -> Optional[PipelineTrace]:
    return _traces.get(trace_id)


def get_task_traces(task_id: str) -> List[PipelineTrace]:
    return [t for t in _traces.values() if t.task_id == task_id]


def get_recent_traces(limit: int = 20) -> List[Dict[str, Any]]:
    """Get recent traces as summaries for the dashboard."""
    sorted_traces = sorted(_traces.values(), key=lambda t: t.started_at, reverse=True)[:limit]
    return [
        {
            "trace_id": t.trace_id,
            "task_id": t.task_id,
            "task_title": t.task_title,
            "status": t.status,
            "duration_ms": t.duration_ms,
            "total_tokens": t.total_tokens,
            "total_cost_usd": t.total_cost_usd,
            "total_llm_calls": t.total_llm_calls,
            "models_used": t.models_used,
            "stage_durations": t.stage_durations,
            "span_count": len(t.spans),
            "started_at": t.started_at,
            "completed_at": t.completed_at,
        }
        for t in sorted_traces
    ]


def get_trace_detail(trace_id: str) -> Optional[Dict[str, Any]]:
    """Get full trace detail including all spans."""
    trace = _traces.get(trace_id)
    if not trace:
        return None

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
            for s in trace.spans
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
