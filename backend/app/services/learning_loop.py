"""
Learning loop — close the gap from "tries→fails→retries" to "tries→learns→improves".

Pipeline:
1. capture_signal()           — called inline by pipeline_engine on every
                                 REJECT / GATE_FAIL / RETRY / APPROVE_AFTER_RETRY.
2. distill_signals_for_stage()— LLM-distils N undistilled signals for a stage
                                 into one PromptOverride proposal. Triggered
                                 either on-demand (API), on a threshold reach
                                 inside capture_signal, or by a nightly cron.
3. get_active_addendum()      — called by pipeline_engine before LLM call to
                                 splice the active (or shadow) override into
                                 the system prompt.
4. record_override_outcome() — called by pipeline_engine after the post-stage
                                 review so we can score the override's impact.

Lifecycle:
- New PromptOverrides start as `proposed` and are NOT auto-injected.
- They can be flipped to one of:
    * `active`   — full-traffic injection; only one per stage
    * `shadow`   — A/B canary; receives `SHADOW_TRAFFIC_RATIO` of traffic
                   alongside the active override and accumulates impact
                   stats. Auto-graduates / auto-retires based on whether
                   it beats the predecessor.
    * `archived` — kept for audit, never injected
    * `disabled` — kill-switched, kept for audit
- `auto_apply=True` promotes proposed→active immediately on creation.
"""
from __future__ import annotations

import json
import logging
import os
import random
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.learning import LearningSignal, PromptOverride
from ..redis_client import cache_delete, cache_get, cache_set
from .llm_router import chat_completion as llm_chat

logger = logging.getLogger(__name__)


# Trigger LLM distillation once a stage accumulates this many undistilled signals.
DISTILL_TRIGGER_THRESHOLD = 3
# Cap how many signals we feed the distillation LLM in a single batch.
DISTILL_MAX_BATCH = 12
# Cache TTL for active addendum (so injection doesn't hit Postgres every stage).
ACTIVE_CACHE_TTL = 60  # seconds

# ── Auto-activation policy thresholds ────────────────────────────────────
# A `proposed` override is auto-promoted to `active` when (a) it has no
# `active` competitor on the same stage, OR (b) the active competitor's
# approve rate over enough samples has fallen below the demotion floor.
# An `active` override is auto-demoted to `archived` when its sample size
# is large enough AND its approve rate has fallen below the floor.
AUTO_PROMOTE_MIN_USES = 5            # minimum data points before any policy fires
AUTO_PROMOTE_MIN_APPROVE_RATE = 0.70  # promote if predecessor approve_rate < this
AUTO_DEMOTE_MAX_REJECT_RATE = 0.50    # demote active when reject_rate ≥ this
AUTO_PROMOTE_DEFAULT_ENABLED = True   # global kill switch (env override below)

# ── A/B shadow mode thresholds ────────────────────────────────────────────
# A `shadow` override is injected into a fraction of traffic alongside the
# active override on the same stage. Once it has enough data, we compare
# its approve rate to the active and either graduate it (full active) or
# archive it (it lost the canary). Both sides run the same LLM call — the
# choice is made *before* the call, so cost is identical to a single run.
SHADOW_TRAFFIC_RATIO = float(os.getenv("LEARNING_SHADOW_TRAFFIC", "0.30"))
SHADOW_MIN_USES = 5                # require enough samples before deciding
SHADOW_GRADUATE_MARGIN = 0.10       # shadow must beat active by ≥ 10 pts
SHADOW_RETIRE_MARGIN = 0.10         # archive shadow if active beats it by ≥ 10 pts


def _auto_policy_enabled() -> bool:
    import os
    raw = os.getenv("LEARNING_AUTO_POLICY")
    if raw is None:
        return AUTO_PROMOTE_DEFAULT_ENABLED
    return raw.strip().lower() in ("1", "true", "yes", "on")


SIGNAL_TYPES = {
    "REJECT": "Peer reviewer rejected output",
    "GATE_FAIL": "Quality gate failed",
    "RETRY": "Stage retried after failure",
    "APPROVE_AFTER_RETRY": "Approved after at least one retry (positive correction signal)",
    "HUMAN_OVERRIDE": "Human flipped automatic decision",
    "BLOCKED": "Cost/guardrail blocked execution",
}


