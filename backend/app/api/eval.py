"""Eval Suite API — datasets, cases, runs.

Endpoints:
  POST   /eval/datasets                — create dataset (admin)
  GET    /eval/datasets                — list datasets
  GET    /eval/datasets/{id}           — dataset + cases
  PATCH  /eval/datasets/{id}           — update (admin)
  DELETE /eval/datasets/{id}           — delete (admin)

  POST   /eval/datasets/{id}/cases     — add case (admin)
  PATCH  /eval/cases/{case_id}         — update case (admin)
  DELETE /eval/cases/{case_id}         — delete case (admin)

  POST   /eval/runs                    — schedule a run (admin); body: {dataset_id, label?, model_override?, role_override?}
  GET    /eval/runs                    — list runs
  GET    /eval/runs/{id}               — run summary + per-case results
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import async_session_factory, get_db
from ..models.eval import EvalCase, EvalDataset, EvalResult, EvalRun
from ..models.user import User
from ..security import get_current_user, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/eval", tags=["eval"])


# ───── Schemas ─────────────────────────────────────────────────────

class DatasetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    target_role: str = ""
    tags: List[str] = []


class DatasetUpdate(BaseModel):
    description: Optional[str] = None
    target_role: Optional[str] = None
    tags: Optional[List[str]] = None
    is_active: Optional[bool] = None


class CaseCreate(BaseModel):
    name: str = ""
    task: str = Field(..., min_length=1)
    role: str = ""
    scorer: str = "contains"
    expected: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)
    weight: float = 1.0
    timeout_seconds: int = 120


class CaseUpdate(BaseModel):
    name: Optional[str] = None
    task: Optional[str] = None
    role: Optional[str] = None
    scorer: Optional[str] = None
    expected: Optional[Dict[str, Any]] = None
    context: Optional[Dict[str, Any]] = None
    weight: Optional[float] = None
    timeout_seconds: Optional[int] = None
    enabled: Optional[bool] = None


class RunCreate(BaseModel):
    dataset_id: str
    label: str = ""
    agent_role_override: str = ""
    model_override: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ───── Datasets ────────────────────────────────────────────────────

def _dataset_dict(d: EvalDataset, with_case_count: int = 0) -> Dict[str, Any]:
    return {
        "id": str(d.id),
        "name": d.name,
        "description": d.description,
        "target_role": d.target_role,
        "tags": d.tags or [],
        "is_active": d.is_active,
        "case_count": with_case_count,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _case_dict(c: EvalCase) -> Dict[str, Any]:
    return {
        "id": str(c.id),
        "dataset_id": str(c.dataset_id),
        "name": c.name,
        "task": c.task,
        "role": c.role,
        "scorer": c.scorer,
        "expected": c.expected or {},
        "context": c.context or {},
        "weight": c.weight,
        "timeout_seconds": c.timeout_seconds,
        "enabled": c.enabled,
    }


@router.post("/datasets", status_code=201)
async def create_dataset(
    body: DatasetCreate,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    dup = (await db.execute(select(EvalDataset).where(EvalDataset.name == body.name))).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail="dataset name already exists")
    ds = EvalDataset(
        name=body.name, description=body.description, target_role=body.target_role,
        tags=body.tags, is_active=True,
    )
    db.add(ds)
    await db.flush()
    return _dataset_dict(ds, 0)


@router.get("/datasets")
async def list_datasets(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    active_only: bool = True,
):
    stmt = select(EvalDataset)
    if active_only:
        stmt = stmt.where(EvalDataset.is_active.is_(True))
    rows = (await db.execute(stmt.order_by(desc(EvalDataset.created_at)))).scalars().all()
    out = []
    for ds in rows:
        case_cnt = (await db.execute(
            select(EvalCase).where(EvalCase.dataset_id == ds.id)
        )).scalars().all()
        out.append(_dataset_dict(ds, with_case_count=len(case_cnt)))
    return out


@router.get("/datasets/{dataset_id}")
async def get_dataset(
    dataset_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ds = await db.get(EvalDataset, dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="dataset not found")
    cases = (await db.execute(
        select(EvalCase).where(EvalCase.dataset_id == dataset_id)
    )).scalars().all()
    out = _dataset_dict(ds, with_case_count=len(cases))
    out["cases"] = [_case_dict(c) for c in cases]
    return out


@router.patch("/datasets/{dataset_id}")
async def update_dataset(
    dataset_id: str,
    body: DatasetUpdate,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ds = await db.get(EvalDataset, dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="dataset not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(ds, field, value)
    await db.flush()
    return _dataset_dict(ds)


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(
    dataset_id: str,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ds = await db.get(EvalDataset, dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="dataset not found")
    await db.delete(ds)
    return {"ok": True}


# ───── Cases ────────────────────────────────────────────────────────

@router.post("/datasets/{dataset_id}/cases", status_code=201)
async def add_case(
    dataset_id: str,
    body: CaseCreate,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ds = await db.get(EvalDataset, dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="dataset not found")
    case = EvalCase(
        dataset_id=ds.id, name=body.name, task=body.task,
        role=body.role, scorer=body.scorer,
        expected=body.expected, context=body.context,
        weight=body.weight, timeout_seconds=body.timeout_seconds,
        enabled=True,
    )
    db.add(case)
    await db.flush()
    return _case_dict(case)


@router.patch("/cases/{case_id}")
async def update_case(
    case_id: str,
    body: CaseUpdate,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    case = await db.get(EvalCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="case not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(case, field, value)
    await db.flush()
    return _case_dict(case)


@router.delete("/cases/{case_id}")
async def delete_case(
    case_id: str,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    case = await db.get(EvalCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="case not found")
    await db.delete(case)
    return {"ok": True}


# ───── Runs ─────────────────────────────────────────────────────────

def _run_dict(r: EvalRun) -> Dict[str, Any]:
    return {
        "id": str(r.id),
        "dataset_id": str(r.dataset_id) if r.dataset_id else None,
        "label": r.label,
        "agent_role_override": r.agent_role_override,
        "model_override": r.model_override,
        "status": r.status,
        "total_cases": r.total_cases,
        "passed_cases": r.passed_cases,
        "failed_cases": r.failed_cases,
        "skipped_cases": r.skipped_cases,
        "avg_score": r.avg_score,
        "avg_latency_ms": r.avg_latency_ms,
        "total_tokens": r.total_tokens,
        "error": r.error,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "metadata": r.metadata_extra or {},
    }


def _result_dict(res: EvalResult) -> Dict[str, Any]:
    return {
        "id": str(res.id),
        "case_id": str(res.case_id) if res.case_id else None,
        "case_name": res.case_name,
        "role": res.role,
        "seed_id": res.seed_id,
        "score": res.score,
        "passed": res.passed,
        "scorer": res.scorer,
        "scorer_detail": res.scorer_detail or {},
        "output": res.output,
        "observations": res.observations or [],
        "error": res.error,
        "steps": res.steps,
        "latency_ms": res.latency_ms,
        "tokens": res.tokens,
        "created_at": res.created_at.isoformat() if res.created_at else None,
    }


async def _run_in_background(run_id: str) -> None:
    """Standalone DB session so we don't hold the request transaction."""
    from .eval_runner import run_dataset
    try:
        async with async_session_factory() as db:
            await run_dataset(db, run_id)
    except Exception as e:
        logger.exception(f"[eval] background run {run_id} crashed: {e}")
        try:
            async with async_session_factory() as db:
                run = await db.get(EvalRun, run_id)
                if run and run.status not in ("completed", "failed"):
                    run.status = "failed"
                    run.error = f"runner crashed: {e}"
                    await db.flush()
                    await db.commit()
        except Exception:
            pass


