"""
Gateway API — unified message intake from Feishu, QQ, OpenClaw, and webhooks.

After creating a task, automatically triggers pipeline execution in the background.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets as _secrets
import uuid
from datetime import datetime
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from jose import JWTError

from ..config import settings
from ..database import get_db, async_session_factory
from ..models.pipeline import PipelineTask, PipelineStage
from ..models.user import User
from ..security import decode_token
from ..services.sse import emit_event
from ..services.collaboration import PIPELINE_STAGES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gateway", tags=["gateway"])


def _default_stages():
    return [
        {"stage_id": s["id"], "label": s["label"], "owner_role": s["role"], "sort_order": i}
        for i, s in enumerate(PIPELINE_STAGES)
    ]


async def _session_org_id_from_request(request: Request, db: AsyncSession) -> Optional[uuid.UUID]:
    """Optional JWT in ``X-Agent-Hub-Session: Bearer <jwt>`` (web UI + pipeline key).

    Binds OpenClaw-created tasks to the logged-in user's org so ``GET /pipeline/tasks/{id}``
    with the same JWT does not 404 due to org scoping.
    """
    raw = (request.headers.get("x-agent-hub-session") or "").strip()
    if not raw.lower().startswith("bearer "):
        return None
    token = raw[7:].strip()
    if not token:
        return None
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None
        result = await db.execute(
            select(User).where(User.id == uuid.UUID(str(user_id)), User.is_active.is_(True))
        )
        u = result.scalar_one_or_none()
        return u.org_id if u else None
    except (JWTError, ValueError, TypeError):
        return None


async def _create_task_from_gateway(
    db: AsyncSession,
    title: str,
    description: str,
    source: str,
    source_message_id: str = "",
    source_user_id: str = "",
    org_id: Optional[uuid.UUID] = None,
) -> PipelineTask:
    task = PipelineTask(
        title=title,
        description=description,
        source=source,
        source_message_id=source_message_id or None,
        source_user_id=source_user_id or None,
        created_by="gateway",
        org_id=org_id,
        current_stage_id="planning",
    )
    db.add(task)
    await db.flush()

    for stage_data in _default_stages():
        stage = PipelineStage(task_id=task.id, **stage_data)
        if stage_data["stage_id"] == "planning":
            stage.status = "active"
            stage.started_at = datetime.utcnow()
        db.add(stage)
    await db.flush()

    await emit_event("task:created", {
        "taskId": str(task.id), "title": title, "source": source,
    })

    if source_user_id:
        from ..services.gateway_binding import remember_last_task
        await remember_last_task(source, source_user_id, str(task.id))

    return task


async def _commit_task_before_background(
    db: AsyncSession,
    task: PipelineTask,
) -> PipelineTask:
    """Persist the task row before spawning a background worker.

    FastAPI background tasks may start before the request-scoped `get_db()`
    dependency reaches its post-yield `commit()`. The worker uses a fresh DB
    session, so without an explicit commit it can fail to see the newly created
    `pipeline_tasks` row and trip FK errors when writing checkpoints/artifacts.
    """
    await db.commit()
    await db.refresh(task)
    return task


async def _run_pipeline_background(
    task_id: str,
    title: str,
    description: str,
    *,
    pause_for_acceptance: bool = True,
):
    """Run FULL end-to-end flow: pipeline → codegen → build → deploy → preview.

    Wave 5 / G6: by default IM-originated tasks pause at the
    ``awaiting_final_acceptance`` terminus — the user clicks 接受 / 打回
    in the IM card to publish or rework. Pass ``pause_for_acceptance=False``
    (or ``OpenClawIntakeRequest.auto_final_accept=True``) to keep the old
    auto-publish behaviour for trusted automation.
    """
    from ..services.e2e_orchestrator import run_full_e2e

    try:
        async with async_session_factory() as db:
            result = await run_full_e2e(
                db,
                task_id=task_id,
                task_title=title,
                task_description=description,
                auto_deploy=True,
                dag_template="full",
                pause_for_acceptance=pause_for_acceptance,
            )
            await db.commit()
            phases = {k: v.get("ok", False) for k, v in result.get("phases", {}).items()}
            logger.info(
                f"[gateway] E2E completed for task {task_id}: "
                f"ok={result.get('ok')} url={result.get('url', '')} "
                f"awaiting={result.get('awaitingFinalAcceptance', False)} "
                f"phases={phases}"
            )
    except Exception as e:
        logger.error(f"[gateway] E2E failed for task {task_id}: {e}")


def _should_use_plan_mode(source: str, explicit: Optional[bool] = None) -> bool:
    """Resolve whether this gateway request should pause at the plan stage."""
    if explicit is not None:
        return bool(explicit)
    if not settings.gateway_plan_mode:
        return False
    return (source or "").strip().lower() in ("feishu", "qq", "slack", "openclaw", "api")


def _plan_runtime_options(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract execution-affecting options stored with a pending plan."""
    meta = payload.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    return {
        "auto_final_accept": bool(meta.get("auto_final_accept", False)),
        "source_message_id": str(meta.get("source_message_id") or ""),
        "pending_task_id": str(meta.get("pending_task_id") or ""),
    }


_FEEDBACK_KEYWORDS = (
    "通过", "approve", "ok", "确认", "上线", "lgtm", "approved",
    "改", "修改", "调整", "revision", "fix", "重做",
    "bug", "报错", "崩了", "404", "500", "白屏",
)

# Wave 5 / G5: when a task is at the awaiting_final_acceptance terminus we
# route IM feedback to the dedicated /final-accept | /final-reject APIs
# instead of the (older, intra-stage) feedback_loop. These keyword sets
# decide which verb the natural-language reply maps to.
_FINAL_ACCEPT_KEYWORDS = (
    "通过", "approve", "ok", "确认", "上线", "lgtm", "approved",
    "接受", "accept", "ship", "release", "publish", "好了", "可以",
)
_FINAL_REJECT_KEYWORDS = (
    "改", "修改", "调整", "revision", "fix", "重做", "回炉",
    "reject", "redo", "rework", "退回", "打回", "不行", "不通过",
)


def _classify_final_acceptance_intent(text: str) -> Optional[str]:
    """Return ``'accept'``, ``'reject'``, or ``None`` for an IM reply.

    Reject wins ties — if the user wrote "通过但是要改 X" we treat it as a
    rejection so they don't accidentally publish a not-ready build.
    """
    if not text:
        return None
    lowered = text.strip().lower()
    has_reject = any(kw in lowered for kw in _FINAL_REJECT_KEYWORDS)
    if has_reject:
        return "reject"
    has_accept = any(kw in lowered for kw in _FINAL_ACCEPT_KEYWORDS)
    if has_accept:
        return "accept"
    return None


async def _resolve_feedback_task(
    text: str,
    source: str,
    user_id: str,
) -> tuple[Optional[str], str]:
    """Resolve target task_id for a feedback message.

    Resolution order:
        1. explicit `task:<id>` / `任务：<id>` prefix wins.
        2. otherwise, if message looks like feedback (keyword match) and
           we have a remembered last-task binding for (source, user_id),
           use that.

    Returns (task_id, content) or (None, original_text) if it should be
    treated as a new task.
    """
    import re

    task_match = re.match(r"(?:task|任务)[：:]\s*([a-f0-9-]{8,})\s*[,，\s]*(.*)", text, re.IGNORECASE)
    if task_match:
        return task_match.group(1), task_match.group(2).strip() or "通过"

    lowered = text.strip().lower()
    looks_like_feedback = any(kw in lowered for kw in _FEEDBACK_KEYWORDS)
    if not looks_like_feedback:
        return None, text

    from ..services.gateway_binding import get_last_task
    last_id = await get_last_task(source, user_id)
    if not last_id:
        return None, text
    return last_id, text


