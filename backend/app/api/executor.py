"""
Executor API — run Claude Code tasks, manage jobs, stream logs.

Replaces Node.js server/executor/executorRouter.mjs with DB-backed jobs
and sandboxed execution.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..security import get_current_user
from ..services.executor_bridge import (
    execute_claude_code,
    get_job,
    get_jobs_by_task,
    kill_job,
    build_execution_prompt,
)

router = APIRouter(prefix="/executor", tags=["executor"])


class RunRequest(BaseModel):
    taskId: str = ""
    prompt: str = ""
    workDir: str = ""
    allowedTools: list[str] = []
    timeoutSeconds: int = 900


@router.post("/run")
async def run_executor(
    body: RunRequest,
    user: Annotated[User, Depends(get_current_user)],
):
    prompt = body.prompt
    if not prompt and body.taskId:
        prompt = f"Execute task: {body.taskId}"

    if not prompt:
        raise HTTPException(status_code=400, detail="prompt or taskId required")

    job = await execute_claude_code(
        task_id=body.taskId or "manual",
        prompt=prompt,
        work_dir=body.workDir,
        allowed_tools=body.allowedTools or None,
        timeout_seconds=body.timeoutSeconds,
    )

    return {"ok": True, "job": _safe_job(job)}


@router.get("/jobs/{job_id}")
async def get_job_endpoint(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": _safe_job(job)}


@router.get("/jobs/task/{task_id}")
async def get_jobs_by_task_endpoint(
    task_id: str,
    user: Annotated[User, Depends(get_current_user)],
):
    jobs = get_jobs_by_task(task_id)
    return {"jobs": [_safe_job(j) for j in jobs]}


@router.post("/jobs/{job_id}/kill")
async def kill_job_endpoint(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
):
    success = kill_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found or already completed")
    return {"ok": True}


def _safe_job(job: dict) -> dict:
    """Strip large log content for API responses."""
    return {
        "id": job.get("id"),
        "taskId": job.get("taskId"),
        "status": job.get("status"),
        "pid": job.get("pid"),
        "startedAt": job.get("startedAt"),
        "completedAt": job.get("completedAt"),
        "exitCode": job.get("exitCode"),
        "outputLength": len(job.get("output", "")),
        "logCount": len(job.get("logs", [])),
    }
