"""Scheduler observability — read-only view of the global TaskScheduler.

GET /api/scheduler/status — running + queued tasks + lifetime counters
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..security import get_current_user
from ..services.task_scheduler import get_scheduler

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/status")
async def scheduler_status(_user=Depends(get_current_user)):
    """Snapshot of the in-process pipeline scheduler.

    Used by the UI to render queue depth, throughput, and the list of
    currently-running pipelines. Cheap — pure in-memory, no DB hit.
    """
    return get_scheduler().status()
