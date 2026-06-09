"""
Distributed Trace Context — contextvars-based trace propagation.

Provides thread-safe, async-safe trace context propagation across
all layers: Gateway → Orchestrator → Agent → Tool → LLM.
"""
from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TraceSpan:
    """A single span within a distributed trace."""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    request_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def set_metadata(self, key: str, value: object) -> None:
        """Attach a metadata key/value to this span (in place)."""
        self.metadata[key] = value

    def new_child(self, metadata: Optional[dict] = None) -> "TraceSpan":
        """Create a child span, preserving trace_id and request_id."""
        child_meta = dict(self.metadata)
        if metadata:
            child_meta.update(metadata)
        return TraceSpan(
            trace_id=self.trace_id,
            span_id=str(uuid.uuid4()),
            parent_span_id=self.span_id,
            request_id=self.request_id,
            metadata=child_meta,
        )


# Context variables (async-safe by design via contextvars)
_trace_context: contextvars.ContextVar[Optional[TraceSpan]] = contextvars.ContextVar(
    "trace_context", default=None,
)


def get_current_span() -> Optional[TraceSpan]:
    """Return the current trace span, or None if not in a traced context."""
    return _trace_context.get(None)


def set_current_span(span: Optional[TraceSpan]) -> None:
    """Set the current trace span. Pass None to clear."""
    _trace_context.set(span)


def start_trace(
    request_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> TraceSpan:
    """Start a new root trace span. Called at entry points (Gateway, API handler).

    Returns:
        A new TraceSpan that MUST be passed to :func:`set_current_span`.

    Example:
        >>> span = start_trace(request_id=req_id)
        >>> set_current_span(span)
        >>> logger.info("task started")
        >>> child = span.new_child({"stage": "planning"})
        >>> set_current_span(child)
        >>> ...  # stage execution
        >>> set_current_span(span)  # restore parent when done
    """
    return TraceSpan(
        trace_id=str(uuid.uuid4()),
        span_id=str(uuid.uuid4()),
        parent_span_id=None,
        request_id=request_id,
        metadata=metadata or {},
    )


def ensure_trace() -> TraceSpan:
    """Get current span or create a new root one. Never returns None."""
    span = get_current_span()
    if span is None:
        span = start_trace()
        set_current_span(span)
    return span
