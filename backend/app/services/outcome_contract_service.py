"""
Outcome Contract — pure-function evaluator and helpers.

Kept separate from the API layer so unit tests can exercise the verdict
logic without spinning up FastAPI or a database. The router calls into
these functions after loading the contract + readings from the DB.

Three concerns live here:

1. ``evaluate_metric`` — does ONE metric reading meet its target, given
   the metric definition (target_value, direction, baseline_value)?
2. ``aggregate_readings_for_metric`` — collapse multiple readings into
   a single representative value for a checkpoint (latest by default;
   could be extended to "average over window").
3. ``compute_checkpoint_verdict`` — given a contract + readings, produce
   the full per-metric result list, the overall verdict, and whether the
   refund trigger fires.

The verdict is structural: ``passed`` / ``failed`` / ``partial`` /
``skipped``. Refund firing is a separate boolean computed from the
contract's ``refund_trigger`` config.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Public alias used by API + tests
MetricDef = Dict[str, Any]
MetricResult = Dict[str, Any]


# ---------------------------------------------------------------------------
# Metric definition validation
# ---------------------------------------------------------------------------


REQUIRED_METRIC_KEYS = ("name", "source", "target_value", "direction")


def validate_metric_def(metric: Dict[str, Any]) -> List[str]:
    """Return list of human-readable error keys; empty = valid."""
    errs: List[str] = []
    for k in REQUIRED_METRIC_KEYS:
        if k not in metric or metric[k] in ("", None):
            errs.append(f"missing:{k}")

    direction = metric.get("direction")
    if direction and direction not in ("increase", "decrease", "reach"):
        errs.append(f"bad_direction:{direction}")

    target = metric.get("target_value")
    if target is not None:
        try:
            float(target)
        except (TypeError, ValueError):
            errs.append("bad_target_value")

    window = metric.get("measurement_window_days", 30)
    try:
        if int(window) <= 0:
            errs.append("bad_window")
    except (TypeError, ValueError):
        errs.append("bad_window")

    return errs


def validate_metrics_list(metrics: List[Dict[str, Any]]) -> List[str]:
    if not metrics:
        return ["empty_metrics"]
    errs: List[str] = []
    seen_names = set()
    for i, m in enumerate(metrics):
        for e in validate_metric_def(m):
            errs.append(f"metric[{i}].{e}")
        name = m.get("name")
        if name and name in seen_names:
            errs.append(f"metric[{i}].duplicate_name:{name}")
        if name:
            seen_names.add(name)
    return errs


def validate_verification_plan(plan: List[Dict[str, Any]]) -> List[str]:
    """Each checkpoint needs ``day`` >= 1; ``method`` is optional."""
    if not plan:
        return ["empty_plan"]
    errs: List[str] = []
    days_seen: set[int] = set()
    for i, cp in enumerate(plan):
        day = cp.get("day")
        try:
            d = int(day)
            if d < 1:
                errs.append(f"checkpoint[{i}].bad_day")
            elif d in days_seen:
                errs.append(f"checkpoint[{i}].duplicate_day:{d}")
            else:
                days_seen.add(d)
        except (TypeError, ValueError):
            errs.append(f"checkpoint[{i}].bad_day")
    return errs


# ---------------------------------------------------------------------------
# Reading aggregation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadingPoint:
    """Lightweight view of an OutcomeMetricReading row."""

    metric_name: str
    value: float
    recorded_at: datetime
    source: str = "manual"


def aggregate_readings_for_metric(
    metric: MetricDef,
    readings: Iterable[ReadingPoint],
    *,
    window_end: datetime,
) -> Optional[float]:
    """Return the representative value for ONE metric.

    Strategy (deliberately simple for v1):

    * Filter readings to ``[window_end - measurement_window_days, window_end]``.
    * Pick the **latest** reading inside the window (typical for KPIs like
      "weekly_active_users" where you want the most recent value, not the
      mean of last 30 days).

    Returns ``None`` if no readings exist inside the window.
    """
    name = metric.get("name")
    if not name:
        return None
    window_days = int(metric.get("measurement_window_days", 30))
    window_start = window_end - timedelta(days=window_days)

    in_window: List[ReadingPoint] = [
        r for r in readings
        if r.metric_name == name and window_start <= r.recorded_at <= window_end
    ]
    if not in_window:
        return None
    in_window.sort(key=lambda r: r.recorded_at)
    return in_window[-1].value


# ---------------------------------------------------------------------------
# Per-metric verdict
# ---------------------------------------------------------------------------


def evaluate_metric(metric: MetricDef, actual: Optional[float]) -> MetricResult:
    """Return a per-metric result row.

    Output shape (stable for storage in ``OutcomeCheckpoint.metric_results``):

        {
            "metric": "<name>",
            "target": <float>,
            "actual": <float|None>,
            "baseline": <float|None>,
            "direction": "increase|decrease|reach",
            "passed": <bool>,
            "ratio": <float|None>,
            "missing_reading": <bool>,
        }
    """
    name = metric.get("name") or ""
    target = float(metric.get("target_value", 0.0))
    direction = metric.get("direction", "increase")
    baseline = metric.get("baseline_value")
    baseline_f = float(baseline) if baseline is not None else None

    if actual is None:
        return {
            "metric": name,
            "target": target,
            "actual": None,
            "baseline": baseline_f,
            "direction": direction,
            "passed": False,
            "ratio": None,
            "missing_reading": True,
        }

    actual_f = float(actual)
    if direction == "increase":
        passed = actual_f >= target
        ratio = actual_f / target if target else None
    elif direction == "decrease":
        passed = actual_f <= target
        ratio = (target / actual_f) if actual_f else None
    elif direction == "reach":
        passed = actual_f >= target
        ratio = actual_f / target if target else None
    else:
        passed = False
        ratio = None

    return {
        "metric": name,
        "target": target,
        "actual": actual_f,
        "baseline": baseline_f,
        "direction": direction,
        "passed": bool(passed),
        "ratio": ratio,
        "missing_reading": False,
    }


# ---------------------------------------------------------------------------
# Checkpoint-level verdict
# ---------------------------------------------------------------------------


@dataclass
class CheckpointVerdict:
    verdict: str                       # passed | failed | partial | skipped
    metric_results: List[MetricResult] = field(default_factory=list)
    summary: str = ""
    refund_triggered: bool = False
    refund_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "metric_results": self.metric_results,
            "summary": self.summary,
            "refund_triggered": self.refund_triggered,
            "refund_reason": self.refund_reason,
        }


def _check_refund_trigger(
    trigger: Dict[str, Any], metric_results: List[MetricResult]
) -> Tuple[bool, str]:
    """Evaluate the contract's ``refund_trigger`` against the metric results."""
    if not trigger:
        # Default: refund only when ALL metrics fail (most generous to us).
        any_passed = any(r["passed"] for r in metric_results)
        return (not any_passed, "all_metrics_failed (default trigger)")

    rule = trigger.get("trigger") or "all_metrics_failed"

    if rule == "any_metric_failed":
        failed = [r for r in metric_results if not r["passed"]]
        if failed:
            names = ",".join(r["metric"] for r in failed)
            return True, f"any_metric_failed:{names}"
        return False, ""

    if rule == "all_metrics_failed":
        if metric_results and all(not r["passed"] for r in metric_results):
            return True, "all_metrics_failed"
        return False, ""

    if rule == "ratio_below":
        threshold = float(trigger.get("ratio", 0.5))
        ratios = [
            r["ratio"] for r in metric_results
            if r.get("ratio") is not None
        ]
        if not ratios:
            return False, ""
        worst = min(ratios)
        if worst < threshold:
            return True, f"ratio_below:{worst:.3f}<{threshold}"
        return False, ""

    return False, f"unknown_trigger:{rule}"


