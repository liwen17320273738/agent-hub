"""
Observability API — Pipeline trace 查询 + 审批操作 + 内存查询

GET  /traces                    — 最近 trace 列表
GET  /traces/:id                — trace 详情（含所有 spans）
GET  /traces/task/:task_id      — 按任务查 traces
GET  /approvals                 — 待审批列表
POST /approvals/:id/resolve     — 审批/拒绝
GET  /audit-log                 — 审计日志
POST /pipeline/execute-stage    — 使用增强引擎执行单阶段
POST /pipeline/execute-full     — 使用增强引擎执行全流水线
GET  /memory/search             — 记忆检索
POST /planner/resolve-model     — 模型选择预览
POST /planner/estimate-cost     — 管线成本估算
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..security import get_current_user
from ..services.observability import (
    get_recent_traces,
    get_trace_detail,
    get_task_traces,
)
from ..services.guardrails import (
    get_pending_approvals,
    resolve_approval,
    get_audit_log,
)
from ..services.memory import search_similar_memories
from ..services.planner_worker import (
    resolve_model,
    estimate_pipeline_cost,
)

router = APIRouter(prefix="/observability", tags=["observability"])


# --- Traces ---

@router.get("/traces")
async def list_traces(
    limit: int = Query(20, ge=1, le=100),
    _user=Depends(get_current_user),
):
    return {"traces": await get_recent_traces(limit=limit)}


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str, _user=Depends(get_current_user)):
    detail = await get_trace_detail(trace_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Trace not found")
    return {"trace": detail}


@router.get("/traces/task/{task_id}")
async def get_traces_by_task(task_id: str, _user=Depends(get_current_user)):
    traces = await get_task_traces(task_id)
    return {"traces": [
        {
            "trace_id": t.trace_id,
            "status": t.status,
            "duration_ms": t.duration_ms,
            "total_tokens": t.total_tokens,
            "total_cost_usd": t.total_cost_usd,
            "span_count": len(t.spans),
            "started_at": t.started_at,
        }
        for t in traces
    ]}


# --- Approvals ---

@router.get("/approvals")
async def list_approvals(
    task_id: Optional[str] = Query(None),
    _user=Depends(get_current_user),
):
    approvals = await get_pending_approvals(task_id)
    return {"approvals": [a.model_dump() for a in approvals]}


class ResolveApprovalRequest(BaseModel):
    approved: bool
    comment: str = ""


@router.post("/approvals/{approval_id}/resolve")
async def resolve_approval_endpoint(
    approval_id: str,
    body: ResolveApprovalRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not hasattr(user, "role") or user.role != "admin":
        from ..models.pipeline import PipelineTask
        from sqlalchemy import select as sa_select
        pending = await get_pending_approvals(task_id=None)
        approval = next((a for a in pending if a.approval_id == approval_id), None)
        if not approval:
            raise HTTPException(status_code=404, detail="Approval request not found")
        task_result = await db.execute(
            sa_select(PipelineTask.org_id).where(
                PipelineTask.id == approval.task_id
            )
        )
        row = task_result.one_or_none()
        if row and row[0] and hasattr(user, "org_id") and row[0] != user.org_id:
            raise HTTPException(status_code=404, detail="Approval request not found")

    reviewer_id = str(user.id) if hasattr(user, "id") else "unknown"
    result = await resolve_approval(
        approval_id=approval_id,
        approved=body.approved,
        reviewer=reviewer_id,
        comment=body.comment,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return {"approval": result.model_dump()}


# --- Audit Log ---

@router.get("/audit-log")
async def get_audit_log_endpoint(
    task_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    _user=Depends(get_current_user),
):
    entries = await get_audit_log(task_id=task_id, limit=limit)
    return {"entries": [e.model_dump() for e in entries]}


# --- Dashboard Snapshot ---

@router.get("/dashboard")
async def get_dashboard(
    days: int = Query(14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """One-shot snapshot for the Pipeline Observability page.

    Returns: trend (daily cost / tokens / calls), per-stage heatmap, per-agent
    leaderboard, per-model leaderboard, recent failures, approval & budget-event
    summaries, task status counts.
    """
    from ..services.observability_dashboard import get_dashboard_snapshot
    return await get_dashboard_snapshot(db, days=days)


# --- Weekly Digest ---

@router.get("/digest")
async def get_weekly_digest(
    since_days: int = Query(7, ge=1, le=60),
    prev_days: Optional[int] = Query(None, ge=1, le=120),
    pass_rate_drop: float = Query(0.10, ge=0.0, le=1.0),
    score_drop: float = Query(0.10, ge=0.0, le=1.0),
    latency_increase: float = Query(0.50, ge=0.0, le=10.0),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Compare the most recent ``since_days`` window against the prior
    ``prev_days`` window for every agent role and surface regressions.

    Cheap to call (read-only DB scan); intended for a "weekly digest"
    UI panel and as a building block for future scheduled jobs.
    """
    from ..services.weekly_digest import compute_digest

    return await compute_digest(
        db,
        since_days=since_days,
        prev_days=prev_days,
        pass_rate_drop=pass_rate_drop,
        score_drop=score_drop,
        latency_increase=latency_increase,
    )


# --- Memory Search ---