async def _try_parse_feedback(
    text: str,
    source: str,
    user_id: str,
) -> Optional[Dict[str, Any]]:
    """Check if message is feedback for an existing task and dispatch it.

    Wave 5 / G5 split: if the resolved task is at ``awaiting_final_acceptance``,
    we route through the new acceptance APIs (publish vs rework-from-stage)
    rather than the older intra-stage feedback loop.
    """
    task_id, content = await _resolve_feedback_task(text, source, user_id)
    if not task_id:
        return None

    # Probe the task's status; if it's parked at the terminus, prefer the
    # acceptance verb-router. We open a fresh session because this is called
    # from the request path before the dispatcher's own session begins.
    try:
        async with async_session_factory() as probe:
            from sqlalchemy import select as _select
            import uuid as _uuid
            row = await probe.execute(
                _select(PipelineTask).where(PipelineTask.id == _uuid.UUID(task_id))
            )
            probe_task = row.scalar_one_or_none()
    except Exception:
        probe_task = None

    if probe_task and probe_task.status == "awaiting_final_acceptance":
        intent = _classify_final_acceptance_intent(content)
        if intent in ("accept", "reject"):
            return await _apply_final_acceptance_from_im(
                task_id=task_id,
                intent=intent,
                source=source,
                user_id=user_id,
                raw_text=content,
            )
        # Unrecognised reply on a parked task — drop a hint instead of
        # silently kicking the old feedback loop (which would have no effect).
        try:
            from ..services.notify import notify_user_text
            await notify_user_text(
                source=source, user_id=user_id,
                title="🤔 没明白你的意思",
                body=(
                    "这个任务正在等你最终验收：\n"
                    "• 回复「通过」或「上线」 → 接受交付\n"
                    "• 回复「重做：原因」 → 打回重做"
                ),
            )
        except Exception:
            pass
        return {
            "ok": True, "action": "final_acceptance_prompt", "taskId": task_id,
        }

    from ..services.interaction.feedback import feedback_loop
    item = await feedback_loop.parse_im_feedback(task_id, content, source, user_id)
    result = await feedback_loop.process_feedback(item.id)
    return {"ok": True, "action": "feedback", "feedbackId": item.id, "taskId": task_id, **result}


async def _apply_final_acceptance_from_im(
    *,
    task_id: str,
    intent: str,
    source: str,
    user_id: str,
    raw_text: str,
) -> Dict[str, Any]:
    """Translate an IM reply into a /final-accept or /final-reject call.

    We replicate the API's side-effects directly (no HTTP hop): mutate the
    PipelineTask row, emit the SSE event, send a confirmation card. For
    rejects we extract the reason after the colon if present (e.g. ``"重做：登录页崩了"``)
    and try to recover a stage hint from a ``@stage:xxx`` token; otherwise
    we just pause for an operator to decide which stage to rerun.
    """
    from datetime import datetime as _dt
    import re as _re
    from sqlalchemy.orm import selectinload as _selectinload
    from sqlalchemy import select as _select
    import uuid as _uuid
    from ..services.notify import notify_user_text

    actor_label = f"im:{source}:{user_id}" if user_id else f"im:{source}"

    async with async_session_factory() as db:
        async with db.begin():
            row = await db.execute(
                _select(PipelineTask)
                .options(_selectinload(PipelineTask.stages))
                .where(PipelineTask.id == _uuid.UUID(task_id))
            )
            task = row.scalar_one_or_none()
            if not task:
                return {"ok": False, "action": "final_acceptance_missing_task", "taskId": task_id}
            if task.status != "awaiting_final_acceptance":
                return {
                    "ok": False, "action": "final_acceptance_state_mismatch",
                    "taskId": task_id, "status": task.status,
                }

            if intent == "accept":
                task.status = "done"
                task.current_stage_id = "done"
                task.final_acceptance_status = "accepted"
                task.final_acceptance_by = actor_label
                task.final_acceptance_at = _dt.utcnow()
                task.final_acceptance_feedback = (raw_text or "").strip()[:500] or None

                await emit_event("pipeline:final-accepted", {
                    "taskId": task_id,
                    "by": actor_label,
                    "via": "im",
                    "notes": (raw_text or "")[:200],
                })

                # Confirm in IM (best effort).
                try:
                    await notify_user_text(
                        source=source, user_id=user_id,
                        title="✅ 已上线",
                        body=f"任务「{task.title}」已通过验收并上线，干得漂亮！",
                    )
                except Exception:
                    pass
                return {
                    "ok": True, "action": "final_accepted_from_im",
                    "taskId": task_id, "by": actor_label,
                }

            # intent == "reject"
            reason = raw_text or ""
            for sep in ("：", ":"):
                if sep in reason:
                    reason = reason.split(sep, 1)[1]
                    break
            reason = (reason or "需要修改").strip()[:1000]

            stage_hint: Optional[str] = None
            m = _re.search(r"@?stage[:：]\s*([a-zA-Z0-9_\-]+)", raw_text)
            if m:
                stage_hint = m.group(1)
                if not any(s.stage_id == stage_hint for s in task.stages):
                    stage_hint = None  # ignore unknown stage hints

            task.final_acceptance_status = "rejected"
            task.final_acceptance_by = actor_label
            task.final_acceptance_at = _dt.utcnow()
            task.final_acceptance_feedback = reason

            if stage_hint:
                target_stage = next(
                    (s for s in task.stages if s.stage_id == stage_hint), None,
                )
                if target_stage:
                    target_order = target_stage.sort_order
                    for s in task.stages:
                        if s.sort_order >= target_order:
                            s.status = "pending"
                            s.completed_at = None
                            if s.stage_id == stage_hint:
                                s.last_error = reason[:1000]
                                if hasattr(s, "reject_feedback"):
                                    s.reject_feedback = (
                                        f"用户在 IM 最终验收阶段打回，要求从此阶段重做：{reason}"
                                    )
                    task.status = "active"
                    task.current_stage_id = stage_hint
            else:
                task.status = "paused"

    await emit_event("pipeline:final-rejected", {
        "taskId": task_id,
        "by": actor_label,
        "via": "im",
        "reason": reason[:500],
        "restartFromStage": stage_hint,
    })

    try:
        if stage_hint:
            await notify_user_text(
                source=source, user_id=user_id,
                title="↩ 已打回",
                body=f"已记下你的反馈，从 {stage_hint} 重新生成。\n原因：{reason[:200]}",
            )
        else:
            await notify_user_text(
                source=source, user_id=user_id,
                title="↩ 已打回",
                body=(
                    f"已记下你的反馈，任务暂停等待操作员决定从哪一步重做。\n"
                    f"原因：{reason[:200]}\n"
                    f"小提示：下次可以加上「@stage:你想重做的阶段」自动从该阶段重跑。"
                ),
            )
    except Exception:
        pass

    return {
        "ok": True, "action": "final_rejected_from_im",
        "taskId": task_id, "by": actor_label,
        "restartFromStage": stage_hint,
    }


