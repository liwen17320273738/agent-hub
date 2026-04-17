"""
Gateway API — unified message intake from Feishu, QQ, OpenClaw, and webhooks.

After creating a task, automatically triggers pipeline execution in the background.
"""
from __future__ import annotations

import logging
import secrets as _secrets
from datetime import datetime
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from ..config import settings
from ..database import get_db, async_session_factory
from ..models.pipeline import PipelineTask, PipelineStage
from ..services.sse import emit_event
from ..services.collaboration import PIPELINE_STAGES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gateway", tags=["gateway"])


def _default_stages():
    return [
        {"stage_id": s["id"], "label": s["label"], "owner_role": s["role"], "sort_order": i}
        for i, s in enumerate(PIPELINE_STAGES)
    ]


async def _create_task_from_gateway(
    db: AsyncSession,
    title: str,
    description: str,
    source: str,
    source_message_id: str = "",
    source_user_id: str = "",
) -> PipelineTask:
    task = PipelineTask(
        title=title,
        description=description,
        source=source,
        source_message_id=source_message_id or None,
        source_user_id=source_user_id or None,
        created_by="gateway",
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


async def _run_pipeline_background(task_id: str, title: str, description: str):
    """Run FULL end-to-end flow: pipeline → codegen → build → deploy → preview."""
    from ..services.e2e_orchestrator import run_full_e2e

    try:
        async with async_session_factory() as db:
            async with db.begin():
                result = await run_full_e2e(
                    db,
                    task_id=task_id,
                    task_title=title,
                    task_description=description,
                    auto_deploy=True,
                    dag_template="full",
                )
                phases = {k: v.get("ok", False) for k, v in result.get("phases", {}).items()}
                logger.info(
                    f"[gateway] E2E completed for task {task_id}: "
                    f"ok={result.get('ok')} url={result.get('url', '')} phases={phases}"
                )
    except Exception as e:
        logger.error(f"[gateway] E2E failed for task {task_id}: {e}")


_FEEDBACK_KEYWORDS = (
    "通过", "approve", "ok", "确认", "上线", "lgtm", "approved",
    "改", "修改", "调整", "revision", "fix", "重做",
    "bug", "报错", "崩了", "404", "500", "白屏",
)


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
    """Check if message is feedback for an existing task and dispatch it."""
    task_id, content = await _resolve_feedback_task(text, source, user_id)
    if not task_id:
        return None

    from ..services.interaction.feedback import feedback_loop
    item = await feedback_loop.parse_im_feedback(task_id, content, source, user_id)
    result = await feedback_loop.process_feedback(item.id)
    return {"ok": True, "action": "feedback", "feedbackId": item.id, "taskId": task_id, **result}


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

        if source_user_id and source in ("feishu", "qq"):
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
    if settings.gateway_plan_mode and source_user_id and source in ("feishu", "qq"):
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
    payload = plan_session.make_payload(title, description, plan_dict)
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

    if intent["intent"] == "approve":
        await plan_session.clear_plan(source, source_user_id)
        task = await _create_task_from_gateway(
            db, title, description, source,
            source_message_id, source_user_id,
        )
        background_tasks.add_task(
            _run_pipeline_background, str(task.id), title, description,
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
        await plan_session.clear_plan(source, source_user_id)
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
            await plan_session.clear_plan(source, source_user_id)
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
        result = await _present_plan_and_wait(
            source=source,
            source_user_id=source_user_id,
            title=title,
            description=description,
            feedback_addendum=feedback,
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

    if action == "plan_approve":
        await plan_session.clear_plan(source, user_id)
        task = await _create_task_from_gateway(
            db, title, description, source, "", user_id,
        )
        background_tasks.add_task(
            _run_pipeline_background, str(task.id), title, description,
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


@router.post("/openclaw/intake")
async def openclaw_intake(
    body: OpenClawIntakeRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    secret = settings.pipeline_api_key
    if not secret:
        raise HTTPException(status_code=503, detail="Gateway not configured: PIPELINE_API_KEY is required")
    auth = request.headers.get("authorization", "")
    token = auth.replace("Bearer ", "").strip() if auth.startswith("Bearer ") else ""
    if not _secrets.compare_digest(token, secret):
        raise HTTPException(status_code=403, detail="Invalid gateway secret")

    if not body.title.strip():
        raise HTTPException(status_code=400, detail="title is required")

    task = await _create_task_from_gateway(
        db, body.title, body.description, body.source,
        body.messageId, body.userId,
    )

    result = await db.execute(
        select(PipelineTask)
        .options(selectinload(PipelineTask.stages))
        .where(PipelineTask.id == task.id)
    )
    full_task = result.scalar_one()

    background_tasks.add_task(
        _run_pipeline_background, str(task.id), body.title, body.description,
    )

    return {"ok": True, "taskId": str(task.id), "pipelineTriggered": True, "task": full_task}


@router.get("/openclaw/status")
async def openclaw_status():
    return {"gateway": "openclaw", "status": "online"}


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
        if action and action["action"].startswith("plan_"):
            resp = await _handle_plan_card_action(
                db, background_tasks,
                {
                    "action": action["action"],
                    "source": "slack",
                    "user_id": action["user_id"],
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
