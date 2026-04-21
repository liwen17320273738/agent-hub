"""
Learning loop REST surface — view signals, propose / activate / archive prompt
overrides, trigger on-demand distillation.

GET    /api/learning/signals?stage_id=&distilled=&limit=
GET    /api/learning/overrides?stage_id=&status=
POST   /api/learning/overrides/{id}/activate
POST   /api/learning/overrides/{id}/archive
POST   /api/learning/overrides/{id}/disable
POST   /api/learning/distill?stage_id=&auto_apply=
GET    /api/learning/summary    — per-stage counts (signals + active overrides)
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.learning import LearningSignal, PromptOverride
from ..security import get_current_user
from ..services.learning_loop import (
    SIGNAL_TYPES,
    distill_signals_for_stage,
    evaluate_auto_promotion,
    get_policy_config,
    list_overrides,
    list_signals,
    set_override_status,
    set_override_targeting,
)


router = APIRouter(prefix="/api/learning", tags=["learning"])


@router.get("/signals")
async def get_signals(
    stage_id: Optional[str] = Query(None),
    distilled: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    return {
        "signal_types": SIGNAL_TYPES,
        "signals": await list_signals(
            db, stage_id=stage_id, distilled=distilled, limit=limit,
        ),
    }


@router.get("/overrides")
async def get_overrides(
    stage_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    return {
        "overrides": await list_overrides(
            db, stage_id=stage_id, status=status, limit=limit,
        ),
    }


class StatusBody(BaseModel):
    actor: Optional[str] = None


def _actor_from_user(user, body: Optional[StatusBody]) -> str:
    if body and body.actor:
        return body.actor
    if user is not None and hasattr(user, "id"):
        return str(user.id)
    return "system"


@router.post("/overrides/{override_id}/activate")
async def activate_override(
    override_id: str,
    body: Optional[StatusBody] = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await set_override_status(
        db, override_id=override_id, status="active",
        actor=_actor_from_user(user, body),
    )
    if not result:
        raise HTTPException(status_code=404, detail="Override not found")
    await db.commit()
    return {"override": result}


@router.post("/overrides/{override_id}/archive")
async def archive_override(
    override_id: str,
    body: Optional[StatusBody] = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await set_override_status(
        db, override_id=override_id, status="archived",
        actor=_actor_from_user(user, body),
    )
    if not result:
        raise HTTPException(status_code=404, detail="Override not found")
    await db.commit()
    return {"override": result}


@router.post("/overrides/{override_id}/disable")
async def disable_override(
    override_id: str,
    body: Optional[StatusBody] = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await set_override_status(
        db, override_id=override_id, status="disabled",
        actor=_actor_from_user(user, body),
    )
    if not result:
        raise HTTPException(status_code=404, detail="Override not found")
    await db.commit()
    return {"override": result}


@router.post("/overrides/{override_id}/shadow")
async def shadow_override(
    override_id: str,
    body: Optional[StatusBody] = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Promote a proposed override into the A/B shadow slot.

    The shadow runs alongside the active override and absorbs
    ``LEARNING_SHADOW_TRAFFIC`` (default 30%) of traffic. Once it has
    enough samples the auto-policy graduates the winner.
    """
    result = await set_override_status(
        db, override_id=override_id, status="shadow",
        actor=_actor_from_user(user, body),
    )
    if not result:
        raise HTTPException(status_code=404, detail="Override not found")
    await db.commit()
    return {"override": result}


class TargetingBody(BaseModel):
    """Targeting filter for an override.

    * ``templates``: only inject for these task templates
      (e.g. ``["full","fast"]``). Empty/missing = match-anything.
    * ``complexities``: only inject for these complexity tiers
      (e.g. ``["simple","medium"]``). Empty/missing = match-anything.
    """
    templates: Optional[List[str]] = None
    complexities: Optional[List[str]] = None