def compute_checkpoint_verdict(
    *,
    metrics: List[MetricDef],
    readings: Iterable[ReadingPoint],
    refund_trigger: Dict[str, Any],
    window_end: datetime,
) -> CheckpointVerdict:
    """Run the full checkpoint logic and return a structured verdict.

    * ``passed`` — every metric passed.
    * ``failed`` — every metric failed (or no readings at all).
    * ``partial`` — some passed, some failed.
    * ``skipped`` — no metrics defined (shouldn't happen for signed contracts).
    """
    if not metrics:
        return CheckpointVerdict(verdict="skipped", summary="no metrics defined")

    readings_list = list(readings)
    results: List[MetricResult] = []
    for m in metrics:
        actual = aggregate_readings_for_metric(m, readings_list, window_end=window_end)
        results.append(evaluate_metric(m, actual))

    passed_count = sum(1 for r in results if r["passed"])
    total = len(results)
    missing = sum(1 for r in results if r.get("missing_reading"))

    if passed_count == total:
        verdict = "passed"
    elif passed_count == 0:
        verdict = "failed"
    else:
        verdict = "partial"

    refund_fires, refund_reason = _check_refund_trigger(refund_trigger or {}, results)

    summary_bits = [f"{passed_count}/{total} metrics passed"]
    if missing:
        summary_bits.append(f"{missing} metric(s) had no readings in window")
    if refund_fires:
        summary_bits.append(f"refund triggered ({refund_reason})")
    summary = "; ".join(summary_bits)

    return CheckpointVerdict(
        verdict=verdict,
        metric_results=results,
        summary=summary,
        refund_triggered=refund_fires,
        refund_reason=refund_reason,
    )


__all__ = [
    "ReadingPoint",
    "MetricDef",
    "MetricResult",
    "CheckpointVerdict",
    "validate_metric_def",
    "validate_metrics_list",
    "validate_verification_plan",
    "aggregate_readings_for_metric",
    "evaluate_metric",
    "compute_checkpoint_verdict",
]