async def _clarify_or_create_task(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    *,
    text: str,
    source: str,
    source_user_id: str,
    source_message_id: str,
) -> Dict[str, Any]:
    """Run requirement clarifier; either ask follow-ups or create + dispatch the task.

    Behavior:
      - If user has a pending clarifier session, current message is appended.
      - clarifier.assess() decides if requirement is buildable.
      - Insufficient AND still under MAX_ROUNDS → save session, send questions
        back to the IM channel, do NOT create a task.
      - Sufficient OR MAX_ROUNDS reached → clear session, create task with the
        refined title + description, schedule background pipeline run.

    Returns the JSON body to respond to the webhook with.
    """
    from ..services import clarifier_session
    from ..services.clarifier import assess as clarifier_assess, format_questions_for_im

    session = await clarifier_session.get_session(source, source_user_id) if source_user_id else None
    session = clarifier_session.append_message(session, text)
    asked_count = int(session.get("asked_count") or 0)

    result = await clarifier_assess(list(session.get("messages") or []))

    if not result.sufficient and asked_count < clarifier_session.MAX_ROUNDS:
        session["asked_count"] = asked_count + 1
        session["questions"] = result.questions
        if source_user_id:
            await clarifier_session.save_session(source, source_user_id, session)

        if source_user_id and source in ("feishu", "qq", "slack"):
            from ..services.notify import notify_user_text
            try:
                await notify_user_text(
                    source=source,
                    user_id=source_user_id,
                    title="🤔 需求确认",
                    body=format_questions_for_im(result.questions),
                )
            except Exception as e:
                logger.warning(f"[clarifier] notify_user_text failed: {e}")

        return {
            "ok": True,
            "action": "clarify",
            "questions": result.questions,
            "round": asked_count + 1,
            "rationale": result.rationale,
        }

    if source_user_id:
        await clarifier_session.clear_session(source, source_user_id)

    final_title = (result.refined_title or text[:50] or "未命名任务").strip()
    final_description = (
        result.refined_description
        or clarifier_session.merged_description(session)
        or text
    ).strip()

    # Plan/Act dual-mode: produce a plan and WAIT for user approval.
    if source_user_id and _should_use_plan_mode(source):
        return await _present_plan_and_wait(
            source=source,
            source_user_id=source_user_id,
            title=final_title,
            description=final_description,
            asked_rounds=asked_count + 1,
            rationale=result.rationale,
        )

    task = await _create_task_from_gateway(
        db, final_title, final_description, source,
        source_message_id, source_user_id,
    )
    await _commit_task_before_background(db, task)

    background_tasks.add_task(
        _run_pipeline_background, str(task.id), final_title, final_description,
    )

    return {
        "ok": True,
        "taskId": str(task.id),
        "pipelineTriggered": True,
        "clarifier": {
            "rounds": asked_count + 1,
            "rationale": result.rationale,
        },
    }


# ─────────────────────────────────────────────────────────────────
# Plan/Act dual-mode handlers
# ─────────────────────────────────────────────────────────────────