@router.put("/overrides/{override_id}/targeting")
async def update_override_targeting(
    override_id: str,
    body: TargetingBody,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Replace this override's segment targeting filter.

    Send an empty body (``{}``) to revert to "match-anything", which is
    the legacy pre-segmentation behaviour. Multiple shadows on the same
    stage with disjoint targeting can run concurrently.
    """
    payload: dict = {}
    if body.templates:
        payload["templates"] = list(body.templates)
    if body.complexities:
        payload["complexities"] = list(body.complexities)

    result = await set_override_targeting(
        db, override_id=override_id, targeting=payload,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Override not found")
    await db.commit()
    return {"override": result}


class DistillBody(BaseModel):
    stage_id: str
    auto_apply: bool = False
    signal_ids: Optional[List[str]] = None


@router.post("/distill")
async def distill(
    body: DistillBody,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    result = await distill_signals_for_stage(
        db, stage_id=body.stage_id,
        auto_apply=body.auto_apply,
        forced_signal_ids=body.signal_ids,
    )
    if not result:
        raise HTTPException(
            status_code=400,
            detail="Nothing to distill (no undistilled REJECT/GATE_FAIL signals "
                   "for this stage, or LLM output unparseable).",
        )
    await db.commit()
    return {"override": result}


@router.get("/summary")
async def summary(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Per-stage rollup: signal count by type, active override info, undistilled count."""
    sig_rows = await db.execute(
        select(
            LearningSignal.stage_id,
            LearningSignal.signal_type,
            LearningSignal.distilled,
            func.count().label("c"),
        ).group_by(
            LearningSignal.stage_id, LearningSignal.signal_type, LearningSignal.distilled,
        )
    )
    by_stage: dict = {}
    for stage_id, sig_type, distilled, c in sig_rows.all():
        s = by_stage.setdefault(stage_id, {
            "stage_id": stage_id, "signals_total": 0,
            "signals_undistilled": 0, "by_type": {}, "active_override": None,
            "proposed_overrides": 0, "archived_overrides": 0,
        })
        s["signals_total"] += int(c or 0)
        if not distilled:
            s["signals_undistilled"] += int(c or 0)
        s["by_type"][sig_type] = s["by_type"].get(sig_type, 0) + int(c or 0)

    ovr_rows = await db.execute(
        select(PromptOverride.stage_id, PromptOverride.status, func.count().label("c"))
        .group_by(PromptOverride.stage_id, PromptOverride.status)
    )
    for stage_id, status, c in ovr_rows.all():
        s = by_stage.setdefault(stage_id, {
            "stage_id": stage_id, "signals_total": 0,
            "signals_undistilled": 0, "by_type": {}, "active_override": None,
            "proposed_overrides": 0, "archived_overrides": 0,
        })
        if status == "proposed":
            s["proposed_overrides"] += int(c or 0)
        elif status == "archived":
            s["archived_overrides"] += int(c or 0)

    actives = await db.execute(
        select(PromptOverride).where(PromptOverride.status == "active")
    )
    for ov in actives.scalars().all():
        s = by_stage.setdefault(ov.stage_id, {
            "stage_id": ov.stage_id, "signals_total": 0,
            "signals_undistilled": 0, "by_type": {}, "active_override": None,
            "proposed_overrides": 0, "archived_overrides": 0,
        })
        s["active_override"] = {
            "id": str(ov.id), "title": ov.title, "version": ov.version,
            "uses": ov.impact_uses, "approves": ov.impact_approves,
            "rejects": ov.impact_rejects,
        }

    return {"per_stage": list(by_stage.values())}


# ─────────────────────────────────────────────────────────────────────────────
# Auto-promotion / demotion policy
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/policy")
async def get_policy(_user=Depends(get_current_user)):
    """Read the current auto-promotion thresholds (env-toggleable)."""
    return get_policy_config()


class AutoPromoteBody(BaseModel):
    stage_id: Optional[str] = None
    actor: Optional[str] = None


@router.post("/auto-promote/evaluate")
async def auto_promote_evaluate(
    body: Optional[AutoPromoteBody] = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Manually run the auto-promotion / demotion policy.

    - `stage_id` omitted → evaluate every stage that has either an active or
      proposed override.
    - returns the list of policy events that fired (may be empty).
    """
    actor = (body.actor if body and body.actor else None) or (
        getattr(user, "id", None) and f"user:{user.id}"
    ) or "manual"

    if body and body.stage_id:
        stages = [body.stage_id]
    else:
        rows = await db.execute(
            select(PromptOverride.stage_id)
            .where(PromptOverride.status.in_(["active", "proposed"]))
            .distinct()
        )
        stages = [s for (s,) in rows.all()]

    events: List[dict] = []
    for sid in stages:
        try:
            outcome = await evaluate_auto_promotion(db, stage_id=sid, actor=actor)
            if outcome:
                events.extend(outcome.get("events") or [])
        except Exception as exc:  # pragma: no cover — defensive
            events.append({"action": "error", "stage_id": sid, "reason": str(exc)})
    if events:
        await db.commit()
    return {"evaluated_stages": stages, "events": events}
