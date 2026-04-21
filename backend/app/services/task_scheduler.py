"""Global task scheduler — process-level fairness for pipeline runs.

Background
==========
Before this module, every ``/auto-run``, ``/smart-run``, ``/run-stage`` and
similar endpoint did:

    asyncio.create_task(_run_in_background(...))

That fires N pipelines in parallel for N concurrent users — happily blowing
LLM provider rate limits, exhausting Postgres connections, and starving
later submissions. There is *no* fairness, no cap, no visibility.

This module replaces that pattern with a ``TaskScheduler`` singleton that:

* Holds an ``asyncio.Semaphore`` with capacity ``MAX_CONCURRENT_TASKS``
  (env: ``SCHED_MAX_CONCURRENT``, default 4).
* Records every submission as either ``running`` or ``queued`` and emits
  ``scheduler:queued`` / ``scheduler:started`` / ``scheduler:finished``
  SSE events so the UI can render queue depth in real time.
* Provides ``status()`` for the ``/api/scheduler/status`` REST.
* Persists the *queue* (not running) to Redis so a process restart can
  resume waiting submissions instead of dropping them on the floor.

Persistence model
=================
Coroutines aren't serialisable, so we can't pickle ``coro_factory``. Instead
each persisted submission records ``(kind, params)``, and a kind→builder
registry rebuilds the factory on resume. Callers register their kinds at
import time::

    from .task_scheduler import register_kind, get_scheduler

    def _build_dag_run(params):
        async def _run(db):
            await execute_dag_pipeline(db, **params)
        return _run

    register_kind("dag-run", _build_dag_run)

    submission_id = await get_scheduler().submit(
        task_id=tid, label=f"dag-run:{tid[:8]}", kind="dag-run",
        params={"task_id": tid, "task_title": title, ...},
    )

Submissions whose ``kind`` is registered + ``params`` is provided are
automatically persisted; everything else falls back to the legacy
``coro_factory=`` path (in-memory only, lost on restart).

Running tasks are NOT persisted — if a worker dies mid-execution, the
in-flight pipeline is gone and operators must re-trigger it. We surface
the orphan count at startup via SSE so it's at least visible.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


DEFAULT_MAX_CONCURRENT = max(1, int(os.getenv("SCHED_MAX_CONCURRENT", "4")))


CoroFactory = Callable[[AsyncSession], Awaitable[None]]
KindBuilder = Callable[[Dict[str, Any]], CoroFactory]


# ─────────────────────────────────────────────────────────────────────────────
# Kind registry — module-level so call sites can register at import time.
# ─────────────────────────────────────────────────────────────────────────────

_KIND_BUILDERS: Dict[str, KindBuilder] = {}


def register_kind(kind: str, builder: KindBuilder) -> None:
    """Register a (kind → factory builder) so that persisted queue items
    of this kind can be rebuilt on process restart.

    Idempotent: re-registering the same kind overwrites silently (useful
    for hot reload). Builders MUST be pure functions of ``params`` —
    they may close over module-level imports but not over per-request
    state, since they'll be invoked from the resumer at startup.
    """
    _KIND_BUILDERS[kind] = builder


def list_kinds() -> List[str]:
    return sorted(_KIND_BUILDERS.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Redis-backed queue store
# ─────────────────────────────────────────────────────────────────────────────

_QUEUE_ZSET = "scheduler:queue"      # score=enqueued_at_ms, member=submission_id
_META_KEY_FMT = "scheduler:meta:{}"   # JSON blob with {kind, params, label, task_id, queued_at}


async def _persist_enqueue(meta: Dict[str, Any]) -> None:
    from ..redis_client import get_redis
    r = get_redis()
    payload = json.dumps({
        "submission_id": meta["submission_id"],
        "task_id": meta["task_id"],
        "label": meta["label"],
        "kind": meta["kind"],
        "params": meta.get("params") or {},
        "queued_at": meta["queued_at"],
    }, ensure_ascii=False)
    score = _ts_ms_from_iso(meta["queued_at"])
    try:
        await r.set(_META_KEY_FMT.format(meta["submission_id"]), payload)
        await r.zadd(_QUEUE_ZSET, {meta["submission_id"]: score})
    except Exception as exc:
        logger.warning("[scheduler] persist enqueue failed: %s", exc)


async def _persist_dequeue(submission_id: str) -> None:
    """Called when a queued submission starts running OR finishes failing
    before start. Either way it shouldn't be replayed on restart."""
    from ..redis_client import get_redis
    r = get_redis()
    try:
        await r.zrem(_QUEUE_ZSET, submission_id)
        await r.delete(_META_KEY_FMT.format(submission_id))
    except Exception as exc:
        logger.warning("[scheduler] persist dequeue failed: %s", exc)