async def capture_signal(
    db: AsyncSession,
    *,
    task_id: str,
    stage_id: str,
    role: str = "",
    signal_type: str,
    severity: str = "info",
    reviewer: Optional[str] = None,
    reviewer_feedback: Optional[str] = None,
    output_excerpt: Optional[str] = None,
    error_excerpt: Optional[str] = None,
    retry_count: int = 0,
    quality_score: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> LearningSignal:
    """Persist one signal and (best-effort) trigger distillation when we cross
    the threshold for this stage. NEVER raises — learning is best-effort."""
    sig = LearningSignal(
        task_id=str(task_id),
        stage_id=stage_id,
        role=role or "",
        signal_type=signal_type,
        severity=severity,
        reviewer=reviewer,
        reviewer_feedback=(reviewer_feedback or "")[:4000] or None,
        output_excerpt=(output_excerpt or "")[:4000] or None,
        error_excerpt=(error_excerpt or "")[:2000] or None,
        retry_count=int(retry_count or 0),
        quality_score=quality_score,
        metadata_extra=metadata or {},
    )
    db.add(sig)
    await db.flush()

    try:
        if signal_type in ("REJECT", "GATE_FAIL", "HUMAN_OVERRIDE"):
            count = await _undistilled_count(db, stage_id=stage_id)
            if count >= DISTILL_TRIGGER_THRESHOLD:
                logger.info(
                    "[learning] stage=%s undistilled=%d — triggering distillation",
                    stage_id, count,
                )
                await distill_signals_for_stage(db, stage_id=stage_id)

            if signal_type == "REJECT":
                await check_reject_patterns(db, stage_id=stage_id)
    except Exception as exc:  # pragma: no cover — never propagate
        logger.warning("[learning] auto-distill failed for %s: %s", stage_id, exc)

    return sig


async def _undistilled_count(db: AsyncSession, *, stage_id: str) -> int:
    from sqlalchemy import func
    res = await db.execute(
        select(func.count(LearningSignal.id)).where(
            and_(
                LearningSignal.stage_id == stage_id,
                LearningSignal.distilled.is_(False),
                LearningSignal.signal_type.in_(["REJECT", "GATE_FAIL", "HUMAN_OVERRIDE"]),
            )
        )
    )
    return int(res.scalar() or 0)


async def list_signals(
    db: AsyncSession, *, stage_id: Optional[str] = None,
    distilled: Optional[bool] = None, limit: int = 50,
) -> List[Dict[str, Any]]:
    stmt = select(LearningSignal)
    if stage_id:
        stmt = stmt.where(LearningSignal.stage_id == stage_id)
    if distilled is not None:
        stmt = stmt.where(LearningSignal.distilled.is_(distilled))
    stmt = stmt.order_by(LearningSignal.created_at.desc()).limit(limit)
    res = await db.execute(stmt)
    out = []
    for s in res.scalars().all():
        out.append({
            "id": str(s.id), "task_id": s.task_id, "stage_id": s.stage_id,
            "role": s.role, "signal_type": s.signal_type, "severity": s.severity,
            "reviewer": s.reviewer, "reviewer_feedback": s.reviewer_feedback,
            "output_excerpt": s.output_excerpt, "error_excerpt": s.error_excerpt,
            "retry_count": s.retry_count, "quality_score": s.quality_score,
            "distilled": bool(s.distilled),
            "distilled_into_id": str(s.distilled_into_id) if s.distilled_into_id else None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Distillation
# ─────────────────────────────────────────────────────────────────────────────

_DISTILL_SYSTEM = """你是 Agent Hub 的"提示工程优化教练"。
我会给你某个 SDLC 阶段（比如 design / development / testing 等）最近 N 次执行的失败/被拒/重试样本（peer-review feedback 或 quality gate 不通过的原因）。

你的任务：把这些样本中**反复出现的失败模式**抽象为 3-8 条**简短、可执行**的规则，作为该阶段 system prompt 的"补丁"加进去，让下次执行时直接避免这些坑。

输出严格的 JSON（不要多余文本）：
{
  "title": "简短标题，10 字内，描述这次补丁要解决的核心问题",
  "rationale": "1-3 句话说明这些规则从哪些反复出现的失败模式归纳出来",
  "addendum": "Markdown 格式的提示补丁正文。结构为：\\n\\n## 强制要求（来自历史复盘）\\n- 规则 1\\n- 规则 2\\n- ...\\n\\n每条规则要短、可验证、和样本里反复出现的失败直接对应。"
}

规则约束：
- 不要笼统的"提高质量""注意安全"之类废话
- 不要重复 system prompt 已经强调过的内容（除非样本表明该要求被忽略）
- 每条规则必须能从样本里找到至少 2 次出现的失败映射
- 最多 8 条；少而精 > 多而泛
- addendum 必须以 "## 强制要求（来自历史复盘）" 开头
"""


def _format_signals_for_distill(signals: List[LearningSignal]) -> str:
    parts = []
    for i, s in enumerate(signals, 1):
        block = [f"### 样本 {i}  (signal_type={s.signal_type}, severity={s.severity})"]
        if s.reviewer_feedback:
            block.append(f"- reviewer 反馈：\n{s.reviewer_feedback[:1500]}")
        if s.error_excerpt:
            block.append(f"- 错误：\n{s.error_excerpt[:800]}")
        if s.output_excerpt:
            block.append(f"- 被拒输出片段：\n{s.output_excerpt[:1500]}")
        parts.append("\n".join(block))
    return "\n\n".join(parts)


def _safe_json_extract(content: str) -> Optional[Dict[str, Any]]:
    content = content.strip()
    # try fenced ```json
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content[: -3]
    # find first { ... last }
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None


async def distill_signals_for_stage(
    db: AsyncSession, *, stage_id: str,
    auto_apply: bool = False,
    forced_signal_ids: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Pick the latest undistilled REJECT/GATE_FAIL/HUMAN_OVERRIDE signals for
    the stage, ask an LLM to distill them, persist a PromptOverride proposal,
    and mark the source signals as distilled.

    Returns the new override dict, or None if there's nothing to distill / the
    LLM output was unparseable.
    """
    if forced_signal_ids:
        from sqlalchemy.dialects.postgresql import UUID as PG_UUID  # noqa: F401
        res = await db.execute(
            select(LearningSignal).where(LearningSignal.id.in_(forced_signal_ids))
        )
    else:
        res = await db.execute(
            select(LearningSignal).where(
                and_(
                    LearningSignal.stage_id == stage_id,
                    LearningSignal.distilled.is_(False),
                    LearningSignal.signal_type.in_(
                        ["REJECT", "GATE_FAIL", "HUMAN_OVERRIDE"]
                    ),
                )
            ).order_by(LearningSignal.created_at.desc()).limit(DISTILL_MAX_BATCH)
        )
    signals: List[LearningSignal] = list(res.scalars().all())
    if not signals:
        return None

    role = signals[0].role
    payload = _format_signals_for_distill(signals)

    from ..config import settings as app_settings
    model = app_settings.llm_model or "deepseek-chat"
    api_url = app_settings.llm_api_url or ""

    try:
        llm_result = await llm_chat(
            model=model,
            messages=[
                {"role": "system", "content": _DISTILL_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"阶段：{stage_id}（角色：{role}）\n"
                        f"样本数：{len(signals)}\n\n{payload}"
                    ),
                },
            ],
            api_url=api_url,
        )
    except Exception as exc:
        logger.warning("[learning] LLM call failed for distill stage=%s: %s",
                       stage_id, exc)
        return None

    if llm_result.get("error"):
        logger.warning("[learning] LLM error for distill: %s", llm_result["error"])
        return None

    parsed = _safe_json_extract(llm_result.get("content", ""))
    if not parsed or not parsed.get("addendum"):
        logger.warning("[learning] unparseable LLM distill output for %s", stage_id)
        return None

    parent = await _latest_active_override(db, stage_id=stage_id)
    new_version = (parent.version + 1) if parent else 1

    override = PromptOverride(
        stage_id=stage_id,
        role=role,
        title=(parsed.get("title") or f"{stage_id} 自动复盘补丁 v{new_version}")[:200],
        addendum=parsed["addendum"][:8000],
        rationale=(parsed.get("rationale") or "")[:2000],
        # New overrides land in shadow mode (A/B canary) regardless of auto_apply
        status="shadow",
        auto_apply=bool(auto_apply),
        sample_signal_ids=[str(s.id) for s in signals],
        distilled_from_n=len(signals),
        version=new_version,
        parent_id=parent.id if parent else None,
    )
    if auto_apply:
        override.activated_at = datetime.utcnow()
        override.activated_by = "auto-distill"

    db.add(override)
    await db.flush()

    sig_ids = [s.id for s in signals]
    await db.execute(
        update(LearningSignal)
        .where(LearningSignal.id.in_(sig_ids))
        .values(distilled=True, distilled_into_id=override.id)
    )

    if auto_apply:
        await _bust_active_cache(stage_id)

    logger.info(
        "[learning] distilled %d signals into override %s (stage=%s, status=%s)",
        len(signals), override.id, stage_id, override.status,
    )
    return _override_to_dict(override)


def _targeting_matches(
    targeting: Optional[Dict[str, Any]],
    *,
    template: Optional[str],
    complexity: Optional[str],
) -> bool:
    """Return True iff this override's targeting allows the given segment.

    Targeting schema::
        {"templates": [...], "complexities": [...]}

    Empty dict / missing keys / empty lists = match-anything (legacy
    behaviour for rows that pre-date this feature). Segments are matched
    case-sensitively.
    """
    if not targeting:
        return True
    templates = targeting.get("templates") or []
    if templates and template and template not in templates:
        return False
    complexities = targeting.get("complexities") or []
    if complexities and complexity and complexity not in complexities:
        return False
    return True


async def _latest_active_override(
    db: AsyncSession,
    *,
    stage_id: str,
    template: Optional[str] = None,
    complexity: Optional[str] = None,
) -> Optional[PromptOverride]:
    """Highest-version active override on this stage that matches the
    requested segment. None if no active matches.
    """
    res = await db.execute(
        select(PromptOverride).where(
            and_(
                PromptOverride.stage_id == stage_id,
                PromptOverride.status == "active",
            )
        ).order_by(PromptOverride.version.desc())
    )
    for o in res.scalars().all():
        if _targeting_matches(o.targeting, template=template, complexity=complexity):
            return o
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Activation API
# ─────────────────────────────────────────────────────────────────────────────

async def list_overrides(
    db: AsyncSession, *, stage_id: Optional[str] = None,
    status: Optional[str] = None, limit: int = 100,
) -> List[Dict[str, Any]]:
    stmt = select(PromptOverride)
    if stage_id:
        stmt = stmt.where(PromptOverride.stage_id == stage_id)
    if status:
        stmt = stmt.where(PromptOverride.status == status)
    stmt = stmt.order_by(PromptOverride.created_at.desc()).limit(limit)
    res = await db.execute(stmt)
    return [_override_to_dict(o) for o in res.scalars().all()]


async def set_override_status(
    db: AsyncSession, *, override_id: str, status: str,
    actor: str = "system",
) -> Optional[Dict[str, Any]]:
    """Transition an override to a new lifecycle state.

    Statuses
    --------
    * ``proposed``  — distilled but not in production
    * ``active``    — full-traffic injection. Promotion archives any other
                      active or shadow override on the same stage.
    * ``shadow``    — A/B canary. Coexists with the active override and
                      receives ``SHADOW_TRAFFIC_RATIO`` of traffic. Other
                      pre-existing shadows on the same stage are archived
                      (only one shadow at a time per stage).
    * ``archived``  — kept for audit, never injected
    * ``disabled``  — kill-switched, kept for audit
    """
    if status not in ("proposed", "active", "shadow", "archived", "disabled"):
        raise ValueError(f"invalid status: {status}")

    res = await db.execute(
        select(PromptOverride).where(PromptOverride.id == override_id)
    )
    override = res.scalar_one_or_none()
    if not override:
        return None

    now = datetime.utcnow()
    if status == "active":
        # Archive every other active/shadow on this stage WHOSE TARGETING
        # OVERLAPS with the one we're activating. Two actives with disjoint
        # targeting (e.g. one for `template=full`, one for `template=fast`)
        # can coexist — they serve different segments. Same logic for
        # shadow conflicts.
        await _archive_overlapping(
            db,
            stage_id=override.stage_id,
            new_targeting=override.targeting or {},
            statuses=("active", "shadow"),
            keep_id=override.id,
            now=now,
        )
        override.status = "active"
        override.activated_at = now
        override.activated_by = actor
    elif status == "shadow":
        # Only one shadow per overlapping segment per stage. Disjoint
        # targeting means parallel canaries are allowed (which is the
        # whole point of segmentation).
        await _archive_overlapping(
            db,
            stage_id=override.stage_id,
            new_targeting=override.targeting or {},
            statuses=("shadow",),
            keep_id=override.id,
            now=now,
        )
        override.status = "shadow"
        override.activated_at = now
        override.activated_by = actor
    elif status == "archived":
        override.status = "archived"
        override.archived_at = now
    else:
        override.status = status

    await db.flush()
    await _bust_active_cache(override.stage_id)
    return _override_to_dict(override)


async def set_override_targeting(
    db: AsyncSession,
    *,
    override_id: str,
    targeting: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Replace the targeting filter on an override and bust caches.

    ``targeting`` may be ``None`` or an empty dict to revert to
    "match-anything". Unknown keys are preserved (forward-compat) but
    only ``templates`` / ``complexities`` are honoured by the matcher.
    """
    res = await db.execute(
        select(PromptOverride).where(PromptOverride.id == override_id)
    )
    override = res.scalar_one_or_none()
    if not override:
        return None

    override.targeting = dict(targeting or {})
    await db.flush()
    await _bust_active_cache(override.stage_id)
    return _override_to_dict(override)


def _targeting_overlap(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Two targeting dicts overlap iff there is at least one (template,
    complexity) pair both would accept. An empty dict on either side
    means "match anything", so it overlaps with everything."""
    if not a or not b:
        return True
    a_t = set(a.get("templates") or [])
    b_t = set(b.get("templates") or [])
    if a_t and b_t and not (a_t & b_t):
        return False
    a_c = set(a.get("complexities") or [])
    b_c = set(b.get("complexities") or [])
    if a_c and b_c and not (a_c & b_c):
        return False
    return True


async def _archive_overlapping(
    db: AsyncSession,
    *,
    stage_id: str,
    new_targeting: Dict[str, Any],
    statuses: tuple,
    keep_id: uuid.UUID,
    now: datetime,
) -> None:
    """Archive every override on this stage with given statuses whose
    targeting overlaps the new one (excluding ``keep_id``).

    We do the overlap check in Python because storing arbitrary JSON
    targeting and querying it portably across PG/SQLite is hairy. Each
    stage typically has a handful of active+shadow rows so this is cheap.
    """
    res = await db.execute(
        select(PromptOverride).where(
            and_(
                PromptOverride.stage_id == stage_id,
                PromptOverride.status.in_(statuses),
                PromptOverride.id != keep_id,
            )
        )
    )
    for o in res.scalars().all():
        if _targeting_overlap(new_targeting, o.targeting or {}):
            o.status = "archived"
            o.archived_at = now


def _override_to_dict(o: PromptOverride) -> Dict[str, Any]:
    return {
        "id": str(o.id),
        "stage_id": o.stage_id,
        "role": o.role,
        "title": o.title,
        "addendum": o.addendum,
        "rationale": o.rationale,
        "status": o.status,
        "auto_apply": bool(o.auto_apply),
        "sample_signal_ids": list(o.sample_signal_ids or []),
        "distilled_from_n": o.distilled_from_n,
        "version": o.version,
        "parent_id": str(o.parent_id) if o.parent_id else None,
        "activated_at": o.activated_at.isoformat() if o.activated_at else None,
        "activated_by": o.activated_by,
        "archived_at": o.archived_at.isoformat() if o.archived_at else None,
        "targeting": dict(o.targeting or {}),
        "impact": {
            "uses": o.impact_uses,
            "approves": o.impact_approves,
            "rejects": o.impact_rejects,
            "approve_rate": (
                round(o.impact_approves / (o.impact_approves + o.impact_rejects), 4)
                if (o.impact_approves + o.impact_rejects) else None
            ),
        },
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Runtime injection (called by pipeline_engine before LLM call)
# ─────────────────────────────────────────────────────────────────────────────

def _cache_key(
    stage_id: str,
    *,
    template: Optional[str] = None,
    complexity: Optional[str] = None,
) -> str:
    """Cache key includes segment so different (template, complexity)
    callers can cache their distinct candidate pairs independently."""
    seg = f"{template or '*'}|{complexity or '*'}"
    return f"learning:active_addendum:{stage_id}:{seg}"


async def _bust_active_cache(stage_id: str) -> None:
    """Drop every segment cache for this stage. Cheap because pattern
    deletion uses Redis SCAN; safe because stale active selection would
    otherwise stick around for ACTIVE_CACHE_TTL after a status change."""
    try:
        from ..redis_client import cache_delete_pattern
        await cache_delete_pattern(f"learning:active_addendum:{stage_id}:*")
    except Exception:
        pass
    # Legacy single-key cache from before segmentation — drop it too in
    # case something is mid-deploy.
    try:
        await cache_delete(f"learning:active_addendum:{stage_id}")
    except Exception:
        pass


async def _latest_shadow_override(
    db: AsyncSession,
    *,
    stage_id: str,
    template: Optional[str] = None,
    complexity: Optional[str] = None,
) -> Optional[PromptOverride]:
    """Latest shadow override on this stage matching the segment, or None.

    Multiple shadows can coexist if their targeting segments are disjoint
    (see ``set_override_status`` for the conflict rule). When several
    match the same call, we pick the newest one.
    """
    res = await db.execute(
        select(PromptOverride).where(
            and_(
                PromptOverride.stage_id == stage_id,
                PromptOverride.status == "shadow",
            )
        ).order_by(PromptOverride.version.desc(), PromptOverride.created_at.desc())
    )
    for o in res.scalars().all():
        if _targeting_matches(o.targeting, template=template, complexity=complexity):
            return o
    return None


async def get_active_addendum(
    db: AsyncSession,
    *,
    stage_id: str,
    template: Optional[str] = None,
    complexity: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return the addendum to inject for this stage's next LLM call, or None.

    Segment matching
    ----------------
    ``template`` / ``complexity`` are the runtime segment for this call.
    Only overrides whose ``targeting`` matches the segment (or whose
    targeting is empty = match-anything) are eligible. Multiple shadow
    overrides with disjoint targeting can coexist; this function picks
    the latest match.

    Selection rules
    ---------------
    * If a shadow override matches the segment, with probability
      ``SHADOW_TRAFFIC_RATIO`` it wins this call (returned with
      ``mode='shadow'``). Otherwise control falls through to the active
      override.
    * If only an active matches, it's returned with ``mode='active'``.
    * If neither matches, returns None.

    Caching: cache key is per-segment so different segments don't
    invalidate each other; the cache stores the *pair* of candidates,
    so the per-call random roll still produces an even split.
    """
    key = _cache_key(stage_id, template=template, complexity=complexity)
    cached = await cache_get(key)
    is_new_shape = (
        isinstance(cached, dict) and ("active" in cached or "shadow" in cached)
    )
    if cached is None or not is_new_shape:
        active = await _latest_active_override(
            db, stage_id=stage_id, template=template, complexity=complexity,
        )
        shadow = await _latest_shadow_override(
            db, stage_id=stage_id, template=template, complexity=complexity,
        )
        cached = {
            "active": _addendum_payload(active) if active else None,
            "shadow": _addendum_payload(shadow) if shadow else None,
        }
        await cache_set(key, cached, ttl=ACTIVE_CACHE_TTL)

    active_payload = cached.get("active") if isinstance(cached, dict) else None
    shadow_payload = cached.get("shadow") if isinstance(cached, dict) else None

    # Shadow only rides alongside a *vetted* active baseline, at
    # SHADOW_TRAFFIC_RATIO. A lone shadow (no active) must NOT hijack 100% of
    # production traffic: it's an un-vetted, auto-distilled prompt with no
    # baseline to A/B against, and injecting it everywhere lets a single bad
    # distillation poison the stage (its section structure can even conflict
    # with the artifact contract → systematic rejection). In that case fall
    # back to the base prompt (None) so the contract-aligned prompt governs.
    if shadow_payload and active_payload:
        if random.random() < SHADOW_TRAFFIC_RATIO:
            return {**shadow_payload, "mode": "shadow"}
        return {**active_payload, "mode": "active"}

    if active_payload:
        return {**active_payload, "mode": "active"}
    return None


def _addendum_payload(o: PromptOverride) -> Dict[str, Any]:
    return {
        "id": str(o.id),
        "title": o.title,
        "addendum": o.addendum,
        "version": o.version,
    }


async def record_override_outcome(
    db: AsyncSession, *, override_id: str, approved: bool,
) -> Optional[Dict[str, Any]]:
    """Bump the impact counter on an override after a stage that used it
    finishes its peer review, then run the auto-activation policy
    SCOPED TO THE OVERRIDE'S TARGETING SEGMENT.

    Why segment-scoped? With segmentation, there can be (e.g.) one shadow
    targeting ``template=full`` and a different shadow targeting
    ``template=fast``. A REJECT on the full-targeted shadow should not
    cause us to graduate or retire the fast-targeted one. So we look
    up the just-incremented override's targeting and pass a
    representative (template, complexity) into ``evaluate_auto_promotion``
    so it only compares within that segment.

    Best-effort, never raises.
    """
    try:
        col = PromptOverride.impact_approves if approved else PromptOverride.impact_rejects
        await db.execute(
            update(PromptOverride)
            .where(PromptOverride.id == override_id)
            .values(
                impact_uses=PromptOverride.impact_uses + 1,
                **{col.key: col + 1},
            )
            # populate_existing forces the identity map to refresh on next
            # SELECT — important so evaluate_auto_promotion below sees the
            # *post-increment* counters, not stale cached values.
            .execution_options(synchronize_session="fetch")
        )
        await db.flush()
        try:
            db.expire_all()
        except Exception:
            pass
    except Exception as exc:
        logger.debug("[learning] record_override_outcome failed: %s", exc)
        return None

    if not _auto_policy_enabled():
        return None

    try:
        res = await db.execute(
            select(PromptOverride.stage_id, PromptOverride.targeting).where(
                PromptOverride.id == override_id
            )
        )
        row = res.first()
        if not row:
            return None
        stage_id, targeting = row[0], row[1] or {}
        # Pick a representative segment from the override's targeting so
        # the evaluator considers the same audience this update came
        # from. None → match-anything (legacy overrides).
        templates = (targeting.get("templates") or []) if isinstance(targeting, dict) else []
        complexities = (targeting.get("complexities") or []) if isinstance(targeting, dict) else []
        seg_template = templates[0] if templates else None
        seg_complexity = complexities[0] if complexities else None
        return await evaluate_auto_promotion(
            db, stage_id=stage_id, actor="auto-policy",
            template=seg_template, complexity=seg_complexity,
        )
    except Exception as exc:
        logger.debug("[learning] auto-policy evaluation failed: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Auto-promotion / demotion policy
# ─────────────────────────────────────────────────────────────────────────────

def _approve_rate(o: PromptOverride) -> Optional[float]:
    total = (o.impact_approves or 0) + (o.impact_rejects or 0)
    if total <= 0:
        return None
    return (o.impact_approves or 0) / total


async def _latest_proposed_override(
    db: AsyncSession, *, stage_id: str,
) -> Optional[PromptOverride]:
    res = await db.execute(
        select(PromptOverride).where(
            and_(
                PromptOverride.stage_id == stage_id,
                PromptOverride.status == "proposed",
            )
        ).order_by(PromptOverride.version.desc(), PromptOverride.created_at.desc()).limit(1)
    )
    return res.scalar_one_or_none()


async def evaluate_auto_promotion(
    db: AsyncSession, *, stage_id: str, actor: str = "auto-policy",
    template: Optional[str] = None, complexity: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Decide whether to auto-promote a proposed override or auto-demote a
    failing active one for a single stage.

    Rules (applied in order):

    1. **Demote first** — if the active override has accumulated enough
       samples (`AUTO_PROMOTE_MIN_USES`) and its reject rate is at or above
       `AUTO_DEMOTE_MAX_REJECT_RATE`, archive it. Frees the stage for the
       next proposal to be auto-promoted (rule 2).

    2. **Promote** when:
       a. No active override exists on this stage AND a proposed override
          flagged with `auto_apply=True` is waiting; or
       b. There is a proposed override (any flag) whose predecessor
          (the still-active override it would replace) has a poor approve
          rate (< `AUTO_PROMOTE_MIN_APPROVE_RATE`) over enough samples.

    Returns a policy event dict on action, or None if nothing changed.
    """
    # All lookups are scoped to (template, complexity) so segmented
    # canaries don't compete with each other.
    active = await _latest_active_override(
        db, stage_id=stage_id, template=template, complexity=complexity,
    )
    shadow = await _latest_shadow_override(
        db, stage_id=stage_id, template=template, complexity=complexity,
    )
    proposed = await _latest_proposed_override(db, stage_id=stage_id)

    # 0) A/B shadow graduation — a shadow with enough samples either wins
    #    (replaces active) or loses (gets archived). Run this BEFORE the
    #    demote-active rule so a clearly-superior shadow can take over even
    #    if the active hasn't crossed the demote threshold yet.
    if shadow and (shadow.impact_uses or 0) >= SHADOW_MIN_USES:
        shadow_rate = _approve_rate(shadow)
        active_rate = _approve_rate(active) if active else None

        if shadow_rate is not None:
            # If there's no active baseline, a shadow that hits the global
            # promote threshold simply gets graduated.
            if active is None:
                if shadow_rate >= AUTO_PROMOTE_MIN_APPROVE_RATE:
                    promoted = await set_override_status(
                        db, override_id=str(shadow.id), status="active", actor=actor,
                    )
                    if promoted:
                        event = {
                            "action": "shadow_graduated",
                            "stage_id": stage_id,
                            "override_id": str(shadow.id),
                            "version": shadow.version,
                            "shadow_approve_rate": round(shadow_rate, 3),
                            "shadow_uses": shadow.impact_uses,
                            "reason": (
                                f"no active baseline; shadow approve_rate "
                                f"{shadow_rate:.2f} ≥ {AUTO_PROMOTE_MIN_APPROVE_RATE}"
                            ),
                        }
                        logger.info("[learning][auto-policy] %s", event)
                        await _emit_policy_event(event)
                        return {"events": [event]}

            elif active_rate is not None and (active.impact_uses or 0) >= SHADOW_MIN_USES:
                # Both sides have enough data — head-to-head comparison.
                if shadow_rate - active_rate >= SHADOW_GRADUATE_MARGIN:
                    promoted = await set_override_status(
                        db, override_id=str(shadow.id), status="active", actor=actor,
                    )
                    if promoted:
                        event = {
                            "action": "shadow_graduated",
                            "stage_id": stage_id,
                            "override_id": str(shadow.id),
                            "version": shadow.version,
                            "predecessor_id": str(active.id),
                            "shadow_approve_rate": round(shadow_rate, 3),
                            "active_approve_rate": round(active_rate, 3),
                            "margin": round(shadow_rate - active_rate, 3),
                            "reason": (
                                f"shadow beat active by "
                                f"{shadow_rate - active_rate:.2f} ≥ "
                                f"{SHADOW_GRADUATE_MARGIN}"
                            ),
                        }
                        logger.info("[learning][auto-policy] %s", event)
                        await _emit_policy_event(event)
                        return {"events": [event]}

                if active_rate - shadow_rate >= SHADOW_RETIRE_MARGIN:
                    archived = await set_override_status(
                        db, override_id=str(shadow.id), status="archived", actor=actor,
                    )
                    if archived:
                        event = {
                            "action": "shadow_retired",
                            "stage_id": stage_id,
                            "override_id": str(shadow.id),
                            "version": shadow.version,
                            "shadow_approve_rate": round(shadow_rate, 3),
                            "active_approve_rate": round(active_rate, 3),
                            "margin": round(active_rate - shadow_rate, 3),
                            "reason": (
                                f"active beat shadow by "
                                f"{active_rate - shadow_rate:.2f} ≥ "
                                f"{SHADOW_RETIRE_MARGIN}"
                            ),
                        }
                        logger.info("[learning][auto-policy] %s", event)
                        await _emit_policy_event(event)
                        # Refresh local view; fall through so we may still
                        # demote a failing active or promote a proposal.
                        shadow = None

    # 1) demote a failing active
    if active and (active.impact_uses or 0) >= AUTO_PROMOTE_MIN_USES:
        rate = _approve_rate(active)
        if rate is not None and (1 - rate) >= AUTO_DEMOTE_MAX_REJECT_RATE:
            archived = await set_override_status(
                db, override_id=str(active.id), status="archived", actor=actor,
            )
            event = {
                "action": "auto_demoted",
                "stage_id": stage_id,
                "override_id": str(active.id),
                "approve_rate": round(rate, 3),
                "uses": active.impact_uses,
                "reason": f"reject_rate ≥ {AUTO_DEMOTE_MAX_REJECT_RATE}",
            }
            logger.info("[learning][auto-policy] %s", event)
            await _emit_policy_event(event)
            # Demotion happened — re-fetch active (segment-scoped) to keep
            # evaluation correct.
            active = await _latest_active_override(
                db, stage_id=stage_id, template=template, complexity=complexity,
            )
            # Fall through so we may promote a waiting proposal next.
            if proposed:
                promoted = await set_override_status(
                    db, override_id=str(proposed.id), status="active", actor=actor,
                )
                if promoted:
                    event2 = {
                        "action": "auto_promoted",
                        "stage_id": stage_id,
                        "override_id": str(proposed.id),
                        "version": proposed.version,
                        "reason": "promoted after auto-demotion of predecessor",
                    }
                    logger.info("[learning][auto-policy] %s", event2)
                    await _emit_policy_event(event2)
                    return {"events": [event, event2]}
            return {"events": [event]}

    # 2) promote a waiting proposal
    if proposed:
        if active is None and bool(proposed.auto_apply):
            promoted = await set_override_status(
                db, override_id=str(proposed.id), status="active", actor=actor,
            )
            if promoted:
                event = {
                    "action": "auto_promoted",
                    "stage_id": stage_id,
                    "override_id": str(proposed.id),
                    "version": proposed.version,
                    "reason": "auto_apply=True and stage had no active override",
                }
                logger.info("[learning][auto-policy] %s", event)
                await _emit_policy_event(event)
                return {"events": [event]}

        if active and (active.impact_uses or 0) >= AUTO_PROMOTE_MIN_USES:
            rate = _approve_rate(active)
            if rate is not None and rate < AUTO_PROMOTE_MIN_APPROVE_RATE:
                promoted = await set_override_status(
                    db, override_id=str(proposed.id), status="active", actor=actor,
                )
                if promoted:
                    event = {
                        "action": "auto_promoted",
                        "stage_id": stage_id,
                        "override_id": str(proposed.id),
                        "version": proposed.version,
                        "predecessor_id": str(active.id),
                        "predecessor_approve_rate": round(rate, 3),
                        "reason": (
                            f"predecessor approve_rate {rate:.2f} "
                            f"< {AUTO_PROMOTE_MIN_APPROVE_RATE}"
                        ),
                    }
                    logger.info("[learning][auto-policy] %s", event)
                    await _emit_policy_event(event)
                    return {"events": [event]}

    return None


async def _emit_policy_event(event: Dict[str, Any]) -> None:
    """Best-effort SSE emission so the UI can surface auto-policy moves live."""
    try:
        from .sse import emit_event
        await emit_event("learning:auto-policy", event)
    except Exception:
        pass


def get_policy_config() -> Dict[str, Any]:
    """Expose the current policy thresholds (read-only, for the UI/admin)."""
    return {
        "enabled": _auto_policy_enabled(),
        "min_uses": AUTO_PROMOTE_MIN_USES,
        "min_approve_rate": AUTO_PROMOTE_MIN_APPROVE_RATE,
        "max_reject_rate": AUTO_DEMOTE_MAX_REJECT_RATE,
        "active_cache_ttl": ACTIVE_CACHE_TTL,
        "distill_trigger_threshold": DISTILL_TRIGGER_THRESHOLD,
        "shadow": {
            "traffic_ratio": SHADOW_TRAFFIC_RATIO,
            "min_uses": SHADOW_MIN_USES,
            "graduate_margin": SHADOW_GRADUATE_MARGIN,
            "retire_margin": SHADOW_RETIRE_MARGIN,
        },
    }


# ── Reject Pattern Accumulation → Auto-Skill Creation ─────────────────
# When the same stage accumulates >= REJECT_PATTERN_THRESHOLD reject
# signals with similar feedback, we extract the pattern and create
# a new Skill entry that will be auto-injected on that stage going forward.

REJECT_PATTERN_THRESHOLD = int(os.environ.get("REJECT_PATTERN_THRESHOLD", "3"))


async def check_reject_patterns(db: AsyncSession, *, stage_id: str) -> Optional[Dict[str, Any]]:
    """Check if a stage has accumulated enough similar rejections to auto-create a skill."""
    stmt = (
        select(LearningSignal)
        .where(
            and_(
                LearningSignal.stage_id == stage_id,
                LearningSignal.signal_type == "REJECT",
                LearningSignal.reviewer_feedback.isnot(None),
            )
        )
        .order_by(LearningSignal.created_at.desc())
        .limit(20)
    )
    res = await db.execute(stmt)
    signals = res.scalars().all()

    if len(signals) < REJECT_PATTERN_THRESHOLD:
        return None

    feedback_texts = [s.reviewer_feedback for s in signals if s.reviewer_feedback]
    if len(feedback_texts) < REJECT_PATTERN_THRESHOLD:
        return None

    common_keywords = _extract_common_keywords(feedback_texts)
    if not common_keywords:
        return None

    pattern_id = f"auto-fix-{stage_id}-{'-'.join(common_keywords[:3])}"[:100]

    from ..models.skill import Skill
    existing = await db.get(Skill, pattern_id)
    if existing:
        return {"skill_id": pattern_id, "status": "exists"}

    pattern_desc = f"自动生成的修正技能：在 {stage_id} 阶段，反复被拒绝的原因涉及: {', '.join(common_keywords)}"
    prompt = (
        f"在 {stage_id} 阶段输出时，请特别注意以下常见拒绝原因并确保避免：\n"
        + "\n".join(f"- {fb[:200]}" for fb in feedback_texts[:5])
        + "\n\n请确保产出已针对以上问题做出改进。"
    )

    skill = Skill(
        id=pattern_id,
        name=f"自动修正: {stage_id}",
        category="auto-fix",
        description=pattern_desc,
        version="1.0.0",
        author="learning-loop",
        prompt_template=prompt,
        trigger_stages=[stage_id],
        completion_criteria=[f"避免以下问题: {', '.join(common_keywords)}"],
        execution_mode="inline",
        is_builtin=False,
        enabled=True,
    )
    db.add(skill)
    await db.flush()

    logger.info(
        "[learning] Auto-created skill %s from %d reject signals for stage %s",
        pattern_id, len(feedback_texts), stage_id,
    )

    try:
        from .sse import emit_event
        await emit_event("learning:auto-skill-created", {
            "skillId": pattern_id,
            "stageId": stage_id,
            "keywords": common_keywords,
            "signalCount": len(feedback_texts),
        })
    except Exception:
        pass

    return {"skill_id": pattern_id, "status": "created", "keywords": common_keywords}


def _extract_common_keywords(texts: List[str], min_freq: int = 2) -> List[str]:
    """Extract frequently appearing keywords from a list of feedback texts."""
    word_count: Dict[str, int] = {}
    stop_words = {"的", "了", "是", "在", "和", "有", "不", "这", "个", "中", "to", "the", "is", "a", "an", "and", "or", "not", "be"}
    for text in texts:
        import re
        words = set(re.findall(r'[\u4e00-\u9fa5]{2,}|[a-zA-Z_]{3,}', text.lower()))
        for w in words:
            if w not in stop_words:
                word_count[w] = word_count.get(w, 0) + 1
    return sorted(
        [w for w, c in word_count.items() if c >= min_freq],
        key=lambda w: word_count[w],
        reverse=True,
    )[:10]


# ── Cross-Project Knowledge Accumulation ──────────────────────────────
# Maps task domain to accumulated patterns. Domains are extracted from
# task titles/descriptions at signal capture time using keyword heuristics.
# When a new task enters the pipeline, patterns from the same domain
# are injected into the system prompt automatically.

DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "auth": ["登录", "注册", "认证", "OAuth", "JWT", "login", "signup", "password", "auth", "permission", "权限", "角色", "role"],
    "payment": ["支付", "付款", "交易", "订单", "stripe", "alipay", "wechat", "bill", "invoice", "subscription", "订阅", "缴费"],
    "data": ["数据", "报表", "统计", "分析", "analytics", "report", "dashboard", "chart", "export", "ETL", "pipeline", "埋点", "指标"],
    "communication": ["消息", "通知", "推送", "chat", "notification", "email", "短信", "SMS", "webhook", "message", "邮件", "聊天"],
    "storage": ["存储", "文件", "上传", "upload", "download", "S3", "storage", "blob", "file", "备份", "backup"],
    "ui": ["页面", "组件", "UI", "UX", "前端", "landing", "dashboard", "form", "table", "菜单", "导航", "nav", "layout", "布局"],
    "search": ["搜索", "search", "检索", "index", "elasticsearch", "algolia", "推荐", "recommendation"],
    "deploy": ["部署", "deploy", "CI/CD", "docker", "k8s", "kubernetes", "release", "上线", "运维", "ops"],
}

DOMAIN_PATTERN_STORE_KEY = "learning:domain_patterns"


def _classify_domain(title: str, description: str = "") -> str:
    """Classify a task into a functional domain based on keyword matching."""
    text = f"{title} {description}".lower()
    scores: Dict[str, int] = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw.lower() in text)
        if count > 0:
            scores[domain] = count
    if not scores:
        return "general"
    return max(scores, key=scores.get)


async def capture_domain_signal(
    db: AsyncSession,
    *,
    task_id: str,
    stage_id: str,
    role: str = "",
    signal_type: str,
    severity: str = "info",
    reviewer_feedback: Optional[str] = None,
    task_title: str = "",
    task_description: str = "",
) -> None:
    """Capture a learning signal AND store it in the cross-project domain
    knowledge store so future tasks in the same domain benefit."""
    try:
        domain = _classify_domain(task_title, task_description)
        domain_key = f"{DOMAIN_PATTERN_STORE_KEY}:{domain}:{stage_id}"

        from ..redis_client import cache_get, cache_set
        existing = await cache_get(domain_key)
        patterns: List[Dict[str, Any]] = list(existing) if isinstance(existing, list) else []

        pattern = {
            "task_id": task_id,
            "stage_id": stage_id,
            "role": role,
            "signal_type": signal_type,
            "severity": severity,
            "feedback": (reviewer_feedback or "")[:500],
            "domain": domain,
            "recorded_at": datetime.utcnow().isoformat(),
        }
        patterns.append(pattern)
        # Keep last 20 patterns per domain+stage
        await cache_set(domain_key, patterns[-20:], ttl=86400 * 30)

        logger.debug(
            "[learning][cross-project] domain=%s stage=%s stored pattern (total=%d)",
            domain, stage_id, min(len(patterns), 20),
        )
    except Exception as e:
        logger.debug("[learning][cross-project] capture failed: %s", e)


async def get_domain_addendum(
    db: AsyncSession,
    *,
    task_title: str,
    task_description: str = "",
    stage_id: str,
) -> Optional[str]:
    """Retrieve accumulated cross-project knowledge for the same domain+stage.

    Returns a formatted markdown addendum to inject, or None if no patterns
    exist for this domain yet.
    """
    domain = _classify_domain(task_title, task_description)
    domain_key = f"{DOMAIN_PATTERN_STORE_KEY}:{domain}:{stage_id}"

    try:
        from ..redis_client import cache_get
        patterns = await cache_get(domain_key)
        if not patterns or not isinstance(patterns, list) or not patterns:
            return None

        # Deduplicate by feedback content
        seen = set()
        unique: List[Dict[str, Any]] = []
        for p in patterns:
            fb = (p.get("feedback") or "")[:80]
            if fb and fb not in seen:
                seen.add(fb)
                unique.append(p)

        if not unique:
            return None

        lines = [
            f"## 该 {domain} 领域的注意事项（来自过往任务复盘）",
        ]
        for p in unique[:5]:
            fb = p.get("feedback", "")
            sev = p.get("severity", "info")
            emoji = {"error": "🔴", "warn": "🟡", "info": "🔵"}.get(sev, "⚪")
            lines.append(f"- {emoji} [{p.get('signal_type', '?')}] {fb[:200]}")
        lines.append("")
        lines.append("请针对上述已知问题进行针对性检查，避免历史问题在新任务中重现。")

        return "\n".join(lines)
    except Exception:
        return None
