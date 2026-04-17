"""Weekly digest — surface agent regressions across two time windows.

Compares the most recent N days against the previous N days for each
agent role, using:
  - Eval pass-rate (per-role aggregation of EvalRun.passed_cases / total)
  - Eval avg score
  - Span p95 latency from observability traces
  - Pipeline stage failure-rate (status='failed' / total stage runs)

Returns a per-role report with deltas + a list of "regressions" — roles
whose pass-rate dropped >10 ppts or avg score dropped >0.10 or p95
latency increased >50%.

This module is deterministic and read-only; it does not require an LLM.
A future "narrative summary" can be layered on top by calling chat_completion.
"""
from __future__ import annotations

import logging
import math
import statistics
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.eval import EvalRun, EvalResult
from ..models.observability import SpanRecord
from ..models.pipeline import PipelineStage

logger = logging.getLogger(__name__)


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(s[int(k)])
    return float(s[f] + (s[c] - s[f]) * (k - f))


async def _eval_metrics_for_window(
    db: AsyncSession, *, since: datetime, until: datetime
) -> Dict[str, Dict[str, Any]]:
    """role -> {pass_rate, avg_score, runs, results}"""
    runs = (
        await db.execute(
            select(EvalRun)
            .where(EvalRun.completed_at.isnot(None))
            .where(EvalRun.completed_at >= since)
            .where(EvalRun.completed_at < until)
        )
    ).scalars().all()
    if not runs:
        return {}

    by_role: Dict[str, Dict[str, Any]] = {}
    for r in runs:
        results = (
            await db.execute(select(EvalResult).where(EvalResult.run_id == r.id))
        ).scalars().all()
        for res in results:
            role = res.role or r.agent_role_override or "unknown"
            slot = by_role.setdefault(
                role,
                {"passed": 0, "total": 0, "scores": [], "latencies": [], "runs": set()},
            )
            slot["total"] += 1
            slot["passed"] += 1 if res.passed else 0
            slot["scores"].append(float(res.score or 0.0))
            slot["latencies"].append(float(res.latency_ms or 0))
            slot["runs"].add(str(r.id))

    out: Dict[str, Dict[str, Any]] = {}
    for role, slot in by_role.items():
        total = slot["total"] or 1
        out[role] = {
            "eval_total": slot["total"],
            "eval_passed": slot["passed"],
            "eval_pass_rate": round(slot["passed"] / total, 4),
            "eval_avg_score": round(statistics.fmean(slot["scores"]) if slot["scores"] else 0.0, 4),
            "eval_avg_latency_ms": round(
                statistics.fmean(slot["latencies"]) if slot["latencies"] else 0.0, 1
            ),
            "eval_runs": len(slot["runs"]),
        }
    return out


async def _span_metrics_for_window(
    db: AsyncSession, *, since: datetime, until: datetime
) -> Dict[str, Dict[str, Any]]:
    cutoff_since = since.timestamp()
    cutoff_until = until.timestamp()
    rows = (
        await db.execute(
            select(SpanRecord)
            .where(SpanRecord.started_at >= cutoff_since)
            .where(SpanRecord.started_at < cutoff_until)
        )
    ).scalars().all()
    by_role: Dict[str, Dict[str, Any]] = {}
    for sp in rows:
        role = sp.role or "unknown"
        slot = by_role.setdefault(role, {"durations": [], "errors": 0, "total": 0, "tokens": 0})
        slot["total"] += 1
        slot["durations"].append(float(sp.duration_ms or 0))
        slot["tokens"] += int(sp.total_tokens or 0)
        if (sp.status or "").lower() == "failed":
            slot["errors"] += 1

    out: Dict[str, Dict[str, Any]] = {}
    for role, slot in by_role.items():
        out[role] = {
            "span_total": slot["total"],
            "span_failed": slot["errors"],
            "span_failure_rate": round(slot["errors"] / max(1, slot["total"]), 4),
            "span_p50_ms": round(_percentile(slot["durations"], 0.5), 1),
            "span_p95_ms": round(_percentile(slot["durations"], 0.95), 1),
            "span_total_tokens": slot["tokens"],
        }
    return out


async def _stage_failure_rate(
    db: AsyncSession, *, since: datetime, until: datetime
) -> Dict[str, Dict[str, Any]]:
    rows = (
        await db.execute(
            select(PipelineStage)
            .where(PipelineStage.completed_at.isnot(None))
            .where(PipelineStage.completed_at >= since)
            .where(PipelineStage.completed_at < until)
        )
    ).scalars().all()
    by_role: Dict[str, Dict[str, int]] = {}
    for s in rows:
        role = (s.owner_role or "unknown").strip() or "unknown"
        slot = by_role.setdefault(role, {"total": 0, "failed": 0})
        slot["total"] += 1
        if (s.status or "").lower() == "failed":
            slot["failed"] += 1
    out: Dict[str, Dict[str, Any]] = {}
    for role, slot in by_role.items():
        out[role] = {
            "stage_total": slot["total"],
            "stage_failed": slot["failed"],
            "stage_failure_rate": round(slot["failed"] / max(1, slot["total"]), 4),
        }
    return out


