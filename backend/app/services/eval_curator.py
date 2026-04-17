"""Eval curator — turn live trace/feedback signals into eval cases.

This is the first half of the "data loop": every successful or human-approved
pipeline run is a free eval case. We harvest them on demand into named
EvalDataset rows so that future regressions can be caught automatically.

Two ingestion sources are supported today:

  1. Recent successful PipelineTask + final stage output → llm_judge case
     (rubric is the original task title, expected output is the recorded
     stage output; the LLM judge then validates the new run against the
     same rubric).

  2. Positive FeedbackRecord (👍 from a human reviewer) → exact / contains
     case (we trust the human and lock in the exact output as the answer).

Curation never overwrites — duplicate (task, expected) pairs are skipped.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.eval import EvalCase, EvalDataset
from ..models.pipeline import PipelineStage, PipelineTask

logger = logging.getLogger(__name__)


def _fingerprint(task: str, expected: Dict[str, Any]) -> str:
    raw = (task or "").strip().lower() + "||" + str(expected or {})
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


async def _existing_fingerprints(db: AsyncSession, dataset_id: str) -> set[str]:
    rows = await db.execute(
        select(EvalCase.task, EvalCase.expected).where(EvalCase.dataset_id == dataset_id)
    )
    fps: set[str] = set()
    for t, e in rows.all():
        fps.add(_fingerprint(t or "", e or {}))
    return fps


async def curate_from_pipeline_tasks(
    db: AsyncSession,
    *,
    dataset_id: str,
    role: Optional[str] = None,
    since_days: int = 14,
    limit: int = 20,
    min_quality_score: float = 0.7,
    scorer: str = "llm_judge",
) -> Dict[str, Any]:
    """Scan recent successful PipelineTask rows and append them as cases.

    A "candidate" is a task whose status is "completed" (or "active" with a
    last stage that produced non-trivial output) and whose
    overall_quality_score (if present) >= min_quality_score.

    Each candidate becomes one EvalCase whose `task` is the original task
    title, whose `expected.rubric` is derived from the title + final stage
    label, and whose `expected.golden` is the produced output (so that
    "contains" scoring also works when no LLM key is present).
    """
    ds = await db.get(EvalDataset, dataset_id)
    if not ds:
        return {"ok": False, "error": "dataset not found"}

    cutoff = datetime.utcnow() - timedelta(days=max(1, since_days))
    q = (
        select(PipelineTask)
        .where(PipelineTask.status.in_(["completed", "active"]))
        .where(PipelineTask.updated_at >= cutoff)
        .order_by(desc(PipelineTask.updated_at))
        .limit(max(1, min(limit * 4, 200)))
    )
    rows = await db.execute(q)
    tasks: List[PipelineTask] = list(rows.scalars().all())

    fps = await _existing_fingerprints(db, dataset_id)
    appended: List[Dict[str, Any]] = []
    skipped = 0

    for task in tasks:
        if len(appended) >= limit:
            break
        if (
            min_quality_score > 0
            and task.overall_quality_score is not None
            and task.overall_quality_score < min_quality_score
        ):
            skipped += 1
            continue

        stage_q = (
            select(PipelineStage)
            .where(PipelineStage.task_id == task.id)
            .where(PipelineStage.status == "done")
            .order_by(desc(PipelineStage.sort_order))
            .limit(1)
        )
        st_row = (await db.execute(stage_q)).scalars().first()
        if not st_row or not st_row.output or len(st_row.output.strip()) < 32:
            skipped += 1
            continue
        if role and (st_row.owner_role or "").lower() != role.lower():
            skipped += 1
            continue

        case_role = role or st_row.owner_role or ds.target_role or ""
        rubric = (
            f"The agent should accomplish: {task.title.strip()}.\n"
            f"The output must be at least as informative as the reference "
            f"answer captured from a previously-approved run."
        )
        golden = st_row.output.strip()[:4000]
        if scorer == "contains":
            expected: Dict[str, Any] = {
                "any": [golden[: min(120, len(golden) // 2)]] if len(golden) >= 60 else [golden],
            }
        else:
            expected = {"rubric": rubric, "golden": golden}

        fp = _fingerprint(task.title, expected)
        if fp in fps:
            skipped += 1
            continue
        fps.add(fp)

        case = EvalCase(
            dataset_id=ds.id,
            name=f"trace:{str(task.id)[:8]}",
            task=task.title,
            role=case_role,
            scorer=scorer,
            expected=expected,
            context={"source": "pipeline_task", "task_id": str(task.id)},
            weight=1.0,
            timeout_seconds=180,
            enabled=True,
        )
        db.add(case)
        appended.append({
            "case_name": case.name,
            "task_title": task.title,
            "role": case_role,
            "source_task_id": str(task.id),
        })

    if appended:
        await db.flush()

    return {
        "ok": True,
        "dataset_id": str(ds.id),
        "scanned": len(tasks),
        "appended": len(appended),
        "skipped": skipped,
        "cases": appended,
    }


async def curate_from_feedback(
    db: AsyncSession,
    *,
    dataset_id: str,
    sentiment: str = "positive",
    since_days: int = 30,
    limit: int = 20,
) -> Dict[str, Any]:
    """Pull positively-rated feedback records and turn them into cases.

    FeedbackRecord schema is small (rating + comment), so this is best-effort
    — when a feedback row references a known PipelineTask (via task_id) we
    can recover the original task text; otherwise we skip.
    """
    try:
        from ..models.feedback import FeedbackRecord  # type: ignore
    except Exception:
        return {"ok": False, "error": "feedback model not available"}

    ds = await db.get(EvalDataset, dataset_id)
    if not ds:
        return {"ok": False, "error": "dataset not found"}

    cutoff = datetime.utcnow() - timedelta(days=max(1, since_days))
    q = (
        select(FeedbackRecord)
        .where(FeedbackRecord.created_at >= cutoff)
        .order_by(desc(FeedbackRecord.created_at))
        .limit(max(1, min(limit * 3, 200)))
    )
    try:
        rows = (await db.execute(q)).scalars().all()
    except Exception as e:
        return {"ok": False, "error": f"feedback query failed: {e}"}

    fps = await _existing_fingerprints(db, dataset_id)
    appended: List[Dict[str, Any]] = []
    for fb in rows:
        if len(appended) >= limit:
            break
        rating = (getattr(fb, "rating", "") or "").lower()
        if sentiment == "positive" and rating not in {"good", "positive", "up", "👍", "5"}:
            continue
        task_id = getattr(fb, "task_id", None)
        if not task_id:
            continue
        task = await db.get(PipelineTask, task_id)
        if not task:
            continue
        expected = {"rubric": f"Reference run was rated positively: {fb.comment or ''}".strip()}
        fp = _fingerprint(task.title, expected)
        if fp in fps:
            continue
        fps.add(fp)
        case = EvalCase(
            dataset_id=ds.id,
            name=f"fb:{str(fb.id)[:8]}",
            task=task.title,
            role=ds.target_role or "",
            scorer="llm_judge",
            expected=expected,
            context={"source": "feedback", "feedback_id": str(fb.id), "task_id": str(task.id)},
        )
        db.add(case)
        appended.append({"case_name": case.name, "task_title": task.title})

    if appended:
        await db.flush()
    return {"ok": True, "dataset_id": str(ds.id), "appended": len(appended), "cases": appended}
