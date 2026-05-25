"""
Outcome Contract API — route B Wave 1.

Endpoints:

* ``POST /api/outcome-contracts/draft`` — agent (or human PM) drafts a
  contract from a task. Creates the row in ``status=draft``.
* ``POST /api/outcome-contracts/{id}/propose`` — flip ``draft`` →
  ``proposed`` (ready to send to customer).
* ``POST /api/outcome-contracts/{id}/sign`` — customer signs.
  Generates the ``outcome_checkpoints`` rows from ``verification_plan``.
* ``POST /api/outcome-contracts/{id}/record-metric`` — record a metric
  reading (manual or system-pushed).
* ``POST /api/outcome-contracts/{id}/checkpoints/{day}/run`` — execute
  a checkpoint verdict now (idempotent; safe to call before scheduled date).
* ``GET /api/outcome-contracts/{id}`` — fetch with checkpoints + readings
  summary.
* ``GET /api/outcome-contracts/by-task/{task_id}`` — fetch by task FK.

This API stays thin — verdict logic lives in
``services.outcome_contract_service``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models.outcome_contract import (
    CHECKPOINT_VERDICT_VALUES,
    CONTRACT_STATUS_VALUES,
    METRIC_DIRECTION_VALUES,
    METRIC_SOURCE_VALUES,
    REFUND_POLICY_VALUES,
    OutcomeCheckpoint,
    OutcomeContract,
    OutcomeMetricReading,
)
from ..models.pipeline import PipelineTask
from ..models.user import User
from ..security import get_current_user_optional
from ..services.outcome_contract_service import (
    ReadingPoint,
    compute_checkpoint_verdict,
    validate_metrics_list,
    validate_verification_plan,
)

router = APIRouter(prefix="/outcome-contracts", tags=["outcome-contracts"])


# ---------------------------------------------------------------------------
# Pydantic request/response shapes (kept inline per project convention)
# ---------------------------------------------------------------------------


class MetricDefIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    source: str = Field(default="manual")
    target_value: float
    direction: str = Field(default="increase")
    measurement_window_days: int = Field(default=30, ge=1, le=365)
    baseline_value: Optional[float] = None
    description: Optional[str] = None


class CheckpointPlanIn(BaseModel):
    day: int = Field(..., ge=1, le=365)
    method: str = Field(default="auto_metric_check")


class RefundTriggerIn(BaseModel):
    trigger: str = Field(default="all_metrics_failed")
    ratio: Optional[float] = Field(default=None, ge=0, le=1)


class DraftContractRequest(BaseModel):
    task_id: str
    business_goal: str = Field(..., min_length=10, max_length=4000)
    success_metrics: List[MetricDefIn]
    verification_plan: List[CheckpointPlanIn]
    refund_policy: str = Field(default="full")
    refund_trigger: Optional[RefundTriggerIn] = None
    price_usd: Optional[float] = None
    deposit_pct: Optional[float] = Field(default=None, ge=0, le=1)
    delivery_deadline: Optional[datetime] = None
    drafted_by_agent: Optional[str] = "ceo-agent"


class SignContractRequest(BaseModel):
    signed_by_customer: str = Field(..., min_length=1, max_length=200)
    signature_meta: Dict[str, Any] = Field(default_factory=dict)


class RecordMetricRequest(BaseModel):
    metric_name: str = Field(..., min_length=1, max_length=100)
    value: float
    source: str = Field(default="manual")
    evidence_url: Optional[str] = None
    evidence_meta: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _contract_dict(
    c: OutcomeContract,
    *,
    include_checkpoints: bool = False,
    include_readings_summary: bool = False,
) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "id": str(c.id),
        "task_id": str(c.task_id),
        "workspace_id": str(c.workspace_id) if c.workspace_id else None,
        "business_goal": c.business_goal,
        "success_metrics": c.success_metrics or [],
        "verification_plan": c.verification_plan or [],
        "refund_policy": c.refund_policy,
        "refund_trigger": c.refund_trigger or {},
        "price_usd": c.price_usd,
        "deposit_pct": c.deposit_pct,
        "delivery_deadline": c.delivery_deadline.isoformat() if c.delivery_deadline else None,
        "status": c.status,
        "drafted_by_agent": c.drafted_by_agent,
        "drafted_at": c.drafted_at.isoformat() if c.drafted_at else None,
        "signed_by_customer": c.signed_by_customer,
        "signed_at": c.signed_at.isoformat() if c.signed_at else None,
        "fulfilled_at": c.fulfilled_at.isoformat() if c.fulfilled_at else None,
        "breached_at": c.breached_at.isoformat() if c.breached_at else None,
        "refunded_at": c.refunded_at.isoformat() if c.refunded_at else None,
        "refund_amount_usd": c.refund_amount_usd,
        "notes": c.notes,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }
    if include_checkpoints:
        d["checkpoints"] = [
            _checkpoint_dict(cp) for cp in (c.checkpoints or [])
        ]
    if include_readings_summary:
        readings_by_metric: Dict[str, int] = {}
        for r in c.readings or []:
            readings_by_metric[r.metric_name] = readings_by_metric.get(r.metric_name, 0) + 1
        d["readings_count_by_metric"] = readings_by_metric
    return d


def _checkpoint_dict(cp: OutcomeCheckpoint) -> Dict[str, Any]:
    return {
        "id": str(cp.id),
        "contract_id": str(cp.contract_id),
        "day_offset": cp.day_offset,
        "method": cp.method,
        "scheduled_for": cp.scheduled_for.isoformat() if cp.scheduled_for else None,
        "executed_at": cp.executed_at.isoformat() if cp.executed_at else None,
        "verdict": cp.verdict,
        "metric_results": cp.metric_results or [],
        "summary": cp.summary,
        "refund_decision": cp.refund_decision,
        "notes": cp.notes,
    }


def _reading_dict(r: OutcomeMetricReading) -> Dict[str, Any]:
    return {
        "id": str(r.id),
        "metric_name": r.metric_name,
        "value": r.value,
        "source": r.source,
        "evidence_url": r.evidence_url,
        "recorded_by": r.recorded_by,
        "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
    }


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _to_uuid(s: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(s))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid_uuid")


async def _load_contract(
    db: AsyncSession, contract_id: str, *, with_relations: bool = False
) -> OutcomeContract:
    cid = _to_uuid(contract_id)
    stmt = select(OutcomeContract).where(OutcomeContract.id == cid)
    if with_relations:
        stmt = stmt.options(
            selectinload(OutcomeContract.checkpoints),
            selectinload(OutcomeContract.readings),
        )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="contract_not_found")
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/draft", status_code=201)
async def draft_contract(
    body: DraftContractRequest,
    user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Agent (or PM) drafts a contract for a task.

    Validates metrics + plan up-front so we never persist a malformed draft.
    Returns 409 if the task already has a contract (one-to-one).
    """
    task_uuid = _to_uuid(body.task_id)

    # Verify the task exists.
    task_row = await db.execute(
        select(PipelineTask).where(PipelineTask.id == task_uuid)
    )
    task = task_row.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="task_not_found")

    # One-to-one with task.
    existing = await db.execute(
        select(OutcomeContract).where(OutcomeContract.task_id == task_uuid)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="contract_already_exists")

    # Structural validation.
    metric_dicts = [m.model_dump() for m in body.success_metrics]
    metric_errs = validate_metrics_list(metric_dicts)
    if metric_errs:
        raise HTTPException(
            status_code=422,
            detail=f"invalid_metrics: {','.join(metric_errs)}",
        )

    plan_dicts = [p.model_dump() for p in body.verification_plan]
    plan_errs = validate_verification_plan(plan_dicts)
    if plan_errs:
        raise HTTPException(
            status_code=422,
            detail=f"invalid_verification_plan: {','.join(plan_errs)}",
        )

    if body.refund_policy not in REFUND_POLICY_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"bad_refund_policy:{body.refund_policy}",
        )
    for m in body.success_metrics:
        if m.source not in METRIC_SOURCE_VALUES:
            raise HTTPException(
                status_code=422, detail=f"bad_metric_source:{m.source}",
            )
        if m.direction not in METRIC_DIRECTION_VALUES:
            raise HTTPException(
                status_code=422, detail=f"bad_metric_direction:{m.direction}",
            )

    contract = OutcomeContract(
        task_id=task_uuid,
        workspace_id=task.workspace_id,
        business_goal=body.business_goal,
        success_metrics=metric_dicts,
        verification_plan=plan_dicts,
        refund_policy=body.refund_policy,
        refund_trigger=(
            body.refund_trigger.model_dump(exclude_none=True)
            if body.refund_trigger
            else {}
        ),
        price_usd=body.price_usd,
        deposit_pct=body.deposit_pct,
        delivery_deadline=body.delivery_deadline,
        status="draft",
        drafted_by_agent=body.drafted_by_agent or "ceo-agent",
        drafted_at=datetime.utcnow(),
    )
    db.add(contract)
    await db.commit()
    await db.refresh(contract)
    return _contract_dict(contract)


