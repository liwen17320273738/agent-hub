## Agent Hub — Stability & Observability Architecture (2026-05-11)

### Distributed Tracing
- **Entry**: `app/core/context.py` — `TraceSpan` dataclass with `contextvars.ContextVar`
- **Middleware**: `app/core/trace_middleware.py` — `TraceMiddleware` extracts/propagates `X-Agent-Trace-ID`
- **Pipeline**: `execute_stage()` creates child spans with `{task_id, stage_id}` metadata
- **LLM Router**: `_inject_trace_metadata()` injects trace_id/span_id into every `chat_completion` response
- **Logs**: `logging_config.py` auto-injects `trace_id` + `span_id`

### Circuit Breaker
- **Storage**: Redis keys `agenthub:llm:cb:open:{fingerprint}` with TTL
- **Threshold**: 3 consecutive failures, 120s open, configurable via `config.py`

### Resource Lifecycle
- `cleanup_cancelled_task()` — kill subprocesses + optional worktree removal
- `cleanup_stale_tasks()` — auto-detect >72h stuck tasks
- `cleanup_orphan_worktrees()` — remove leaked directories >48h
- `schedule_periodic_cleanup(60min)` — background sweep
- `kill_job_by_task_id()` — batch terminate executor jobs

### Tests: 364 passed