async def _present_plan_and_wait(
    *,
    source: str,
    source_user_id: str,
    title: str,
    description: str,
    asked_rounds: int = 0,
    rationale: str = "",
    feedback_addendum: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate an execution plan, push it to the user via IM, and persist
    a plan_session waiting for approval.
    """
    from ..services import plan_session
    from ..services.notify import notify_user_text
    from ..services.planner import format_plan_for_im, make_plan

    plan_input_desc = description
    if feedback_addendum:
        plan_input_desc = f"{description}\n\n# 用户反馈（请按此调整）\n{feedback_addendum}"

    plan = await make_plan(title=title, description=plan_input_desc)
    plan_dict = plan.to_dict()
    payload = plan_session.make_payload(title, description, plan_dict, metadata=metadata)
    await plan_session.save_plan(source, source_user_id, payload)

    # Rich interactive card on Feishu (with approve / revise / cancel buttons
    # whose value payload routes back through /gateway/feishu/webhook). For
    # other channels, fall back to the markdown text via notify_user_text so
    # nothing is silently dropped.
    rotation_count = int(payload.get("rotation_count") or 0)
    src_lower = (source or "").lower()
    pushed = False
    if src_lower == "feishu" and source_user_id:
        try:
            from ..services.notify.feishu_im import send_plan_card
            r = await send_plan_card(
                open_id=source_user_id,
                title=title,
                plan=plan_dict,
                source=src_lower,
                user_id=source_user_id,
                rotation_count=rotation_count,
                max_rotations=plan_session.MAX_ROTATIONS,
            )
            pushed = bool(r.get("ok"))
            if not pushed:
                logger.info(f"[plan] feishu plan card not delivered: {r}")
        except Exception as e:
            logger.warning(f"[plan] send_plan_card failed: {e}")
    elif src_lower == "slack" and source_user_id:
        try:
            from ..services.notify.slack import send_plan_card as slack_plan_card
            r = await slack_plan_card(
                receive_id=source_user_id,
                title=title,
                plan=plan_dict,
                source=src_lower,
                user_id=source_user_id,
                rotation_count=rotation_count,
                max_rotations=plan_session.MAX_ROTATIONS,
            )
            pushed = bool(r.get("ok"))
            if not pushed:
                logger.info(f"[plan] slack plan card not delivered: {r}")
        except Exception as e:
            logger.warning(f"[plan] slack send_plan_card failed: {e}")

    if not pushed:
        try:
            await notify_user_text(
                source=source,
                user_id=source_user_id,
                title="📋 待确认计划",
                body=format_plan_for_im(plan),
            )
        except Exception as e:
            logger.warning(f"[plan] notify_user_text failed: {e}")

    return {
        "ok": True,
        "action": "plan_pending",
        "title": title,
        "plan": plan.to_dict(),
        "clarifier": {"rounds": asked_rounds, "rationale": rationale},
    }


async def _try_handle_plan_reply(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    *,
    text: str,
    source: str,
    source_user_id: str,
    source_message_id: str,
) -> Optional[Dict[str, Any]]:
    """If a plan is pending for this user, route this reply through plan flow.

    Returns a response dict (handled) or None (no pending plan, fall through).
    """
    if not source_user_id:
        return None
    from ..services import plan_session
    from ..services.notify import notify_user_text

    pending = await plan_session.load_plan(source, source_user_id)
    if not pending:
        return None

    intent = plan_session.detect_intent(text)
    title = str(pending.get("title") or "")
    description = str(pending.get("description") or "")
    options = _plan_runtime_options(pending)

    if intent["intent"] == "approve":
        await plan_session.clear_plan(source, source_user_id)
        task = None
        pending_task_id = options.get("pending_task_id") or ""
        if pending_task_id:
            try:
                res_pt = await db.execute(
                    select(PipelineTask)
                    .options(selectinload(PipelineTask.stages))
                    .where(PipelineTask.id == uuid.UUID(pending_task_id))
                )
                task = res_pt.scalar_one_or_none()
            except Exception:
                task = None
        if task:
            task.status = "active"
            task.current_stage_id = "planning"
            for stage in sorted(task.stages, key=lambda s: s.sort_order):
                if stage.stage_id == "planning":
                    stage.status = "active"
                    stage.started_at = datetime.utcnow()
                elif stage.status != "done":
                    stage.status = "pending"
                    stage.started_at = None
            await db.flush()
        else:
            task = await _create_task_from_gateway(
                db, title, description, source,
                options.get("source_message_id") or source_message_id,
                source_user_id,
            )
        if options["auto_final_accept"]:
            task.auto_final_accept = True
            await db.flush()
        await _commit_task_before_background(db, task)
        background_tasks.add_task(
            _run_pipeline_background,
            str(task.id),
            title,
            description,
            pause_for_acceptance=not options["auto_final_accept"],
        )
        try:
            await notify_user_text(
                source=source, user_id=source_user_id,
                title="🚀 已开干",
                body=f"任务已启动：{title}\nID: {task.id}\n稍后会汇报阶段进展。",
            )
        except Exception as e:
            logger.debug(f"[plan] approve notify failed: {e}")
        return {
            "ok": True,
            "action": "plan_approved",
            "taskId": str(task.id),
            "pipelineTriggered": True,
        }

    if intent["intent"] == "cancel":
        pending_task_id = options.get("pending_task_id") or ""
        await plan_session.clear_plan(source, source_user_id)
        if pending_task_id:
            try:
                res_can = await db.execute(
                    select(PipelineTask).where(PipelineTask.id == uuid.UUID(pending_task_id))
                )
                t_cancel = res_can.scalar_one_or_none()
                if t_cancel:
                    t_cancel.status = "cancelled"
                    await db.flush()
            except Exception as e:
                logger.debug(f"[plan] IM cancel pending_task_id failed: {e}")
        try:
            await notify_user_text(
                source=source, user_id=source_user_id,
                title="🛑 已取消",
                body="此次计划已丢弃，可以重新发送新需求。",
            )
        except Exception as e:
            logger.debug(f"[plan] cancel notify failed: {e}")
        return {"ok": True, "action": "plan_cancelled"}

    if intent["intent"] == "revise":
        rotation = int(pending.get("rotation_count") or 0)
        if rotation >= plan_session.MAX_ROTATIONS:
            pending_task_id = options.get("pending_task_id") or ""
            await plan_session.clear_plan(source, source_user_id)
            if pending_task_id:
                try:
                    res_mx = await db.execute(
                        select(PipelineTask).where(PipelineTask.id == uuid.UUID(pending_task_id))
                    )
                    t_mx = res_mx.scalar_one_or_none()
                    if t_mx:
                        t_mx.status = "cancelled"
                        await db.flush()
                except Exception:
                    pass
            try:
                await notify_user_text(
                    source=source, user_id=source_user_id,
                    title="❗ 修改次数已用完",
                    body="已达最大调整次数。请重新发送一份完整需求。",
                )
            except Exception:
                pass
            return {"ok": True, "action": "plan_rejected", "reason": "max_rotations"}

        feedback = intent.get("feedback") or text
        meta_rev = pending.get("metadata") if isinstance(pending.get("metadata"), dict) else None
        result = await _present_plan_and_wait(
            source=source,
            source_user_id=source_user_id,
            title=title,
            description=description,
            feedback_addendum=feedback,
            metadata=dict(meta_rev) if meta_rev else None,
        )
        new_pending = await plan_session.load_plan(source, source_user_id)
        if new_pending:
            new_pending["rotation_count"] = rotation + 1
            await plan_session.save_plan(source, source_user_id, new_pending)
        result["rotation_count"] = rotation + 1
        return result

    # Unknown intent — nudge the user, but don't consume the plan.
    try:
        await notify_user_text(
            source=source, user_id=source_user_id,
            title="💡 待你回复",
            body="还有计划等你确认。回复「开干」启动，「修改：xxx」调整，或「取消」放弃。",
        )
    except Exception:
        pass
    return {"ok": True, "action": "plan_waiting"}


async def _handle_plan_card_action(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    card: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Process a plan_approve / plan_revise / plan_reject button click coming
    from a Feishu interactive card. Returns a response dict or None when the
    action isn't recognised.

    For `plan_revise` we can't ask the user inline (Feishu cards don't have
    a free-text input on a button), so we send a follow-up text prompting
    them to reply with `修改：xxx`. The existing `_try_handle_plan_reply`
    will then pick up the next message via the regular message channel.
    """
    from ..services import plan_session
    from ..services.notify import notify_user_text

    action = card.get("action") or ""
    source = (card.get("source") or "feishu").lower()
    user_id = card.get("user_id") or ""
    if not user_id:
        return {"ok": False, "action": "plan_card_invalid", "reason": "no_user_id"}

    # Wave 5 / G4: final-acceptance buttons don't have an associated plan
    # session — they reference a task_id directly. Handle them upfront so
    # we don't fall into the "plan_card_expired" early-return below.
    if action in ("final_accept", "final_reject"):
        target_task_id = str(card.get("task_id") or "").strip()
        if not target_task_id:
            return {"ok": False, "action": f"{action}_invalid", "reason": "no_task_id"}
        intent = "accept" if action == "final_accept" else "reject"
        synth = (
            "[card] 通过" if intent == "accept"
            else "[card] 重做：用户点击了「打回重做」按钮"
        )
        return await _apply_final_acceptance_from_im(
            task_id=target_task_id,
            intent=intent,
            source=source,
            user_id=user_id,
            raw_text=synth,
        )

    pending = await plan_session.load_plan(source, user_id)
    if not pending:
        try:
            await notify_user_text(
                source=source, user_id=user_id,
                title="ℹ️ 计划已失效",
                body="该计划已过期或已被处理，请重新发送需求。",
            )
        except Exception:
            pass
        return {"ok": False, "action": "plan_card_expired"}

    title = str(pending.get("title") or "")
    description = str(pending.get("description") or "")
    options = _plan_runtime_options(pending)

    if action == "plan_approve":
        await plan_session.clear_plan(source, user_id)
        task = await _create_task_from_gateway(
            db,
            title,
            description,
            source,
            options.get("source_message_id") or "",
            user_id,
        )
        if options["auto_final_accept"]:
            task.auto_final_accept = True
            await db.flush()
        await _commit_task_before_background(db, task)
        background_tasks.add_task(
            _run_pipeline_background,
            str(task.id),
            title,
            description,
            pause_for_acceptance=not options["auto_final_accept"],
        )
        try:
            await notify_user_text(
                source=source, user_id=user_id,
                title="🚀 已开干",
                body=f"任务已启动：{title}\nID: {task.id}\n稍后会汇报阶段进展。",
            )
        except Exception:
            pass
        return {
            "ok": True,
            "action": "plan_approved",
            "via": "card",
            "taskId": str(task.id),
            "pipelineTriggered": True,
        }

    if action == "plan_reject":
        await plan_session.clear_plan(source, user_id)
        try:
            await notify_user_text(
                source=source, user_id=user_id,
                title="🛑 已取消",
                body="此次计划已丢弃，可以重新发送新需求。",
            )
        except Exception:
            pass
        return {"ok": True, "action": "plan_cancelled", "via": "card"}

    if action == "plan_revise":
        try:
            await notify_user_text(
                source=source, user_id=user_id,
                title="✎ 请描述如何修改",
                body=(
                    "请直接回复修改要求，例如：\n"
                    "• 把 Vue 换成 React\n"
                    "• 步骤2 拆成两步：先做后端，再做前端\n"
                    "• 砍掉部署，先做 demo\n"
                    "（剩余修改次数："
                    f"{plan_session.MAX_ROTATIONS - int(pending.get('rotation_count') or 0)}）"
                ),
            )
        except Exception:
            pass
        return {"ok": True, "action": "plan_revise_prompt", "via": "card"}

    return None


# --- OpenClaw Gateway ---

class OpenClawIntakeRequest(BaseModel):
    title: str
    description: str = ""
    source: str = "api"
    messageId: str = ""
    userId: str = ""
    planMode: Optional[bool] = None
    # Wave 5 / G6: trusted automation can opt out of the human terminus
    # and let the e2e auto-publish straight after build/test/deploy/preview.
    autoFinalAccept: bool = False


class OpenClawPlanReviseRequest(BaseModel):
    feedback: str


def _extract_gateway_bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    return auth.replace("Bearer ", "").strip() if auth.startswith("Bearer ") else ""


def _require_openclaw_secret(request: Request) -> None:
    secret = settings.pipeline_api_key
    if not secret:
        raise HTTPException(status_code=503, detail="Gateway not configured: PIPELINE_API_KEY is required")
    token = _extract_gateway_bearer(request)
    if not _secrets.compare_digest(token, secret):
        raise HTTPException(status_code=403, detail="Invalid gateway secret")


def _openclaw_plan_links(source: str, user_id: str) -> Dict[str, str]:
    base = f"/api/gateway/openclaw/plans/{source}/{user_id}"
    return {
        "approve": f"{base}/approve",
        "reject": f"{base}/reject",
        "revise": f"{base}/revise",
    }


@router.post("/openclaw/intake")
async def openclaw_intake(
    body: OpenClawIntakeRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    _require_openclaw_secret(request)
    web_org_id = await _session_org_id_from_request(request, db)

    if not body.title.strip():
        raise HTTPException(status_code=400, detail="title is required")

    source = (body.source or "api").strip() or "api"
    use_plan_mode = _should_use_plan_mode(source, body.planMode)
    if use_plan_mode and not body.userId.strip():
        raise HTTPException(status_code=400, detail="userId is required when planMode is enabled")

    if use_plan_mode:
        result = await _present_plan_and_wait(
            source=source,
            source_user_id=body.userId.strip(),
            title=body.title.strip(),
            description=(body.description or body.title).strip(),
            rationale="openclaw_direct",
            metadata={
                "auto_final_accept": bool(body.autoFinalAccept),
                "source_message_id": body.messageId,
            },
        )

        task = await _create_task_from_gateway(
            db,
            body.title.strip(),
            (body.description or body.title).strip(),
            source,
            body.messageId,
            body.userId.strip(),
            org_id=web_org_id,
        )
        task.status = "plan_pending"
        task.current_stage_id = "planning"
        stage_rows = (await db.execute(
            select(PipelineStage).where(PipelineStage.task_id == task.id)
        )).scalars().all()
        for stage in stage_rows:
            stage.status = "awaiting_approval" if stage.stage_id == "planning" else "pending"
            if stage.stage_id != "planning":
                stage.started_at = None
        await db.flush()
        await _commit_task_before_background(db, task)

        from ..services import plan_session
        pending = await plan_session.load_plan(source, body.userId.strip())
        if pending:
            meta = pending.get("metadata") if isinstance(pending.get("metadata"), dict) else {}
            pending["metadata"] = {
                **meta,
                "pending_task_id": str(task.id),
                "auto_final_accept": bool(body.autoFinalAccept),
                "source_message_id": body.messageId,
            }
            await plan_session.save_plan(source, body.userId.strip(), pending)

        fresh = await db.execute(
            select(PipelineTask)
            .options(selectinload(PipelineTask.stages))
            .where(PipelineTask.id == task.id)
        )
        full_task = fresh.scalar_one()

        result["planMode"] = True
        result["autoFinalAccept"] = bool(body.autoFinalAccept)
        result["planSession"] = {
            "source": source,
            "userId": body.userId.strip(),
            "links": _openclaw_plan_links(source, body.userId.strip()),
        }
        result["pipelineTriggered"] = False
        result["taskId"] = str(task.id)
        result["task"] = full_task
        return result

    task = await _create_task_from_gateway(
        db, body.title, body.description, source,
        body.messageId, body.userId,
        org_id=web_org_id,
    )

    if body.autoFinalAccept:
        task.auto_final_accept = True
        await db.flush()

    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages))
        .where(PipelineTask.id == task.id)
    )
    full_task = result.scalar_one()
    await _commit_task_before_background(db, task)

    background_tasks.add_task(
        _run_pipeline_background,
        str(task.id), body.title, body.description,
        pause_for_acceptance=not body.autoFinalAccept,
    )

    return {
        "ok": True, "taskId": str(task.id), "pipelineTriggered": True,
        "planMode": False,
        "autoFinalAccept": bool(body.autoFinalAccept),
        "task": full_task,
    }