@router.post("/{contract_id}/propose")
async def propose_contract(
    contract_id: str,
    user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    contract = await _load_contract(db, contract_id)
    if contract.status != "draft":
        raise HTTPException(
            status_code=409, detail=f"bad_state:{contract.status}",
        )
    contract.status = "proposed"
    await db.commit()
    await db.refresh(contract)
    return _contract_dict(contract)


@router.post("/{contract_id}/sign")
async def sign_contract(
    contract_id: str,
    body: SignContractRequest,
    db: AsyncSession = Depends(get_db),
):
    """Customer signs → flip status, materialize checkpoints from plan.

    Signing is the entry condition for the rest of the pipeline. After
    this call, the orchestrator can proceed to ``planning`` etc.
    """
    contract = await _load_contract(db, contract_id, with_relations=True)
    if contract.status not in ("draft", "proposed"):
        raise HTTPException(
            status_code=409, detail=f"bad_state:{contract.status}",
        )

    now = datetime.utcnow()
    contract.signed_by_customer = body.signed_by_customer
    contract.signed_at = now
    contract.customer_signature_meta = body.signature_meta or {}
    contract.status = "signed"

    # Materialize checkpoints from the verification plan.
    existing_days = {cp.day_offset for cp in (contract.checkpoints or [])}
    for entry in contract.verification_plan or []:
        day = int(entry.get("day", 0))
        if day <= 0 or day in existing_days:
            continue
        cp = OutcomeCheckpoint(
            contract_id=contract.id,
            day_offset=day,
            method=str(entry.get("method") or "auto_metric_check"),
            scheduled_for=now + timedelta(days=day),
            verdict="pending",
            metric_results=[],
        )
        db.add(cp)

    await db.commit()
    await db.refresh(contract)
    # Reload with relations to return checkpoints.
    contract = await _load_contract(db, contract_id, with_relations=True)
    return _contract_dict(contract, include_checkpoints=True)


@router.post("/{contract_id}/record-metric", status_code=201)
async def record_metric_reading(
    contract_id: str,
    body: RecordMetricRequest,
    user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Append a metric reading. Customer or system pushes.

    Manual readings (``source="manual"``) MUST provide ``evidence_url`` so
    the audit trail stays defensible.
    """
    contract = await _load_contract(db, contract_id)
    if contract.status in ("draft", "proposed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"contract_not_active:{contract.status}",
        )

    if body.source not in METRIC_SOURCE_VALUES:
        raise HTTPException(status_code=422, detail=f"bad_source:{body.source}")

    # Ensure metric is declared on the contract.
    declared = {m.get("name") for m in (contract.success_metrics or [])}
    if body.metric_name not in declared:
        raise HTTPException(
            status_code=422,
            detail=f"metric_not_declared:{body.metric_name}",
        )

    if body.source == "manual" and not body.evidence_url:
        raise HTTPException(
            status_code=422,
            detail="manual_reading_requires_evidence_url",
        )

    recorded_by = (user.email if user else None) or body.evidence_meta.get(
        "recorded_by", "system",
    )

    reading = OutcomeMetricReading(
        contract_id=contract.id,
        metric_name=body.metric_name,
        value=body.value,
        source=body.source,
        evidence_url=body.evidence_url,
        evidence_meta=body.evidence_meta or {},
        recorded_by=recorded_by,
    )
    db.add(reading)
    await db.commit()
    await db.refresh(reading)
    return _reading_dict(reading)


@router.post("/{contract_id}/checkpoints/{day}/run")
async def run_checkpoint(
    contract_id: str,
    day: int,
    db: AsyncSession = Depends(get_db),
):
    """Execute (or re-execute) a single checkpoint and update contract state.

    Idempotent: re-running just refreshes ``metric_results`` and the
    aggregate ``status`` of the contract. If the checkpoint triggers the
    refund condition, the contract flips to ``breached`` (but no money is
    moved — that's an out-of-band step).
    """
    contract = await _load_contract(db, contract_id, with_relations=True)
    if contract.status in ("draft", "proposed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"contract_not_active:{contract.status}",
        )

    cp = next(
        (c for c in (contract.checkpoints or []) if c.day_offset == day),
        None,
    )
    if cp is None:
        raise HTTPException(status_code=404, detail=f"checkpoint_not_found:day_{day}")

    # Reload readings explicitly so we have the freshest data.
    readings_result = await db.execute(
        select(OutcomeMetricReading).where(
            OutcomeMetricReading.contract_id == contract.id
        )
    )
    readings_rows = readings_result.scalars().all()
    points = [
        ReadingPoint(
            metric_name=r.metric_name,
            value=r.value,
            recorded_at=r.recorded_at,
            source=r.source,
        )
        for r in readings_rows
    ]

    window_end = datetime.utcnow()
    verdict = compute_checkpoint_verdict(
        metrics=contract.success_metrics or [],
        readings=points,
        refund_trigger=contract.refund_trigger or {},
        window_end=window_end,
    )

    cp.executed_at = window_end
    cp.verdict = verdict.verdict
    cp.metric_results = verdict.metric_results
    cp.summary = verdict.summary
    if verdict.refund_triggered:
        cp.refund_decision = "trigger"

    # Roll up to contract status.
    # ``verifying`` while any checkpoint is still pending;
    # ``breached`` if any checkpoint triggered refund;
    # ``fulfilled`` only when every checkpoint has passed.
    all_cps = list(contract.checkpoints or [])
    if any(c.refund_decision == "trigger" for c in all_cps) or verdict.refund_triggered:
        contract.status = "breached"
        if not contract.breached_at:
            contract.breached_at = window_end
    elif all(c.verdict == "passed" for c in all_cps):
        contract.status = "fulfilled"
        if not contract.fulfilled_at:
            contract.fulfilled_at = window_end
    else:
        if contract.status == "signed":
            contract.status = "in_delivery"
        if any(c.verdict != "pending" for c in all_cps):
            contract.status = "verifying"

    await db.commit()
    await db.refresh(contract)
    contract = await _load_contract(db, contract_id, with_relations=True)
    return {
        "contract": _contract_dict(contract, include_checkpoints=True),
        "checkpoint": _checkpoint_dict(cp),
        "verdict": verdict.to_dict(),
    }


@router.get("/{contract_id}")
async def get_contract(
    contract_id: str,
    db: AsyncSession = Depends(get_db),
):
    contract = await _load_contract(db, contract_id, with_relations=True)
    return _contract_dict(
        contract, include_checkpoints=True, include_readings_summary=True,
    )


@router.get("/by-task/{task_id}")
async def get_contract_by_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    tid = _to_uuid(task_id)
    result = await db.execute(
        select(OutcomeContract)
        .where(OutcomeContract.task_id == tid)
        .options(
            selectinload(OutcomeContract.checkpoints),
            selectinload(OutcomeContract.readings),
        )
    )
    contract = result.scalar_one_or_none()
    if contract is None:
        raise HTTPException(status_code=404, detail="contract_not_found")
    return _contract_dict(
        contract, include_checkpoints=True, include_readings_summary=True,
    )


@router.get("/")
async def list_contracts(
    status: Optional[str] = None,
    workspace_id: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(OutcomeContract).order_by(OutcomeContract.created_at.desc())
    if status:
        if status not in CONTRACT_STATUS_VALUES:
            raise HTTPException(status_code=422, detail=f"bad_status:{status}")
        stmt = stmt.where(OutcomeContract.status == status)
    if workspace_id:
        stmt = stmt.where(OutcomeContract.workspace_id == _to_uuid(workspace_id))
    stmt = stmt.limit(max(1, min(limit, 200)))
    rows = (await db.execute(stmt)).scalars().all()
    return [_contract_dict(c) for c in rows]


__all__ = ["router", "CHECKPOINT_VERDICT_VALUES"]