async def _persist_load_all() -> List[Dict[str, Any]]:
    """Read every persisted queue item, oldest first. Best-effort."""
    from ..redis_client import get_redis
    r = get_redis()
    try:
        ids = await r.zrange(_QUEUE_ZSET, 0, -1)
    except Exception as exc:
        logger.warning("[scheduler] persist load failed: %s", exc)
        return []

    out: List[Dict[str, Any]] = []
    for sid in ids:
        try:
            raw = await r.get(_META_KEY_FMT.format(sid))
            if not raw:
                # tombstone: dangling ZSET entry, clean it up
                await r.zrem(_QUEUE_ZSET, sid)
                continue
            out.append(json.loads(raw))
        except Exception as exc:
            logger.warning("[scheduler] persist load item %s failed: %s", sid, exc)
    return out


def _ts_ms_from_iso(iso: str) -> float:
    try:
        return datetime.fromisoformat(iso).timestamp() * 1000.0
    except Exception:
        return datetime.utcnow().timestamp() * 1000.0


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler
# ─────────────────────────────────────────────────────────────────────────────

class TaskScheduler:
    """In-process bounded scheduler with optional Redis-persisted queue.

    Submissions are FIFO. Persistence kicks in automatically when caller
    provides ``kind`` + ``params`` AND the kind is registered.
    """

    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT):
        self._max_concurrent = max_concurrent
        self._sem = asyncio.Semaphore(max_concurrent)
        self._running: Dict[str, Dict[str, Any]] = {}
        self._queue: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._lifetime_submitted = 0
        self._lifetime_finished = 0
        self._lifetime_failed = 0
        self._lifetime_resumed = 0
        self._resume_started = False

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    async def submit(
        self,
        *,
        task_id: str,
        label: str,
        coro_factory: Optional[CoroFactory] = None,
        kind: str = "pipeline",
        params: Optional[Dict[str, Any]] = None,
        _from_resume: bool = False,
    ) -> str:
        """Enqueue a task and return its submission id immediately.

        Persistence
        -----------
        If ``kind`` is registered AND ``params`` is provided, the
        submission is also written to Redis so a restart can resume it.
        Otherwise it lives only in memory.

        ``coro_factory`` is the legacy escape hatch for callers that
        can't (or won't) be made resumable. New code should pass
        ``kind+params`` instead.
        """
        # Lazy first-call resume — happens once per process. We can't run
        # this in __init__ because there's no event loop yet.
        if not self._resume_started:
            self._resume_started = True
            asyncio.create_task(self._resume_pending())

        submission_id = str(uuid.uuid4())
        persistable = bool(params) and kind in _KIND_BUILDERS

        if coro_factory is None:
            if not persistable:
                raise ValueError(
                    f"submit needs either coro_factory= or a registered kind+params; "
                    f"kind={kind!r} registered={kind in _KIND_BUILDERS} "
                    f"params_present={bool(params)}"
                )
            coro_factory = _KIND_BUILDERS[kind](params or {})

        meta: Dict[str, Any] = {
            "submission_id": submission_id,
            "task_id": task_id,
            "label": label,
            "kind": kind,
            "params": params or {},
            "queued_at": datetime.utcnow().isoformat(),
            "started_at": None,
            "finished_at": None,
            "persistent": persistable,
        }

        async with self._lock:
            self._queue.append(meta)
            if not _from_resume:
                self._lifetime_submitted += 1
            queue_position = len(self._queue)

        if persistable and not _from_resume:
            await _persist_enqueue(meta)

        await self._emit("scheduler:queued", self._public_meta(meta, extra={
            "queueDepth": queue_position,
            "running": len(self._running),
            "maxConcurrent": self._max_concurrent,
        }))

        asyncio.create_task(self._run(meta, coro_factory))
        return submission_id

    async def _resume_pending(self) -> None:
        """Read persisted queue from Redis and re-submit each item.

        Items whose kind isn't registered (e.g. removed code) are dropped
        with a warning. We do NOT try to recover running tasks — those
        coroutines died with the previous process and re-running them
        could double-spend LLM budget or produce duplicate side effects.
        """
        try:
            persisted = await _persist_load_all()
        except Exception as exc:
            logger.warning("[scheduler] resume scan failed: %s", exc)
            return

        if not persisted:
            return

        recoverable = [p for p in persisted if p.get("kind") in _KIND_BUILDERS]
        dropped = [p for p in persisted if p.get("kind") not in _KIND_BUILDERS]

        for p in dropped:
            logger.warning(
                "[scheduler] dropping persisted submission %s — kind %r unknown",
                p.get("submission_id"), p.get("kind"),
            )
            await _persist_dequeue(p["submission_id"])

        if not recoverable:
            return

        logger.info(
            "[scheduler] resuming %d persisted submissions from previous process",
            len(recoverable),
        )
        await self._emit("scheduler:resumed", {
            "count": len(recoverable),
            "dropped": len(dropped),
            "kinds": sorted({p["kind"] for p in recoverable}),
        })

        for p in recoverable:
            try:
                # Drop the old persisted record; submit() will write a new
                # one with a fresh submission_id (we don't want to keep the
                # old id lest two processes race).
                await _persist_dequeue(p["submission_id"])
                await self.submit(
                    task_id=p.get("task_id", ""),
                    label=f"[resumed] {p.get('label', '?')}",
                    kind=p["kind"],
                    params=p.get("params") or {},
                    _from_resume=True,
                )
                self._lifetime_resumed += 1
            except Exception as exc:
                logger.exception(
                    "[scheduler] failed to resume submission %s: %s",
                    p.get("submission_id"), exc,
                )

    async def _run(self, meta: Dict[str, Any], coro_factory: CoroFactory) -> None:
        try:
            await self._sem.acquire()
        except asyncio.CancelledError:
            async with self._lock:
                self._queue = [q for q in self._queue if q["submission_id"] != meta["submission_id"]]
            return

        async with self._lock:
            self._queue = [q for q in self._queue if q["submission_id"] != meta["submission_id"]]
            meta["started_at"] = datetime.utcnow().isoformat()
            self._running[meta["submission_id"]] = meta

        # Once it leaves the queue, take it out of persistence too.
        # Restart between this point and finish DOES drop the running task
        # (documented in module docstring — re-running could double-spend).
        if meta.get("persistent"):
            await _persist_dequeue(meta["submission_id"])

        await self._emit("scheduler:started", self._public_meta(meta, extra={
            "queueDepth": len(self._queue),
            "running": len(self._running),
        }))

        ok = True
        try:
            await self._with_session(coro_factory, meta["label"])
        except Exception as exc:
            ok = False
            logger.exception("[scheduler] task %s crashed: %s", meta["label"], exc)
        finally:
            async with self._lock:
                self._running.pop(meta["submission_id"], None)
                meta["finished_at"] = datetime.utcnow().isoformat()
                if ok:
                    self._lifetime_finished += 1
                else:
                    self._lifetime_failed += 1
            self._sem.release()
            await self._emit("scheduler:finished", self._public_meta(meta, extra={
                "ok": ok,
                "queueDepth": len(self._queue),
                "running": len(self._running),
            }))

    async def _with_session(self, coro_factory: CoroFactory, label: str) -> None:
        from ..database import async_session as session_factory
        from .sse import emit_event

        try:
            async with session_factory() as db:
                try:
                    await coro_factory(db)
                    await db.commit()
                except Exception as exc:
                    await db.rollback()
                    logger.exception("[scheduler] task %s failed: %s", label, exc)
                    await emit_event("pipeline:auto-error", {
                        "error": str(exc),
                        "label": label,
                    })
                    raise
        except Exception:
            raise

    @staticmethod
    def _public_meta(meta: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Strip params from outbound payloads — they may contain large
        prior_outputs blobs. Status/audit consumers only need labels."""
        payload = {
            "submission_id": meta["submission_id"],
            "task_id": meta["task_id"],
            "label": meta["label"],
            "kind": meta["kind"],
            "queued_at": meta.get("queued_at"),
            "started_at": meta.get("started_at"),
            "finished_at": meta.get("finished_at"),
            "persistent": meta.get("persistent", False),
        }
        if extra:
            payload.update(extra)
        return payload

    @staticmethod
    async def _emit(event: str, payload: Dict[str, Any]) -> None:
        try:
            from .sse import emit_event
            await emit_event(event, payload)
        except Exception:
            pass

    def status(self) -> Dict[str, Any]:
        return {
            "maxConcurrent": self._max_concurrent,
            "running": [self._public_meta(m) for m in self._running.values()],
            "queued": [self._public_meta(m) for m in self._queue],
            "runningCount": len(self._running),
            "queueDepth": len(self._queue),
            "registeredKinds": list_kinds(),
            "lifetime": {
                "submitted": self._lifetime_submitted,
                "finished": self._lifetime_finished,
                "failed": self._lifetime_failed,
                "resumed_from_restart": self._lifetime_resumed,
            },
        }


_scheduler: Optional[TaskScheduler] = None


def get_scheduler() -> TaskScheduler:
    """Process-wide singleton. Lazy so tests can monkey-patch the env."""
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
    return _scheduler
