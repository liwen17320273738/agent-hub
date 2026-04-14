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

from typing import Optional, List
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
    estimate_stage_cost,
    estimate_pipeline_cost,
)

router = APIRouter(prefix="/api/observability", tags=["observability"])


# --- Traces ---

@router.get("/traces")
async def list_traces(
    limit: int = Query(20, ge=1, le=100),
    _user=Depends(get_current_user),
):
    return {"traces": get_recent_traces(limit=limit)}


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str, _user=Depends(get_current_user)):
    detail = get_trace_detail(trace_id)
    if not detail:
        raise HTTPException(404, "Trace not found")
    return {"trace": detail}


@router.get("/traces/task/{task_id}")
async def get_traces_by_task(task_id: str, _user=Depends(get_current_user)):
    traces = get_task_traces(task_id)
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
    approvals = get_pending_approvals(task_id)
    return {"approvals": [a.dict() for a in approvals]}


class ResolveApprovalRequest(BaseModel):
    approved: bool
    comment: str = ""


@router.post("/approvals/{approval_id}/resolve")
async def resolve_approval_endpoint(
    approval_id: str,
    body: ResolveApprovalRequest,
    user=Depends(get_current_user),
):
    reviewer_id = str(user.id) if hasattr(user, "id") else "unknown"
    result = resolve_approval(
        approval_id=approval_id,
        approved=body.approved,
        reviewer=reviewer_id,
        comment=body.comment,
    )
    if not result:
        raise HTTPException(404, "Approval request not found")
    return {"approval": result.dict()}


# --- Audit Log ---

@router.get("/audit-log")
async def get_audit_log_endpoint(
    task_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    _user=Depends(get_current_user),
):
    entries = get_audit_log(task_id=task_id, limit=limit)
    return {"entries": [e.dict() for e in entries]}


# --- Memory Search ---

@router.get("/memory/search")
async def search_memory(
    q: str = Query(..., min_length=2),
    role: Optional[str] = Query(None),
    stage_id: Optional[str] = Query(None),
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    results = await search_similar_memories(
        db,
        query=q,
        role=role,
        stage_id=stage_id,
        limit=limit,
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