class CurateBody(BaseModel):
    source: str = Field("pipeline_tasks", description="pipeline_tasks | feedback")
    role: Optional[str] = None
    since_days: int = 14
    limit: int = 20
    min_quality_score: float = 0.7
    scorer: str = "llm_judge"


@router.post("/datasets/{dataset_id}/curate")
async def curate_dataset(
    dataset_id: str,
    body: CurateBody,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Auto-ingest cases from production traces / feedback into this dataset."""
    from .eval_curator import curate_from_feedback, curate_from_pipeline_tasks

    src = (body.source or "pipeline_tasks").lower()
    if src == "feedback":
        result = await curate_from_feedback(
            db, dataset_id=dataset_id, since_days=body.since_days, limit=body.limit,
        )
    else:
        result = await curate_from_pipeline_tasks(
            db,
            dataset_id=dataset_id,
            role=body.role,
            since_days=body.since_days,
            limit=body.limit,
            min_quality_score=body.min_quality_score,
            scorer=body.scorer,
        )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "curation failed")
    return result


@router.post("/runs", status_code=201)
async def create_run(
    body: RunCreate,
    background_tasks: BackgroundTasks,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from .eval_runner import schedule_run
    try:
        run_id = await schedule_run(
            db,
            dataset_id=body.dataset_id,
            label=body.label,
            agent_role_override=body.agent_role_override,
            model_override=body.model_override,
            metadata=body.metadata,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    background_tasks.add_task(_run_in_background, run_id)
    return {"ok": True, "run_id": run_id, "status": "scheduled"}


@router.get("/runs")
async def list_runs(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    dataset_id: Optional[str] = None,
    limit: int = 50,
):
    stmt = select(EvalRun)
    if dataset_id:
        stmt = stmt.where(EvalRun.dataset_id == dataset_id)
    rows = (await db.execute(
        stmt.order_by(desc(EvalRun.started_at)).limit(min(max(1, limit), 200))
    )).scalars().all()
    return [_run_dict(r) for r in rows]


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    run = await db.get(EvalRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    results = (await db.execute(
        select(EvalResult).where(EvalResult.run_id == run.id).order_by(EvalResult.created_at)
    )).scalars().all()
    out = _run_dict(run)
    out["results"] = [_result_dict(r) for r in results]
    return out
