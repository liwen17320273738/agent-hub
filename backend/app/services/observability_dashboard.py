"""
Observability dashboard aggregator.

Single read-only entry point that returns everything the Pipeline Observability
UI needs in one round-trip:

- cost & token daily trend buckets
- per-stage heatmap (avg duration, pass rate, retry rate, avg cost, sample count)
- agent leaderboard (role -> tasks, pass_rate, avg_score, total_cost)
- model leaderboard (model -> calls, total_cost, avg_duration)
- recent failures (last N stages with status=failed or REJECT)
- approval / budget-block summary

All cheap aggregates against indexed columns; safe to call on every page load.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import func, select, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.observability import (
    SpanRecord,
    AuditLog,
    ApprovalRecord,
)
from ..models.pipeline import PipelineStage, PipelineTask


def _utc_floor_day(ts: datetime) -> datetime:
    return datetime(ts.year, ts.month, ts.day, tzinfo=timezone.utc)


def _to_epoch_utc(dt: datetime) -> float:
    """Convert any datetime (naive UTC or aware) to a UTC epoch seconds float."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).timestamp()
    return dt.timestamp()


async def _cost_token_daily(
    db: AsyncSession, *, since: datetime,
) -> Dict[str, List[Dict[str, Any]]]:
    """Daily trend of cost / tokens / llm_calls aggregated from span_records."""
    rows = await db.execute(
        select(
            SpanRecord.started_at,
            SpanRecord.cost_usd,
            SpanRecord.total_tokens,
            SpanRecord.duration_ms,
        ).where(SpanRecord.started_at >= _to_epoch_utc(since))
    )
    buckets: Dict[str, Dict[str, float]] = {}
    for started_at, cost, tokens, dur in rows.all():
        if not started_at:
            continue
        day = datetime.fromtimestamp(started_at, tz=timezone.utc).strftime("%Y-%m-%d")
        b = buckets.setdefault(day, {"cost": 0.0, "tokens": 0, "calls": 0, "duration": 0})
        b["cost"] += float(cost or 0.0)
        b["tokens"] += int(tokens or 0)
        b["calls"] += 1
        b["duration"] += int(dur or 0)
    out = []
    for day, b in sorted(buckets.items()):
        out.append({
            "day": day,
            "cost_usd": round(b["cost"], 6),
            "tokens": b["tokens"],
            "llm_calls": b["calls"],
            "avg_duration_ms": int(b["duration"] / b["calls"]) if b["calls"] else 0,
        })
    return {"daily": out}


async def _stage_heatmap(db: AsyncSession, *, since: datetime) -> List[Dict[str, Any]]:
    """Per-stage rollup: avg duration, pass rate (gate=pass / review=approved),
    retry rate, sample count. Pulled from pipeline_stages."""
    rows = await db.execute(
        select(
            PipelineStage.stage_id,
            PipelineStage.owner_role,
            PipelineStage.status,
            PipelineStage.review_status,
            PipelineStage.gate_status,
            PipelineStage.gate_score,
            PipelineStage.retry_count,
            PipelineStage.started_at,
            PipelineStage.completed_at,
        ).where(PipelineStage.started_at >= since)
    )
    agg: Dict[str, Dict[str, Any]] = {}
    for r in rows.all():
        sid = r.stage_id
        a = agg.setdefault(sid, {
            "stage_id": sid,
            "role": r.owner_role or "",
            "samples": 0,
            "duration_ms_sum": 0,
            "duration_count": 0,
            "passes": 0,
            "fails": 0,
            "rejects": 0,
            "approves": 0,
            "retries_total": 0,
            "score_sum": 0.0,
            "score_count": 0,
        })
        a["samples"] += 1
        a["retries_total"] += int(r.retry_count or 0)
        if r.gate_status == "pass":
            a["passes"] += 1
        elif r.gate_status == "fail":
            a["fails"] += 1
        if r.review_status == "approved":
            a["approves"] += 1
        elif r.review_status == "rejected":
            a["rejects"] += 1
        if r.gate_score is not None:
            a["score_sum"] += float(r.gate_score)
            a["score_count"] += 1
        if r.started_at and r.completed_at:
            a["duration_ms_sum"] += int(
                (r.completed_at - r.started_at).total_seconds() * 1000
            )
            a["duration_count"] += 1

    out = []
    for sid, a in agg.items():
        n = a["samples"]
        gate_n = a["passes"] + a["fails"]
        review_n = a["approves"] + a["rejects"]
        out.append({
            "stage_id": sid,
            "role": a["role"],
            "samples": n,
            "avg_duration_ms": int(a["duration_ms_sum"] / a["duration_count"])
                if a["duration_count"] else 0,
            "pass_rate": round(a["passes"] / gate_n, 4) if gate_n else None,
            "approve_rate": round(a["approves"] / review_n, 4) if review_n else None,
            "avg_score": round(a["score_sum"] / a["score_count"], 4)
                if a["score_count"] else None,
            "retry_rate": round(a["retries_total"] / n, 4) if n else 0.0,
            "rejects": a["rejects"],
            "fails": a["fails"],
        })
    out.sort(key=lambda x: x["samples"], reverse=True)
    return out