def _merge_metrics(*sources: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for src in sources:
        for role, data in src.items():
            merged.setdefault(role, {}).update(data)
    return merged


def _diff(curr: float, prev: float) -> Dict[str, float]:
    abs_delta = round(curr - prev, 4)
    rel = (abs_delta / prev) if prev else (1.0 if curr else 0.0)
    return {"current": round(curr, 4), "previous": round(prev, 4),
            "delta": abs_delta, "rel_delta": round(rel, 4)}


def _detect_regressions(
    curr: Dict[str, Dict[str, Any]],
    prev: Dict[str, Dict[str, Any]],
    *,
    pass_rate_drop: float = 0.10,
    score_drop: float = 0.10,
    latency_increase: float = 0.50,
) -> List[Dict[str, Any]]:
    regressions: List[Dict[str, Any]] = []
    roles = sorted(set(curr.keys()) | set(prev.keys()))
    for role in roles:
        c = curr.get(role, {})
        p = prev.get(role, {})
        reasons: List[str] = []
        # Pass rate
        if "eval_pass_rate" in c and "eval_pass_rate" in p:
            d = c["eval_pass_rate"] - p["eval_pass_rate"]
            if d <= -pass_rate_drop:
                reasons.append(
                    f"pass-rate dropped {abs(d) * 100:.1f}ppt "
                    f"({p['eval_pass_rate'] * 100:.1f}% → {c['eval_pass_rate'] * 100:.1f}%)"
                )
        # Avg score
        if "eval_avg_score" in c and "eval_avg_score" in p:
            d = c["eval_avg_score"] - p["eval_avg_score"]
            if d <= -score_drop:
                reasons.append(
                    f"avg score dropped {abs(d):.2f} ({p['eval_avg_score']:.2f} → {c['eval_avg_score']:.2f})"
                )
        # Latency
        if "span_p95_ms" in c and "span_p95_ms" in p and p["span_p95_ms"] > 0:
            rel = (c["span_p95_ms"] - p["span_p95_ms"]) / p["span_p95_ms"]
            if rel >= latency_increase:
                reasons.append(
                    f"p95 latency rose {rel * 100:.0f}% "
                    f"({p['span_p95_ms']:.0f}ms → {c['span_p95_ms']:.0f}ms)"
                )
        # Stage failure rate
        if "stage_failure_rate" in c and "stage_failure_rate" in p:
            d = c["stage_failure_rate"] - p["stage_failure_rate"]
            if d >= 0.10:
                reasons.append(
                    f"stage failure rose {d * 100:.1f}ppt "
                    f"({p['stage_failure_rate'] * 100:.1f}% → {c['stage_failure_rate'] * 100:.1f}%)"
                )
        if reasons:
            regressions.append({"role": role, "reasons": reasons})
    return regressions


async def compute_digest(
    db: AsyncSession,
    *,
    since_days: int = 7,
    prev_days: Optional[int] = None,
    pass_rate_drop: float = 0.10,
    score_drop: float = 0.10,
    latency_increase: float = 0.50,
) -> Dict[str, Any]:
    now = datetime.utcnow()
    window = max(1, since_days)
    prev_window = max(1, prev_days or window)

    curr_until = now
    curr_since = now - timedelta(days=window)
    prev_until = curr_since
    prev_since = prev_until - timedelta(days=prev_window)

    curr_eval = await _eval_metrics_for_window(db, since=curr_since, until=curr_until)
    prev_eval = await _eval_metrics_for_window(db, since=prev_since, until=prev_until)
    curr_spans = await _span_metrics_for_window(db, since=curr_since, until=curr_until)
    prev_spans = await _span_metrics_for_window(db, since=prev_since, until=prev_until)
    curr_stage = await _stage_failure_rate(db, since=curr_since, until=curr_until)
    prev_stage = await _stage_failure_rate(db, since=prev_since, until=prev_until)

    curr = _merge_metrics(curr_eval, curr_spans, curr_stage)
    prev = _merge_metrics(prev_eval, prev_spans, prev_stage)

    roles = sorted(set(curr.keys()) | set(prev.keys()))
    rows: List[Dict[str, Any]] = []
    for role in roles:
        c = curr.get(role, {})
        p = prev.get(role, {})
        rows.append({
            "role": role,
            "current": c,
            "previous": p,
            "deltas": {
                "eval_pass_rate": _diff(c.get("eval_pass_rate", 0.0), p.get("eval_pass_rate", 0.0)),
                "eval_avg_score": _diff(c.get("eval_avg_score", 0.0), p.get("eval_avg_score", 0.0)),
                "span_p95_ms": _diff(c.get("span_p95_ms", 0.0), p.get("span_p95_ms", 0.0)),
                "stage_failure_rate": _diff(
                    c.get("stage_failure_rate", 0.0), p.get("stage_failure_rate", 0.0)
                ),
            },
        })

    regressions = _detect_regressions(
        curr, prev,
        pass_rate_drop=pass_rate_drop,
        score_drop=score_drop,
        latency_increase=latency_increase,
    )

    return {
        "ok": True,
        "generated_at": now.isoformat() + "Z",
        "current_window": {"since": curr_since.isoformat() + "Z", "until": curr_until.isoformat() + "Z", "days": window},
        "previous_window": {"since": prev_since.isoformat() + "Z", "until": prev_until.isoformat() + "Z", "days": prev_window},
        "roles": rows,
        "regressions": regressions,
        "regressions_count": len(regressions),
    }