@router.get("/openclaw/status")
async def openclaw_status():
    return {"gateway": "openclaw", "status": "online"}


@router.post("/openclaw/plans/{source}/{user_id}/approve")
async def openclaw_approve_plan(
    source: str,
    user_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from ..services import plan_session

    _require_openclaw_secret(request)
    web_org_id = await _session_org_id_from_request(request, db)
    payload = await plan_session.load_plan(source, user_id)
    if not payload:
        raise HTTPException(status_code=404, detail="no pending plan")

    title = str(payload.get("title") or "")
    description = str(payload.get("description") or "")
    if not title:
        raise HTTPException(status_code=400, detail="plan has no title; cannot create task")

    options = _plan_runtime_options(payload)
    await plan_session.clear_plan(source, user_id)
    task = None
    pending_task_id = options.get("pending_task_id") or ""
    if pending_task_id:
        try:
            result = await db.execute(
                select(PipelineTask)
                .options(selectinload(PipelineTask.stages))
                .where(PipelineTask.id == uuid.UUID(pending_task_id))
            )
            task = result.scalar_one_or_none()
        except Exception:
            task = None

    if task:
        if web_org_id and task.org_id is None:
            task.org_id = web_org_id
        task.status = "active"
        task.current_stage_id = "planning"
        for stage in sorted(task.stages, key=lambda s: s.sort_order):
            if stage.stage_id == "planning":
                stage.status = "active"
                stage.started_at = datetime.utcnow()
            elif stage.status != "done":
                stage.status = "pending"
                stage.started_at = None
        await db.flush()
    else:
        task = await _create_task_from_gateway(
            db,
            title,
            description,
            source,
            options.get("source_message_id") or "",
            user_id,
            org_id=web_org_id,
        )
    if options["auto_final_accept"]:
        task.auto_final_accept = True
        await db.flush()
    await _commit_task_before_background(db, task)
    background_tasks.add_task(
        _run_pipeline_background,
        str(task.id),
        title,
        description,
        pause_for_acceptance=not options["auto_final_accept"],
    )
    return {
        "ok": True,
        "action": "plan_approved",
        "taskId": str(task.id),
        "pipelineTriggered": True,
        "autoFinalAccept": options["auto_final_accept"],
    }


@router.post("/openclaw/plans/{source}/{user_id}/reject")
async def openclaw_reject_plan(
    source: str,
    user_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from ..services import plan_session

    _require_openclaw_secret(request)
    payload = await plan_session.load_plan(source, user_id)
    if not payload:
        raise HTTPException(status_code=404, detail="no pending plan")
    options = _plan_runtime_options(payload)
    pending_task_id = options.get("pending_task_id") or ""
    await plan_session.clear_plan(source, user_id)

    if pending_task_id:
        try:
            result = await db.execute(
                select(PipelineTask).where(PipelineTask.id == uuid.UUID(pending_task_id))
            )
            t = result.scalar_one_or_none()
            if t:
                t.status = "cancelled"
                await db.flush()
        except Exception as e:
            logger.debug(f"[openclaw_reject_plan] pending task cancel failed: {e}")

    return {"ok": True, "action": "plan_rejected"}


@router.post("/openclaw/plans/{source}/{user_id}/revise")
async def openclaw_revise_plan(
    source: str,
    user_id: str,
    body: OpenClawPlanReviseRequest,
    request: Request,
):
    from ..services import plan_session

    _require_openclaw_secret(request)
    payload = await plan_session.load_plan(source, user_id)
    if not payload:
        raise HTTPException(status_code=404, detail="no pending plan")

    rotation = int(payload.get("rotation_count") or 0)
    if rotation >= plan_session.MAX_ROTATIONS:
        await plan_session.clear_plan(source, user_id)
        raise HTTPException(
            status_code=400,
            detail=f"max rotations reached ({plan_session.MAX_ROTATIONS}); please re-submit a new requirement",
        )

    title = str(payload.get("title") or "")
    description = str(payload.get("description") or "")
    result = await _present_plan_and_wait(
        source=source,
        source_user_id=user_id,
        title=title,
        description=description,
        feedback_addendum=body.feedback,
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
    )
    new_pending = await plan_session.load_plan(source, user_id)
    if new_pending:
        new_pending["rotation_count"] = rotation + 1
        await plan_session.save_plan(source, user_id, new_pending)
    result["rotation_count"] = rotation + 1
    result["planMode"] = True
    result["planSession"] = {
        "source": source,
        "userId": user_id,
        "links": _openclaw_plan_links(source, user_id),
    }
    result["pipelineTriggered"] = False
    return result


# --- Feishu Webhook (Event v2) ---
#
# Handles three cases:
#   1. `url_verification` challenge — echo `challenge` back ONLY if the
#      `token` matches `feishu_verification_token`.
#   2. AES-encrypted body (`{"encrypt": "..."}`) — decrypt using
#      `feishu_encrypt_key`, then re-process as a normal v2 event.
#   3. Plain v2 message events (`im.message.receive_v1`) — turn into a
#      task or feedback.
#
# Other event types (card.action, member.add, etc.) get a quick 200 OK.


@router.post("/feishu/webhook")
async def feishu_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not settings.feishu_verification_token:
        raise HTTPException(
            status_code=503,
            detail="Feishu webhook not configured: feishu_verification_token is required",
        )

    try:
        raw_body: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    from ..services.feishu_event import (
        normalize_payload, verify_token, is_url_verification,
        extract_message, extract_card_action, FeishuDecryptError,
    )

    try:
        payload = normalize_payload(raw_body)
    except FeishuDecryptError as e:
        logger.warning(f"[feishu] decrypt failed: {e}")
        raise HTTPException(status_code=400, detail=f"Feishu decrypt failed: {e}")

    if not verify_token(payload):
        raise HTTPException(status_code=403, detail="Invalid Feishu verification token")

    if is_url_verification(payload):
        return {"challenge": payload.get("challenge", "")}

    # Interactive-card button clicks (plan approve / revise / cancel buttons).
    # We handle these BEFORE the message branch because card events have no
    # `message` node and would otherwise fall through to "ignored".
    card = extract_card_action(payload)
    if card:
        # _handle_plan_card_action also routes Wave 5 final_accept/final_reject
        # button clicks (G4); the task_id from the button value flows through
        # via the card dict.
        card_response = await _handle_plan_card_action(
            db, background_tasks, card,
        )
        if card_response is not None:
            return card_response
        return {"ok": True, "action": "ignored", "reason": "unknown_card_action"}

    msg = extract_message(payload)
    if not msg:
        return {"ok": True, "action": "ignored", "reason": "non_message_event"}

    text = msg["text"]
    user_id = msg["user_id"]
    message_id = msg["message_id"]
    if not text:
        return {"ok": True, "action": "ignored", "reason": "empty_message"}

    plan_reply = await _try_handle_plan_reply(
        db, background_tasks,
        text=text, source="feishu",
        source_user_id=user_id, source_message_id=message_id,
    )
    if plan_reply:
        return plan_reply

    feedback_result = await _try_parse_feedback(text, "feishu", user_id)
    if feedback_result:
        return feedback_result

    return await _clarify_or_create_task(
        db, background_tasks,
        text=text, source="feishu",
        source_user_id=user_id, source_message_id=message_id,
    )


# --- QQ Webhook (OneBot v11) ---
#
# Receives events from a self-hosted OneBot bridge (NapCat / go-cqhttp /
# Lagrange). The bridge is configured to POST events to /gateway/qq/webhook
# with a shared `access_token` (sent either as `Authorization: Bearer ...`
# OR as `?access_token=...` query string per OneBot v11 spec).
#
# Event schema (relevant subset):
#   { "post_type": "message", "message_type": "private" | "group",
#     "user_id": 123456, "self_id": ..., "message_id": ...,
#     "message": "raw text or array of segments",
#     "raw_message": "plain text fallback",
#     "sender": { "user_id": ..., "nickname": ... },
#     "group_id": ... (only for group)
#   }
#
# Other post_types (meta_event/notice/request) are accepted with a quick
# 200 OK so the bridge doesn't backoff.


def _onebot_extract_text(message: Any) -> str:
    """Extract plain text from OneBot 'message' field (string or segment array)."""
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, list):
        parts: list[str] = []
        for seg in message:
            if not isinstance(seg, dict):
                continue
            if seg.get("type") == "text":
                parts.append(str(seg.get("data", {}).get("text", "")))
            elif seg.get("type") == "at":
                pass  # @somebody — strip
        return "".join(parts).strip()
    return ""


def _onebot_self_at_only(message: Any, self_id: str) -> bool:
    """True when a group message contains nothing but `@bot`."""
    if not isinstance(message, list):
        return False
    text_segs = [s for s in message if isinstance(s, dict) and s.get("type") == "text"]
    has_text = any(str(s.get("data", {}).get("text", "")).strip() for s in text_segs)
    at_self = any(
        s.get("type") == "at" and str(s.get("data", {}).get("qq", "")) == str(self_id)
        for s in message if isinstance(s, dict)
    )
    return at_self and not has_text


@router.post("/qq/webhook")
async def qq_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    secret = settings.qq_bot_access_token or settings.pipeline_api_key
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="QQ webhook not configured: set QQ_BOT_ACCESS_TOKEN or PIPELINE_API_KEY",
        )

    auth_header = request.headers.get("authorization", "")
    header_token = (
        auth_header.replace("Bearer ", "").strip()
        if auth_header.lower().startswith("bearer ") else ""
    )
    query_token = request.query_params.get("access_token", "")
    provided = header_token or query_token
    if not provided or not _secrets.compare_digest(provided, secret):
        raise HTTPException(status_code=403, detail="Invalid OneBot access token")

    try:
        body: Dict[str, Any] = await request.json()
    except Exception:
        return {"ok": True, "action": "ignored", "reason": "invalid_json"}

    post_type = body.get("post_type", "")

    if post_type != "message":
        return {"ok": True, "action": "ignored", "postType": post_type}

    message_type = body.get("message_type", "")
    if message_type not in ("private", "group"):
        return {"ok": True, "action": "ignored", "messageType": message_type}

    self_id = str(body.get("self_id", ""))
    user_id = str(body.get("user_id", "")) or str(
        body.get("sender", {}).get("user_id", "")
    )
    message_id = str(body.get("message_id", ""))
    raw_message = body.get("raw_message", "")

    text = _onebot_extract_text(body.get("message", "")) or str(raw_message or "").strip()
    if not text:
        return {"ok": True, "action": "ignored", "reason": "empty_message"}

    if message_type == "group":
        if _onebot_self_at_only(body.get("message"), self_id):
            return {"ok": True, "action": "ignored", "reason": "at_only"}
        prefix_at = f"[CQ:at,qq={self_id}]"
        if isinstance(raw_message, str) and raw_message.lstrip().startswith(prefix_at):
            text = raw_message.replace(prefix_at, "", 1).strip()

    plan_reply = await _try_handle_plan_reply(
        db, background_tasks,
        text=text, source="qq",
        source_user_id=user_id, source_message_id=message_id,
    )
    if plan_reply:
        return plan_reply

    feedback_result = await _try_parse_feedback(text, "qq", user_id)
    if feedback_result:
        return feedback_result

    return await _clarify_or_create_task(
        db, background_tasks,
        text=text, source="qq",
        source_user_id=user_id, source_message_id=message_id,
    )