async def _agent_leaderboard(db: AsyncSession, *, since: datetime) -> List[Dict[str, Any]]:
    """Per-role rollup of: stages handled, approval rate, avg quality_score,
    total cost (joined via SpanRecord.role)."""
    stage_rows = await db.execute(
        select(
            PipelineStage.owner_role,
            PipelineStage.status,
            PipelineStage.review_status,
            PipelineStage.gate_score,
        ).where(PipelineStage.started_at >= since)
    )
    role_agg: Dict[str, Dict[str, Any]] = {}
    for role, status, review_status, score in stage_rows.all():
        if not role:
            continue
        a = role_agg.setdefault(role, {
            "role": role, "stages": 0, "approves": 0, "rejects": 0,
            "fails": 0, "score_sum": 0.0, "score_count": 0,
            "cost_usd": 0.0, "tokens": 0, "calls": 0,
        })
        a["stages"] += 1
        if review_status == "approved":
            a["approves"] += 1
        elif review_status == "rejected":
            a["rejects"] += 1
        if status == "failed":
            a["fails"] += 1
        if score is not None:
            a["score_sum"] += float(score)
            a["score_count"] += 1

    span_rows = await db.execute(
        select(
            SpanRecord.role,
            func.sum(SpanRecord.cost_usd).label("cost"),
            func.sum(SpanRecord.total_tokens).label("tokens"),
            func.count().label("calls"),
        )
        .where(SpanRecord.started_at >= _to_epoch_utc(since))
        .group_by(SpanRecord.role)
    )
    for role, cost, tokens, calls in span_rows.all():
        if not role:
            continue
        a = role_agg.setdefault(role, {
            "role": role, "stages": 0, "approves": 0, "rejects": 0,
            "fails": 0, "score_sum": 0.0, "score_count": 0,
            "cost_usd": 0.0, "tokens": 0, "calls": 0,
        })
        a["cost_usd"] = float(cost or 0.0)
        a["tokens"] = int(tokens or 0)
        a["calls"] = int(calls or 0)

    out = []
    for role, a in role_agg.items():
        review_n = a["approves"] + a["rejects"]
        out.append({
            "role": role,
            "stages": a["stages"],
            "approve_rate": round(a["approves"] / review_n, 4) if review_n else None,
            "avg_score": round(a["score_sum"] / a["score_count"], 4)
                if a["score_count"] else None,
            "total_cost_usd": round(a["cost_usd"], 6),
            "total_tokens": a["tokens"],
            "llm_calls": a["calls"],
            "fails": a["fails"],
            "rejects": a["rejects"],
        })
    out.sort(key=lambda x: (x["stages"] + x["llm_calls"]), reverse=True)
    return out


async def _model_leaderboard(db: AsyncSession, *, since: datetime) -> List[Dict[str, Any]]:
    rows = await db.execute(
        select(
            SpanRecord.model,
            SpanRecord.tier,
            func.sum(SpanRecord.cost_usd).label("cost"),
            func.sum(SpanRecord.total_tokens).label("tokens"),
            func.sum(SpanRecord.duration_ms).label("duration"),
            func.count().label("calls"),
            func.sum(case((SpanRecord.status == "failed", 1), else_=0)).label("failures"),
        )
        .where(SpanRecord.started_at >= _to_epoch_utc(since))
        .group_by(SpanRecord.model, SpanRecord.tier)
    )
    out = []
    for model, tier, cost, tokens, dur, calls, failures in rows.all():
        if not model:
            continue
        out.append({
            "model": model,
            "tier": tier or "",
            "calls": int(calls or 0),
            "total_cost_usd": round(float(cost or 0.0), 6),
            "total_tokens": int(tokens or 0),
            "avg_duration_ms": int((dur or 0) / calls) if calls else 0,
            "failure_rate": round((failures or 0) / calls, 4) if calls else 0.0,
        })
    out.sort(key=lambda x: x["total_cost_usd"], reverse=True)
    return out


