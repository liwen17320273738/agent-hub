"""
Request logging & correlation middleware.

Adds a ``X-Request-ID`` header to every response and logs
method / path / status / duration for each request using structlog.
"""
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger("agent_hub.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Attach a request-id, log every inbound request with duration."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # ── Request ID ────────────────────────────────────────────
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Bind to structlog context so all downstream logs include it
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        # Attach to request state so downstream code can use it
        request.state.request_id = request_id

        # ── Timing ────────────────────────────────────────────────
        start = time.perf_counter()

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        # ── Headers ───────────────────────────────────────────────
        response.headers["X-Request-ID"] = request_id

        # ── Logging ───────────────────────────────────────────────
        path = request.url.path
        if path == "/health":
            logger.debug(
                "request",
                method=request.method,
                path=path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
        else:
            logger.info(
                "request",
                method=request.method,
                path=path,
                status=response.status_code,
                duration_ms=duration_ms,
            )

        return response
