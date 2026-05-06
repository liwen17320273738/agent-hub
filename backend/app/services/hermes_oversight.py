"""
Hermes Oversight — unified supervision orchestrator.

Aggregates 6 supervision dimensions into a single PASS / REQUEST_CHANGES / BLOCK
verdict so the pipeline engine has a single gate to check instead of scattering
the supervision logic across 6 separate modules.

Each dimension function returns a ``DimensionResult`` with a score [0-10]
and a list of findings. The final verdict is computed from the weighted scores.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .self_verify import verify_stage_output, VerifyStatus
from .quality_gates import evaluate_quality_gate, GateStatus
from .guardrails import evaluate_guardrail, GuardrailLevel

logger = logging.getLogger(__name__)


class HermesVerdict(str, Enum):
    PASS = "pass"
    REQUEST_CHANGES = "request_changes"
    BLOCK = "block"


@dataclass
class Finding:
    severity: str          # critical / major / minor / info
    message: str
    source_dimension: str  # self_verify / quality_gate / guardrail / peer_review / observability / final_acceptance
    detail: str = ""


@dataclass
class DimensionResult:
    dimension: str
    status: str            # pass / warn / fail
    score: float           # 0.0 - 10.0
    findings: List[Finding] = field(default_factory=list)
    summary: str = ""


@dataclass
class HermesReport:
    verdict: HermesVerdict
    overall_score: float
    dimensions: List[DimensionResult]
    findings: List[Finding]
    summary: str
    can_proceed: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "overall_score": self.overall_score,
            "can_proceed": self.can_proceed,
            "summary": self.summary,
            "dimensions": [
                {
                    "dimension": d.dimension,
                    "status": d.status,
                    "score": d.score,
                    "findings": [
                        {"severity": f.severity, "message": f.message,
                         "source": f.source_dimension, "detail": f.detail}
                        for f in d.findings
                    ],
                    "summary": d.summary,
                }
                for d in self.dimensions
            ],
            "findings": [
                {"severity": f.severity, "message": f.message,
                 "source": f.source_dimension, "detail": f.detail}
                for f in self.findings
            ],
        }


# ── Weights ──
DIMENSION_WEIGHTS: Dict[str, float] = {
    "self_verify": 0.10,
    "quality_gate": 0.25,
    "guardrail": 0.20,
    "peer_review": 0.20,
    "observability": 0.10,
    "final_acceptance": 0.15,
}

PASS_THRESHOLD = 7.0
BLOCK_THRESHOLD = 4.0


async def run_hermes_oversight(
    db: AsyncSession,
    *,
    task_id: str,
    stage_id: str,
    role: str,
    content: str,
    previous_outputs: Optional[Dict[str, str]] = None,
    force_continue: bool = False,
) -> HermesReport:
    """Run all 6 supervision dimensions and produce a unified report."""
    all_findings: List[Finding] = []
    dimensions: List[DimensionResult] = []
    dimension_scores: Dict[str, float] = {}

    # ── 1. Self-Verify ──
    try:
        verification = verify_stage_output(stage_id, role, content, previous_outputs)
        sv_findings = []
        for check in verification.checks:
            sv_findings.append(Finding(
                severity="major" if check.status == VerifyStatus.FAIL else
                         "minor" if check.status == VerifyStatus.WARN else "info",
                message=check.message,
                source_dimension="self_verify",
                detail=check.details or "",
            ))
        sv_score = _compute_self_verify_score(verification.overall_status)
        dimensions.append(DimensionResult(
            dimension="self_verify",
            status=verification.overall_status.value,
            score=sv_score,
            findings=sv_findings,
            summary=f"{len(verification.checks)} checks, "
                    f"overall={verification.overall_status.value}",
        ))
        all_findings.extend(sv_findings)
        dimension_scores["self_verify"] = sv_score
    except Exception as e:
        logger.warning("[hermes] self_verify failed: %s", e)
        dimension_scores["self_verify"] = 5.0

    # ── 2. Quality Gate ──
    try:
        gate_result = await evaluate_quality_gate(
            stage_id, content,
            template=None,
            previous_outputs=previous_outputs,
            heuristic_result=None,
            skip_llm=force_continue,
        )
        qg_findings = []
        for check in (gate_result.checks or []):
            qg_findings.append(Finding(
                severity="major" if check.status == GateStatus.FAILED else
                         "minor" if check.status == GateStatus.WARNING else "info",
                message=check.message,
                source_dimension="quality_gate",
                detail=check.details or "",
            ))
        qg_score = gate_result.overall_score * 10.0
        dimensions.append(DimensionResult(
            dimension="quality_gate",
            status=gate_result.overall_status.value,
            score=qg_score,
            findings=qg_findings,
            summary=f"score={gate_result.overall_score:.2f}, "
                    f"can_proceed={gate_result.can_proceed}",
        ))
        all_findings.extend(qg_findings)
        dimension_scores["quality_gate"] = qg_score
    except Exception as e:
        logger.warning("[hermes] quality_gate failed: %s", e)
        dimension_scores["quality_gate"] = 5.0

    # ── 3. Guardrail ──
    try:
        action = f"stage:{stage_id}"
        guardrail_result = await evaluate_guardrail(
            action=action, stage_id=stage_id,
            role=role, task_id=task_id,
            context={"content_length": len(content)},
        )
        gr_findings = []
        gr_level = guardrail_result.get("level", GuardrailLevel.AUTO_APPROVE)
        gr_level_str = gr_level.value if hasattr(gr_level, "value") else str(gr_level)
        if not guardrail_result.get("proceed", True):
            gr_findings.append(Finding(
                severity="critical" if gr_level == GuardrailLevel.BLOCK else "major",
                message=guardrail_result.get("reason", f"Guardrail {gr_level_str}"),
                source_dimension="guardrail",
                detail=f"approval_id={guardrail_result.get('approval_id', '')}",
            ))
        gr_score = 10.0 if guardrail_result.get("proceed", True) else \
                   2.0 if gr_level == GuardrailLevel.BLOCK else 5.0
        dimensions.append(DimensionResult(
            dimension="guardrail",
            status="fail" if not guardrail_result.get("proceed", True) else
                   "warn" if gr_level == GuardrailLevel.WARN else "pass",
            score=gr_score,
            findings=gr_findings,
            summary=f"level={gr_level_str}, proceed={guardrail_result.get('proceed', True)}",
        ))
        all_findings.extend(gr_findings)
        dimension_scores["guardrail"] = gr_score
    except Exception as e:
        logger.warning("[hermes] guardrail failed: %s", e)
        dimension_scores["guardrail"] = 5.0

    # ── 4. Peer Review (from stored stage data) ──
    try:
        from sqlalchemy import select
        from ..models.pipeline import PipelineStage

        pr_findings: List[Finding] = []
        pr_score = 10.0
        result = await db.execute(
            select(PipelineStage).where(
                PipelineStage.task_id == task_id,
                PipelineStage.stage_id == stage_id,
            )
        )
        stage_row = result.scalar_one_or_none()
        if stage_row:
            review_status = getattr(stage_row, "review_status", None)
            review_attempts = getattr(stage_row, "review_attempts", 0)
            if review_status == "rejected":
                pr_findings.append(Finding(
                    severity="major",
                    message=f"Peer review rejected after {review_attempts} attempts",
                    source_dimension="peer_review",
                    detail=getattr(stage_row, "reviewer_feedback", "") or "",
                ))
                pr_score = max(2.0, 10.0 - review_attempts * 2.0)
            elif review_attempts > 3:
                pr_findings.append(Finding(
                    severity="minor",
                    message=f"High review churn: {review_attempts} attempts",
                    source_dimension="peer_review",
                    detail="",
                ))
                pr_score = 6.0
        dimensions.append(DimensionResult(
            dimension="peer_review",
            status="fail" if pr_score < 4 else "warn" if pr_score < 7 else "pass",
            score=pr_score,
            findings=pr_findings,
            summary=f"review_attempts={getattr(stage_row, 'review_attempts', 0)}",
        ))
        all_findings.extend(pr_findings)
        dimension_scores["peer_review"] = pr_score
    except Exception as e:
        logger.warning("[hermes] peer_review failed: %s", e)
        dimension_scores["peer_review"] = 5.0

    # ── 5. Observability (placeholder — full trace analysis is heavy) ──
    try:
        from ..services.observability import get_task_traces
        traces = await get_task_traces(task_id)
        ob_findings: List[Finding] = []
        ob_score = 10.0
        if traces:
            latest = traces[0]
            if latest.total_retries > 10:
                ob_findings.append(Finding(
                    severity="major",
                    message=f"High retry count: {latest.total_retries} total retries",
                    source_dimension="observability",
                    detail=f"trace_id={latest.trace_id}",
                ))
                ob_score = 5.0
            elif latest.total_retries > 5:
                ob_findings.append(Finding(
                    severity="minor",
                    message=f"Elevated retry count: {latest.total_retries}",
                    source_dimension="observability",
                    detail="",
                ))
                ob_score = 7.0
        dimensions.append(DimensionResult(
            dimension="observability",
            status="warn" if ob_score < 7 else "pass",
            score=ob_score,
            findings=ob_findings,
            summary=f"traces={len(traces)}, retries={traces[0].total_retries if traces else 0}",
        ))
        all_findings.extend(ob_findings)
        dimension_scores["observability"] = ob_score
    except Exception as e:
        logger.warning("[hermes] observability failed: %s", e)
        dimension_scores["observability"] = 5.0

    # ── 6. Final Acceptance ──
    try:
        fa_findings: List[Finding] = []
        fa_score = 10.0
        from sqlalchemy import select as _select
        from ..models.pipeline import PipelineTask

        result = await db.execute(
            _select(PipelineTask).where(PipelineTask.id == task_id)
        )
        task_row = result.scalar_one_or_none()
        if task_row:
            fa_status = getattr(task_row, "final_acceptance_status", None)
            if fa_status == "rejected":
                fa_findings.append(Finding(
                    severity="major",
                    message="Final acceptance was rejected",
                    source_dimension="final_acceptance",
                    detail=getattr(task_row, "final_acceptance_feedback", "") or "",
                ))
                fa_score = 3.0
            elif fa_status == "accepted":
                fa_score = 10.0
            elif task_row.status == "awaiting_final_acceptance":
                fa_findings.append(Finding(
                    severity="info",
                    message="Awaiting final acceptance",
                    source_dimension="final_acceptance",
                    detail="",
                ))
                fa_score = 7.0
        dimensions.append(DimensionResult(
            dimension="final_acceptance",
            status="fail" if fa_score < 4 else "warn" if fa_score < 7 else "pass",
            score=fa_score,
            findings=fa_findings,
            summary=f"status={getattr(task_row, 'final_acceptance_status', 'none')}",
        ))
        all_findings.extend(fa_findings)
        dimension_scores["final_acceptance"] = fa_score
    except Exception as e:
        logger.warning("[hermes] final_acceptance failed: %s", e)
        dimension_scores["final_acceptance"] = 5.0

    # ── Compute weighted overall score ──
    weighted_sum = 0.0
    weight_total = 0.0
    for dim, weight in DIMENSION_WEIGHTS.items():
        score = dimension_scores.get(dim, 5.0)
        weighted_sum += score * weight
        weight_total += weight
    overall_score = weighted_sum / weight_total if weight_total > 0 else 5.0

    if overall_score >= PASS_THRESHOLD:
        verdict = HermesVerdict.PASS
        can_proceed = True
    elif overall_score >= BLOCK_THRESHOLD:
        verdict = HermesVerdict.REQUEST_CHANGES
        can_proceed = True
    else:
        verdict = HermesVerdict.BLOCK
        can_proceed = False

    # ── Build summary ──
    findings_by_severity: Dict[str, List[Finding]] = {}
    for f in all_findings:
        findings_by_severity.setdefault(f.severity, []).append(f)

    critical_count = len(findings_by_severity.get("critical", []))
    major_count = len(findings_by_severity.get("major", []))
    parts = []
    if critical_count:
        parts.append(f"{critical_count} critical")
    if major_count:
        parts.append(f"{major_count} major")
    summary = f"Overall {verdict.value} ({overall_score:.1f}/10)"
    if parts:
        summary += f" — {', '.join(parts)} issue(s)"

    return HermesReport(
        verdict=verdict,
        overall_score=overall_score,
        dimensions=dimensions,
        findings=all_findings,
        summary=summary,
        can_proceed=can_proceed,
    )


def _compute_self_verify_score(status: VerifyStatus) -> float:
    if status == VerifyStatus.PASS:
        return 10.0
    if status == VerifyStatus.WARN:
        return 6.0
    return 3.0