async def _recent_failures(db: AsyncSession, *, since: datetime, limit: int = 15) -> List[Dict[str, Any]]:
    rows = await db.execute(
        select(
            PipelineStage.task_id,
            PipelineStage.stage_id,
            PipelineStage.owner_role,
            PipelineStage.status,
            PipelineStage.review_status,
            PipelineStage.last_error,
            PipelineStage.reviewer_feedback,
            PipelineStage.completed_at,
            PipelineStage.retry_count,
            PipelineTask.title,
        )
        .join(PipelineTask, PipelineTask.id == PipelineStage.task_id)
        .where(
            and_(
                PipelineStage.started_at >= since,
                PipelineStage.status.in_(["failed", "blocked"]) |
                (PipelineStage.review_status == "rejected"),
            )
        )
        .order_by(PipelineStage.completed_at.desc().nullslast())
        .limit(limit)
    )
    out = []
    for r in rows.all():
        out.append({
            "task_id": str(r.task_id),
            "task_title": r.title,
            "stage_id": r.stage_id,
            "role": r.owner_role,
            "status": r.status,
            "review_status": r.review_status,
            "retry_count": int(r.retry_count or 0),
            "last_error": (r.last_error or "")[:240],
            "reviewer_feedback": (r.reviewer_feedback or "")[:240],
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        })
    return out


async def _approval_summary(db: AsyncSession, *, since: datetime) -> Dict[str, Any]:
    rows = await db.execute(
        select(
            ApprovalRecord.status,
            ApprovalRecord.risk_level,
            func.count().label("c"),
        )
        .where(ApprovalRecord.created_at >= since)
        .group_by(ApprovalRecord.status, ApprovalRecord.risk_level)
    )
    by_status: Dict[str, int] = {}
    by_risk: Dict[str, int] = {}
    total = 0
    for status, risk, c in rows.all():
        c = int(c or 0)
        total += c
        by_status[status] = by_status.get(status, 0) + c
        by_risk[risk] = by_risk.get(risk, 0) + c
    return {"total": total, "by_status": by_status, "by_risk": by_risk}


async def _budget_block_summary(db: AsyncSession, *, since: datetime) -> Dict[str, Any]:
    """Audit-log derived: how many cost-governor blocks / downgrades happened."""
    rows = await db.execute(
        select(
            AuditLog.action,
            func.count().label("c"),
        )
        .where(
            AuditLog.created_at >= since,
            AuditLog.action.in_(["budget.block", "budget.downgrade", "budget.raise"])
        )
        .group_by(AuditLog.action)
    )
    return {row.action: int(row.c or 0) for row in rows.all()}


async def _task_status_summary(db: AsyncSession, *, since: datetime) -> Dict[str, int]:
    rows = await db.execute(
        select(PipelineTask.status, func.count().label("c"))
        .where(PipelineTask.created_at >= since)
        .group_by(PipelineTask.status)
    )
    return {row.status: int(row.c or 0) for row in rows.all()}


async def get_dashboard_snapshot(
    db: AsyncSession, *, days: int = 14,
) -> Dict[str, Any]:
    """Single-call snapshot for the observability page."""
    # NB: stage / task / approval columns are TIMESTAMP WITHOUT TIME ZONE in
    # this project, so we pass naive UTC for those queries. Span/trace use a
    # float epoch so the aware/naive distinction doesn't matter there.
    since = datetime.utcnow() - timedelta(days=days)

    cost_tokens = await _cost_token_daily(db, since=since)
    stages = await _stage_heatmap(db, since=since)
    agents = await _agent_leaderboard(db, since=since)
    models = await _model_leaderboard(db, since=since)
    failures = await _recent_failures(db, since=since)
    approvals = await _approval_summary(db, since=since)
    budget_events = await _budget_block_summary(db, since=since)
    task_status = await _task_status_summary(db, since=since)

    totals = {
        "cost_usd": round(sum(d["cost_usd"] for d in cost_tokens["daily"]), 6),
        "tokens": sum(d["tokens"] for d in cost_tokens["daily"]),
        "llm_calls": sum(d["llm_calls"] for d in cost_tokens["daily"]),
        "tasks": sum(task_status.values()),
        "stages_executed": sum(s["samples"] for s in stages),
        "rejects": sum(s["rejects"] for s in stages),
        "fails": sum(s["fails"] for s in stages),
    }

    return {
        "window": {"days": days, "since": since.isoformat()},
        "totals": totals,
        "trend": cost_tokens["daily"],
        "stage_heatmap": stages,
        "agent_leaderboard": agents,
        "model_leaderboard": models,
        "recent_failures": failures,
        "approvals": approvals,
        "budget_events": budget_events,
        "task_status": task_status,
    }
