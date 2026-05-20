"""
Trace middleware — injects distributed trace context into every request.

Extracts ``X-Agent-Trace-ID`` from inbound requests, creates a
TraceSpan, and propagates it across async boundaries via contextvars.
"""
from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from .context import start_trace, set_current_span

logger = structlog.get_logger("agent_hub.trace")


class TraceMiddleware(BaseHTTPMiddleware):
    """Ensure every request has a trace context with a ``trace_id``.

    Priority rules for ``X-Agent-Trace-ID``:
        1. Use caller-supplied value (gateway / upstream service).
        2. Otherwise generate a new UUID.

    The trace_id is bound to structlog context and attached to
    ``request.state.trace_span`` for downstream code.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint,
    ) -> Response:
        # ── Extract or generate trace_id ──────────────────────────
        trace_id = request.headers.get("X-Agent-Trace-ID") or str(uuid.uuid4())
        request_id = getattr(request.state, "request_id", None)

        # ── Create root span ──────────────────────────────────────
        root_span = start_trace(
            request_id=request_id,
            metadata={
                "method": request.method,
                "path": request.url.path,
                "trace_id_header_present": "X-Agent-Trace-ID" in request.headers,
            },
        )
        set_current_span(root_span)
        request.state.trace_span = root_span
        request.state.trace_id = trace_id

        # ── Bind trace_id to structlog context ────────────────────
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id,
            span_id=root_span.span_id,
        )

        # ── Execute ───────────────────────────────────────────────
        response = await call_next(request)

        # ── Echo trace_id in response header ──────────────────────
        response.headers["X-Agent-Trace-ID"] = trace_id

        # ── Cleanup ───────────────────────────────────────────────
        structlog.contextvars.unbind_contextvars("trace_id", "span_id")
        set_current_span(None)

        return response