@router.get("/memory/search")
async def search_memory(
    q: str = Query(..., min_length=2),
    role: Optional[str] = Query(None),
    stage_id: Optional[str] = Query(None),
    limit: int = Query(5, ge=1, le=20),
    min_quality: float = Query(0.0, ge=0, le=1),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    org_id = _user.org_id if hasattr(_user, "org_id") else None
    results = await search_similar_memories(
        db,
        query=q,
        role=role,
        stage_id=stage_id,
        limit=limit,
        min_quality=min_quality,
        org_id=org_id,
    )
    return {"results": results}


# --- Planner ---

class ResolveModelRequest(BaseModel):
    role: str
    stage_id: Optional[str] = None
    complexity: Optional[str] = None
    available_providers: Optional[List[str]] = None
    preferred_model: Optional[str] = None


@router.post("/planner/resolve-model")
async def resolve_model_endpoint(
    body: ResolveModelRequest,
    _user=Depends(get_current_user),
):
    resolution = resolve_model(
        role=body.role,
        stage_id=body.stage_id,
        complexity=body.complexity,
        available_providers=body.available_providers,
        preferred_model=body.preferred_model,
    )
    return {"resolution": resolution}


class EstimateCostRequest(BaseModel):
    stages: List[dict]
    available_providers: Optional[List[str]] = None


@router.post("/planner/estimate-cost")
async def estimate_cost_endpoint(
    body: EstimateCostRequest,
    _user=Depends(get_current_user),
):
    estimate = estimate_pipeline_cost(
        stages=body.stages,
        available_providers=body.available_providers,
    )
    return {"estimate": estimate}


# --- Enhanced Pipeline Execution ---

class ExecuteStageRequest(BaseModel):
    task_id: str
    task_title: str
    task_description: str = ""
    stage_id: str
    previous_outputs: Optional[dict] = None
    complexity: Optional[str] = None
    available_providers: Optional[List[str]] = None


@router.post("/pipeline/execute-stage")
async def execute_stage_endpoint(
    body: ExecuteStageRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    from ..services.pipeline_engine import execute_stage

    result = await execute_stage(
        db,
        task_id=body.task_id,
        task_title=body.task_title,
        task_description=body.task_description,
        stage_id=body.stage_id,
        previous_outputs=body.previous_outputs,
        available_providers=body.available_providers,
        complexity=body.complexity,
    )
    await db.commit()
    return result


class ExecuteFullPipelineRequest(BaseModel):
    task_id: str
    task_title: str
    task_description: str = ""
    stages: Optional[List[str]] = None
    complexity: Optional[str] = None
    available_providers: Optional[List[str]] = None


@router.post("/pipeline/execute-full")
async def execute_full_pipeline_endpoint(
    body: ExecuteFullPipelineRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    from ..services.pipeline_engine import execute_full_pipeline

    result = await execute_full_pipeline(
        db,
        task_id=body.task_id,
        task_title=body.task_title,
        task_description=body.task_description,
        stages=body.stages,
        available_providers=body.available_providers,
        complexity=body.complexity,
    )
    await db.commit()
    return result


@router.get("/agent-capabilities")
async def get_agent_capabilities(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Compute real agent capability metrics from learning signals and task history.

    Returns per-role stats:
    - taskCount: number of tasks involving this role
    - passRate: ratio of approved signal outcomes
    - rejectRate: ratio of rejected outcomes
    - avgRetries: average retry count per signal
    - qualityScore: average quality score (0-1)
    """
    from sqlalchemy import select
    from ..models.learning import LearningSignal
    from ..models.pipeline import PipelineStage

    # Fetch all learning signals with non-empty role
    sig_result = await db.execute(
        select(LearningSignal).where(LearningSignal.role != "")
    )
    signals = sig_result.scalars().all()

    # Aggregate per-role in Python (simpler than complex SQL expressions)
    role_data: Dict[str, Dict[str, Any]] = {}
    for s in signals:
        role = s.role or ""
        if not role:
            continue
        entry = role_data.setdefault(role, {
            "signal_count": 0, "reject_count": 0,
            "decision_count": 0, "retry_sum": 0,
            "quality_sum": 0, "quality_count": 0,
        })
        entry["signal_count"] += 1
        entry["retry_sum"] += (s.retry_count or 0)
        if s.quality_score is not None:
            entry["quality_sum"] += s.quality_score
            entry["quality_count"] += 1
        if s.signal_type == "REJECT":
            entry["reject_count"] += 1
            entry["decision_count"] += 1
        elif s.signal_type == "APPROVE_AFTER_RETRY":
            entry["decision_count"] += 1

    # Per-role task counts from pipeline_stages table
    stage_result = await db.execute(
        select(PipelineStage.task_id, PipelineStage.owner_role, PipelineStage.stage_id)
    )
    role_task_counts: Dict[str, set] = {}
    for row in stage_result.all():
        role = row.owner_role or row.stage_id or ""
        if role:
            role_task_counts.setdefault(role, set()).add(str(row.task_id))

    capabilities = {}
    for role, d in role_data.items():
        decision_count = d["decision_count"]
        reject_count = d["reject_count"]
        pass_count = decision_count - reject_count
        pass_rate = pass_count / decision_count if decision_count > 0 else None
        reject_rate = reject_count / decision_count if decision_count > 0 else None
        avg_retries = d["retry_sum"] / d["signal_count"] if d["signal_count"] > 0 else 0.0
        quality = d["quality_sum"] / d["quality_count"] if d["quality_count"] > 0 else None
        task_count = len(role_task_counts.get(role, set())) if role in role_task_counts else 0

        capabilities[role] = {
            "role": role,
            "taskCount": task_count,
            "signalCount": d["signal_count"],
            "passRate": round(pass_rate, 3) if pass_rate is not None else None,
            "rejectRate": round(reject_rate, 3) if reject_rate is not None else None,
            "avgRetries": round(avg_retries, 2),
            "qualityScore": round(quality, 3) if quality is not None else None,
        }

    return {"capabilities": capabilities}