# ─────────────────────────────────────────────────────────────────
# Slack webhook (Events API + Interactivity)
# ─────────────────────────────────────────────────────────────────

@router.post("/slack/webhook")
async def slack_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Single endpoint for both Events API events and Interactivity payloads.

    Slack distinguishes them by Content-Type:
      • Events API: `application/json` body with `type=event_callback` /
        `url_verification` / etc.
      • Interactivity: `application/x-www-form-urlencoded` with a single
        `payload=<json>` field.

    Both are signed with the same v0 scheme — verify before parsing.
    """
    from ..services.notify import slack as slack_im

    raw_body = await request.body()
    ts = request.headers.get("x-slack-request-timestamp", "")
    sig = request.headers.get("x-slack-signature", "")

    # Allow unsigned requests only when the signing secret isn't configured
    # (local dev). In all other cases require a valid signature.
    if settings.slack_signing_secret:
        if not slack_im.verify_signature(timestamp=ts, raw_body=raw_body, signature=sig):
            raise HTTPException(status_code=403, detail="Invalid Slack signature")

    content_type = (request.headers.get("content-type") or "").lower()

    if content_type.startswith("application/x-www-form-urlencoded"):
        # Interactivity (button clicks, modals, …)
        from urllib.parse import parse_qs
        import json as _json
        form = parse_qs(raw_body.decode("utf-8"))
        payload_raw = (form.get("payload") or [""])[0]
        try:
            payload = _json.loads(payload_raw)
        except Exception:
            return {"ok": True, "action": "ignored", "reason": "invalid_payload"}

        action = slack_im.extract_card_action(payload)
        if action and (
            action["action"].startswith("plan_")
            or action["action"] in ("final_accept", "final_reject")
        ):
            resp = await _handle_plan_card_action(
                db, background_tasks,
                {
                    "action": action["action"],
                    "source": "slack",
                    "user_id": action["user_id"],
                    # Wave 5 / G4: forward task_id so final_accept/final_reject
                    # buttons can target the right task.
                    "task_id": action.get("task_id") or "",
                },
            )
            # Best-effort acknowledgement back to Slack channel where the
            # button was clicked (response_url is short-lived but free).
            ack = ""
            if resp and resp.get("ok"):
                if resp.get("action") == "plan_approved":
                    ack = "🚀 任务已启动"
                elif resp.get("action") == "plan_cancelled":
                    ack = "🛑 已取消"
                elif resp.get("action") == "plan_revise_prompt":
                    ack = "请回复修改要求"
                elif resp.get("action") == "final_accepted_from_im":
                    ack = "✅ 已接受验收，准备上线"
                elif resp.get("action") == "final_rejected_from_im":
                    ack = "↩ 已打回，等待重新生成"
            elif resp:
                ack = f"❌ 处理失败：{resp.get('reason') or resp.get('action') or 'unknown'}"
            if ack and action.get("response_url"):
                await slack_im.respond_to_action(action["response_url"], ack)
            return resp or {"ok": True, "action": "ignored"}

        return {"ok": True, "action": "ignored", "reason": "unhandled_interactivity"}

    # Events API (or url_verification handshake)
    try:
        body: Dict[str, Any] = await request.json()
    except Exception:
        return {"ok": True, "action": "ignored", "reason": "invalid_json"}

    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    if body.get("type") != "event_callback":
        return {"ok": True, "action": "ignored"}

    event = body.get("event") or {}
    if event.get("type") not in ("message", "app_mention"):
        return {"ok": True, "action": "ignored"}
    if event.get("bot_id") or event.get("subtype") in ("bot_message", "message_changed"):
        return {"ok": True, "action": "ignored", "reason": "bot_or_edit"}

    user_id = str(event.get("user") or "")
    text = str(event.get("text") or "").strip()
    if not user_id or not text:
        return {"ok": True, "action": "ignored", "reason": "empty"}

    # Strip leading bot mention <@U…> when present
    import re as _re
    text = _re.sub(r"^<@[^>]+>\s*", "", text)

    message_id = str(event.get("client_msg_id") or event.get("ts") or "")

    plan_reply = await _try_handle_plan_reply(
        db, background_tasks,
        text=text, source="slack",
        source_user_id=user_id, source_message_id=message_id,
    )
    if plan_reply:
        return plan_reply

    feedback_result = await _try_parse_feedback(text, "slack", user_id)
    if feedback_result:
        return feedback_result

    return await _clarify_or_create_task(
        db, background_tasks,
        text=text, source="slack",
        source_user_id=user_id, source_message_id=message_id,
    )


# ── GitHub Webhook — drive stage transitions from PR/CI events ──────────


@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Receive GitHub webhook events and drive pipeline stage transitions.

    Supported events:
      - ``pull_request`` (opened, closed, merged) → match task by repo+pr
      - ``check_run`` / ``check_suite`` (completed) → update ci_status
      - ``push`` (branch update) → detect branch for pending tasks

    Only processes events that match a task's ``repo_refs``.
    """
    body = await request.body()
    event = request.headers.get("x-github-event", "")
    _ = request.headers.get("x-hub-signature-256", "")
    payload: dict = {}

    try:
        payload = json.loads(body) if isinstance(body, bytes) else json.loads(body.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("[github-webhook] Invalid JSON payload")
        return {"ok": False, "error": "Invalid JSON"}

    logger.info(f"[github-webhook] event={event} repo={payload.get('repository', {}).get('full_name', 'unknown')}")

    repo_full_name = (payload.get("repository") or {}).get("full_name", "")
    if not repo_full_name:
        return {"ok": False, "error": "No repository info"}

    action = payload.get("action", "")

    # ── Build repo ref from event ──────────────────────────────────────
    ref: dict = {"repo": repo_full_name, "branch": "", "pr": 0, "pr_url": "", "ci_status": ""}

    if event == "pull_request":
        pr = payload.get("pull_request") or {}
        pr_number = pr.get("number", 0)
        ref["pr"] = pr_number
        ref["pr_url"] = pr.get("html_url", "")
        ref["branch"] = (pr.get("head") or {}).get("ref", "")
        if action == "closed" and pr.get("merged"):
            ref["ci_status"] = "merged"
        elif action == "opened":
            ref["ci_status"] = "opened"
        else:
            ref["ci_status"] = action

    elif event in ("push",):
        ref["branch"] = (payload.get("ref") or "").replace("refs/heads/", "")
        ref["ci_status"] = "pushed"
        ref["commit_sha"] = (payload.get("head_commit") or {}).get("id", "")[:12] or ""

    elif event in ("check_run",):
        cr = payload.get("check_run") or {}
        ref["branch"] = (cr.get("check_suite") or {}).get("head_branch", "")
        conclusion = cr.get("conclusion", "")
        if conclusion in ("success", "neutral"):
            ref["ci_status"] = "passing"
        elif conclusion in ("failure", "cancelled", "timed_out"):
            ref["ci_status"] = "failing"
        else:
            ref["ci_status"] = conclusion or "pending"

    elif event in ("check_suite",):
        cs = payload.get("check_suite") or {}
        ref["branch"] = cs.get("head_branch", "")
        conclusion = cs.get("conclusion", "")
        if conclusion in ("success", "neutral"):
            ref["ci_status"] = "passing"
        elif conclusion in ("failure", "cancelled", "timed_out"):
            ref["ci_status"] = "failing"
        else:
            ref["ci_status"] = conclusion or "pending"

    # ── Find matching tasks ────────────────────────────────────────────
    from sqlalchemy import select as _select, desc

    result = await db.execute(
        _select(PipelineTask).where(
            PipelineTask.repo_refs.isnot(None),
            PipelineTask.status.in_(["active", "awaiting_final_acceptance"]),
        ).order_by(desc(PipelineTask.created_at)).limit(20)
    )
    tasks = result.scalars().all()

    matched_tasks = []
    for task in tasks:
        refs = task.repo_refs or []
        if not isinstance(refs, list):
            continue
        for existing_ref in refs:
            if not isinstance(existing_ref, dict):
                continue
            if existing_ref.get("repo") != repo_full_name:
                continue
            # Match by PR number or branch
            pr_match = ref.get("pr") and existing_ref.get("pr") == ref["pr"]
            branch_match = ref.get("branch") and existing_ref.get("branch") == ref["branch"]
            if not (pr_match or branch_match):
                continue
            # Update
            existing_ref.update({k: v for k, v in ref.items() if v})
            if ref.get("ci_status"):
                existing_ref["ci_status"] = ref["ci_status"]
            matched_tasks.append(str(task.id))
            break

    if matched_tasks:
        for t in tasks:
            if str(t.id) in matched_tasks:
                db.add(t)
        await db.flush()
        await db.commit()
        logger.info(f"[github-webhook] Updated {len(matched_tasks)} task(s): {matched_tasks}")

    # ── Auto-progress on PR merge ──────────────────────────────────────
    if event == "pull_request" and action == "closed" and ref.get("ci_status") == "merged":
        for t_id in matched_tasks:
            t = await db.get(PipelineTask, t_id)
            if t and t.current_stage_id == "reviewing":
                logger.info(f"[github-webhook] PR merged — auto-advancing task {t_id}")
                # Advance to done if in reviewing
                from datetime import datetime as _dt
                t.status = "done"
                for stage in t.stages:
                    if stage.stage_id == "reviewing":
                        stage.status = "done"
                        stage.completed_at = _dt.utcnow()
                await db.flush()
                await db.commit()

    return {
        "ok": True,
        "event": event,
        "matched_tasks": len(matched_tasks),
        "task_ids": matched_tasks,
    }


# ─────────────────────────────────────────────────────────────────
# WeChat Official Account Webhook
# ─────────────────────────────────────────────────────────────────
#
# Receives messages from WeChat Official Account (公众号).
# 
# GET: 微信服务器配置回调地址时的签名验证
# POST: 用户消息事件（XML格式）
# 
# 微信消息 XML 格式:
#   <xml>
#     <ToUserName><![CDATA[gh_xxx]]></ToUserName>
#     <FromUserName><![CDATA[o_xxx]]></FromUserName>
#     <CreateTime>1234567890</CreateTime>
#     <MsgType><![CDATA[text]]></MsgType>
#     <Content><![CDATA[消息内容]]></Content>
#     <MsgId>1234567890</MsgId>
#   </xml>

_WX_TEXT_REPLY_TMPL = (
    "<xml>"
    "<ToUserName><![CDATA[{to_user}]]></ToUserName>"
    "<FromUserName><![CDATA[{from_user}]]></FromUserName>"
    "<CreateTime>{create_time}</CreateTime>"
    "<MsgType><![CDATA[text]]></MsgType>"
    "<Content><![CDATA[{content}]]></Content>"
    "</xml>"
)

_EMPTY_REPLY = "success"


def _wx_check_signature(signature: str, timestamp: str, nonce: str) -> bool:
    token = settings.wechat_mp_token
    if not token or not signature or not timestamp or not nonce:
        return False
    tmp = "".join(sorted([token, timestamp, nonce]))
    return hashlib.sha1(tmp.encode()).hexdigest() == signature


def _wx_parse_xml(xml: str) -> Dict[str, str]:
    """Simple XML→dict parser for WeChat messages (no extra deps)."""
    import re as _re
    result: Dict[str, str] = {}
    for m in _re.finditer(r'<(\w+)><!\[CDATA\[(.*?)\]\]></\1>', xml, _re.DOTALL):
        result[m.group(1)] = m.group(2)
    if not result:
        for m in _re.finditer(r'<(\w+)>(.*?)</\1>', xml, _re.DOTALL):
            if m.group(1) not in result:
                result[m.group(1)] = m.group(2)
    return result


@router.get("/wechat/webhook")
async def wechat_webhook_verify(
    signature: str = "",
    timestamp: str = "",
    nonce: str = "",
    echostr: str = "",
):
    """微信服务器配置验证（GET 请求）。"""
    if _wx_check_signature(signature, timestamp, nonce):
        return Response(content=echostr or "", media_type="text/plain")
    raise HTTPException(status_code=403, detail="signature check failed")


@router.post("/wechat/webhook")
async def wechat_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    signature: str = "",
    timestamp: str = "",
    nonce: str = "",
):
    """微信公众号消息回调（POST 请求）。"""
    if not _wx_check_signature(signature, timestamp, nonce):
        raise HTTPException(status_code=403, detail="signature check failed")

    try:
        xml_body = await request.body()
        xml_text = xml_body.decode("utf-8")
    except Exception:
        return Response(content=_EMPTY_REPLY, media_type="text/plain")

    msg = _wx_parse_xml(xml_text)
    if not msg:
        return Response(content=_EMPTY_REPLY, media_type="text/plain")

    from_user = msg.get("FromUserName", "")
    to_user = msg.get("ToUserName", "")
    msg_type = msg.get("MsgType", "")

    if msg_type == "text":
        text = (msg.get("Content", "") or "").strip()
        if not text:
            return Response(content=_EMPTY_REPLY, media_type="text/plain")

        feedback_result = await _try_parse_feedback(text, "wechat", from_user)
        if feedback_result:
            return feedback_result

        plan_reply = await _try_handle_plan_reply(
            db, background_tasks,
            text=text, source="wechat", source_user_id=from_user,
            source_message_id=msg.get("MsgId", ""),
        )
        if plan_reply:
            from ..services.notify.wechat_mp import send_text as wx_send
            _ = await wx_send(
                user_id=from_user,
                title="Agent Hub",
                lines=[plan_reply.get("reply", "已收到")],
                task_id="",
            )
            return Response(content=_EMPTY_REPLY, media_type="text/plain")

        result = await _clarify_or_create_task(
            db, background_tasks,
            text=text, source="wechat",
            source_user_id=from_user,
            source_message_id=msg.get("MsgId", ""),
        )

        if result.get("action") in ("task_created", "clarify_sent"):
            return Response(content=_EMPTY_REPLY, media_type="text/plain")

        reply_text = "✅ 需求已接入，AI 军团开始处理"
        reply_xml = _WX_TEXT_REPLY_TMPL.format(
            to_user=from_user,
            from_user=to_user,
            create_time=int(datetime.utcnow().timestamp()),
            content=reply_text,
        )
        return Response(content=reply_xml, media_type="application/xml")

    if msg_type == "event":
        event = msg.get("Event", "")
        if event == "subscribe":
            reply_xml = _WX_TEXT_REPLY_TMPL.format(
                to_user=from_user,
                from_user=to_user,
                create_time=int(datetime.utcnow().timestamp()),
                content=(
                    "👋 欢迎使用 Agent Hub！\n"
                    "直接发送需求，AI 军团将自动处理。\n"
                    "例如：「开发一个 todo 应用」"
                ),
            )
            return Response(content=reply_xml, media_type="application/xml")

    return Response(content=_EMPTY_REPLY, media_type="text/plain")
