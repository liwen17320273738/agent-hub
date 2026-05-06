"""Feedback Loop — process user feedback and trigger Agent iteration (DB-backed)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, desc

from ..sse import emit_event
from ...models.observability import FeedbackRecord
from ...models.pipeline import PipelineTask
from ...database import async_session, async_session_factory

logger = logging.getLogger(__name__)


class FeedbackItem:
    def __init__(
        self,
        task_id: str,
        source: str,
        user_id: str,
        content: str,
        feedback_type: str = "revision",
    ):
        self.id = str(uuid.uuid4())
        self.task_id = task_id
        self.source = source
        self.user_id = user_id
        self.content = content
        self.feedback_type = feedback_type
        self.status = "pending"
        self.created_at = datetime.utcnow().isoformat()
        self.resolved_at: Optional[str] = None
        self.resolution: Optional[str] = None
        self.iteration_count = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "taskId": self.task_id,
            "source": self.source,
            "userId": self.user_id,
            "content": self.content,
            "type": self.feedback_type,
            "status": self.status,
            "createdAt": self.created_at,
            "resolvedAt": self.resolved_at,
            "resolution": self.resolution,
            "iterationCount": self.iteration_count,
        }


async def _persist_feedback(item: FeedbackItem) -> None:
    try:
        async with async_session() as db:
            record = FeedbackRecord(
                feedback_id=item.id,
                task_id=item.task_id,
                source=item.source,
                user_id=item.user_id,
                content=item.content,
                feedback_type=item.feedback_type,
                status=item.status,
                iteration_count=item.iteration_count,
            )
            db.add(record)
            await db.commit()
    except Exception as e:
        logger.warning(f"[feedback] DB persist failed: {e}")


async def _update_feedback_status(
    feedback_id: str,
    status: str,
    resolution: Optional[str] = None,
    iteration_count: int = 0,
) -> None:
    try:
        async with async_session() as db:
            result = await db.execute(
                select(FeedbackRecord).where(FeedbackRecord.feedback_id == feedback_id)
            )
            record = result.scalar_one_or_none()
            if record:
                record.status = status
                if resolution:
                    record.resolution = resolution
                record.iteration_count = iteration_count
                if status == "resolved":
                    record.resolved_at = datetime.utcnow()
                await db.commit()
    except Exception as e:
        logger.warning(f"[feedback] DB update failed: {e}")


class FeedbackLoop:
    """Manages the user feedback → agent iteration cycle (DB-backed)."""

    async def submit_feedback(
        self,
        task_id: str,
        content: str,
        source: str = "api",
        user_id: str = "",
        feedback_type: str = "revision",
    ) -> FeedbackItem:
        """Submit user feedback for a task."""
        item = FeedbackItem(
            task_id=task_id,
            source=source,
            user_id=user_id,
            content=content,
            feedback_type=feedback_type,
        )

        await _persist_feedback(item)

        await emit_event("feedback:submitted", {
            "taskId": task_id,
            "feedbackId": item.id,
            "type": feedback_type,
            "content": content[:200],
        })

        return item

    async def process_feedback(
        self,
        feedback_id: str,
        db=None,
    ) -> Dict[str, Any]:
        """Process feedback and trigger appropriate agent action."""
        item = await self.get_feedback(feedback_id)
        if not item:
            return {"ok": False, "error": "Feedback not found"}

        item.status = "processing"
        item.iteration_count += 1

        await _update_feedback_status(feedback_id, "processing", iteration_count=item.iteration_count)

        await emit_event("feedback:processing", {
            "taskId": item.task_id,
            "feedbackId": item.id,
            "type": item.feedback_type,
            "iteration": item.iteration_count,
        })

        if item.feedback_type == "approve":
            item.status = "resolved"
            item.resolved_at = datetime.utcnow().isoformat()
            item.resolution = "approved_for_deployment"
            await _update_feedback_status(feedback_id, "resolved", "approved_for_deployment", item.iteration_count)
            asyncio.create_task(_apply_feedback_in_background(item, action="approve"))
            return {
                "ok": True,
                "action": "deploy",
                "taskId": item.task_id,
                "message": "User approved — proceeding to deployment",
            }

        if item.feedback_type in ("reject", "revision"):
            stages_to_rerun = self._determine_stages_to_rerun(item.content)
            asyncio.create_task(_apply_feedback_in_background(
                item, action="iterate", stages=stages_to_rerun,
            ))
            return {
                "ok": True,
                "action": "iterate",
                "taskId": item.task_id,
                "stagesToRerun": stages_to_rerun,
                "feedbackContent": item.content,
                "iteration": item.iteration_count,
                "message": f"Re-running stages: {', '.join(stages_to_rerun)}",
            }

        if item.feedback_type == "bug_report":
            asyncio.create_task(_apply_feedback_in_background(
                item, action="fix", stages=["development", "testing"],
            ))
            return {
                "ok": True,
                "action": "fix",
                "taskId": item.task_id,
                "bugDescription": item.content,
                "message": "Bug report received — creating fix task",
            }

        return {"ok": False, "error": f"Unknown feedback type: {item.feedback_type}"}

    def _determine_stages_to_rerun(self, feedback_content: str) -> List[str]:
        """Determine which pipeline stages need to be re-run based on feedback."""
        content_lower = feedback_content.lower()

        stage_keywords = {
            "planning": ["需求", "prd", "功能", "feature", "scope", "范围"],
            "architecture": ["架构", "设计", "技术", "schema", "api", "数据库"],
            "development": ["代码", "bug", "报错", "修复", "实现", "code", "fix"],
            "testing": ["测试", "test", "用例", "边界"],
            "deployment": ["部署", "配置", "deploy", "环境"],
        }

        stages = []
        for stage, keywords in stage_keywords.items():
            if any(kw in content_lower for kw in keywords):
                stages.append(stage)

        if not stages:
            stages = ["development"]

        return stages

    async def get_feedback(self, feedback_id: str) -> Optional[FeedbackItem]:
        """Load a feedback item from DB."""
        try:
            async with async_session() as db:
                result = await db.execute(
                    select(FeedbackRecord).where(FeedbackRecord.feedback_id == feedback_id)
                )
                rec = result.scalar_one_or_none()
                if not rec:
                    return None
                item = FeedbackItem(
                    task_id=rec.task_id,
                    source=rec.source,
                    user_id=rec.user_id,
                    content=rec.content,
                    feedback_type=rec.feedback_type,
                )
                item.id = rec.feedback_id
                item.status = rec.status
                item.iteration_count = rec.iteration_count
                item.resolution = rec.resolution
                item.created_at = rec.created_at.isoformat() if rec.created_at else ""
                item.resolved_at = rec.resolved_at.isoformat() if rec.resolved_at else None
                return item
        except Exception as e:
            logger.warning(f"[feedback] DB load failed: {e}")
            return None

    async def get_task_feedback(self, task_id: str) -> List[FeedbackItem]:
        """Get all feedback items for a task from DB."""
        items: List[FeedbackItem] = []
        try:
            async with async_session() as db:
                result = await db.execute(
                    select(FeedbackRecord)
                    .where(FeedbackRecord.task_id == task_id)
                    .order_by(desc(FeedbackRecord.created_at))
                )
                for rec in result.scalars().all():
                    item = FeedbackItem(
                        task_id=rec.task_id,
                        source=rec.source,
                        user_id=rec.user_id,
                        content=rec.content,
                        feedback_type=rec.feedback_type,
                    )
                    item.id = rec.feedback_id
                    item.status = rec.status
                    item.iteration_count = rec.iteration_count
                    item.resolution = rec.resolution
                    item.created_at = rec.created_at.isoformat() if rec.created_at else ""
                    item.resolved_at = rec.resolved_at.isoformat() if rec.resolved_at else None
                    items.append(item)
        except Exception as e:
            logger.warning(f"[feedback] DB load task feedback failed: {e}")
        return items

    async def parse_im_feedback(
        self,
        task_id: str,
        message: str,
        source: str,
        user_id: str,
    ) -> FeedbackItem:
        """Parse feedback from IM channel messages."""
        msg_lower = message.strip().lower()

        if msg_lower in ("通过", "approve", "ok", "确认", "上线", "lgtm", "approved"):
            return await self.submit_feedback(
                task_id, message, source, user_id, "approve",
            )

        if msg_lower.startswith(("bug", "bug：", "bug:")):
            content = message.split("：", 1)[-1].split(":", 1)[-1].strip() or message
            return await self.submit_feedback(
                task_id, content, source, user_id, "bug_report",
            )

        content = message
        for prefix in ("修改：", "修改:", "改：", "改:", "revision:", "fix:"):
            if msg_lower.startswith(prefix.lower()):
                content = message[len(prefix):].strip()
                break

        return await self.submit_feedback(
            task_id, content, source, user_id, "revision",
        )


feedback_loop = FeedbackLoop()


async def _apply_feedback_in_background(
    item: "FeedbackItem",
    *,
    action: str,
    stages: Optional[List[str]] = None,
) -> None:
    """Spawn the actual iteration / approval work on a fresh DB session.

    Concurrency: only one e2e iteration may run per task at a time.
    Additional feedback that arrives while a run is in progress is queued
    and merged into the next iteration after the current one finishes.

    - approve  → notify completion (no re-run needed).
    - iterate  → merge feedback into description and re-run e2e on the same
                 project_dir; codegen/build/deploy will pick up the changes.
    - fix      → same as iterate but biased toward development/testing stages.
    """
    from ..notify import notify_task_event
    from ..feedback_lock import (
        acquire_lock, release_lock, enqueue_pending, drain_pending,
    )

    task_id = item.task_id
    initial_payload = {
        "feedback_id": item.id,
        "action": action,
        "stages": stages or [],
        "content": item.content,
        "iteration_count": item.iteration_count,
    }

    if action == "approve":
        try:
            async with async_session_factory() as db:
                async with db.begin():
                    task = await db.get(PipelineTask, _to_uuid(task_id))
                    if task is not None:
                        await notify_task_event(
                            task, event="completed",
                            message="用户已确认，结果保留为最终版本",
                        )
            await _update_feedback_status(
                item.id, "resolved", "approved_for_deployment",
                item.iteration_count,
            )
        except Exception as e:
            logger.exception(f"[feedback] approve failed: {e}")
        return

    if not await acquire_lock(task_id, owner=item.id):
        queued = await enqueue_pending(task_id, initial_payload)
        try:
            async with async_session_factory() as db:
                async with db.begin():
                    task = await db.get(PipelineTask, _to_uuid(task_id))
                    if task is not None:
                        await notify_task_event(
                            task, event="feedback_ack",
                            message=f"上一轮还在处理，本次反馈已加入队列（第 {queued} 条）",
                            extras={"动作": action},
                        )
        except Exception as e:
            logger.warning(f"[feedback] queued-notify failed: {e}")
        await emit_event("feedback:queued", {
            "taskId": task_id, "feedbackId": item.id, "queueLength": queued,
        })
        return

    pending: List[Dict[str, Any]] = [initial_payload]
    try:
        while pending:
            await _run_one_iteration(task_id, pending)
            pending = await drain_pending(task_id)
            if pending:
                await emit_event("feedback:drain", {
                    "taskId": task_id, "count": len(pending),
                })
    except Exception as e:
        logger.exception(f"[feedback] background apply failed: {e}")
        try:
            await _update_feedback_status(item.id, "failed", str(e)[:300],
                                          item.iteration_count)
        except Exception:
            pass
    finally:
        await release_lock(task_id, owner=item.id)


async def _run_one_iteration(task_id: str, payloads: List[Dict[str, Any]]) -> None:
    """Run a single e2e pass, merging all queued feedback payloads."""
    from ..e2e_orchestrator import run_full_e2e
    from ..notify import notify_task_event

    primary = payloads[0]
    primary_id = primary["feedback_id"]
    iteration_count = primary.get("iteration_count", 1)
    actions = sorted({p["action"] for p in payloads})
    stages_union: List[str] = []
    for p in payloads:
        for s in (p.get("stages") or []):
            if s not in stages_union:
                stages_union.append(s)

    merged_feedback_lines: List[str] = []
    for p in payloads:
        merged_feedback_lines.append(
            f"- [{p['action']}] {p.get('content', '')}"
        )
    merged_feedback = "\n".join(merged_feedback_lines)

    async with async_session_factory() as db:
        async with db.begin():
            task = await db.get(PipelineTask, _to_uuid(task_id))
            if task is None:
                logger.warning(f"[feedback] task not found for {task_id}")
                return

            await notify_task_event(
                task, event="iterating",
                message=f"已合并 {len(payloads)} 条反馈，开始重新处理",
                extras={"动作": ", ".join(actions), "轮次": iteration_count},
            )

            stage_hint = ", ".join(stages_union)
            merged_description = (
                f"{task.description or ''}\n\n"
                f"## 用户反馈（第 {iteration_count} 轮，{', '.join(actions)}）\n"
                f"{merged_feedback}\n\n"
                f"涉及阶段：{stage_hint or '自动判定'}"
            )

            project_path = task.project_path or ""

            await emit_event("feedback:apply-start", {
                "taskId": task_id,
                "feedbackId": primary_id,
                "actions": actions,
                "stages": stages_union,
                "mergedCount": len(payloads),
            })

            result = await run_full_e2e(
                db,
                task_id=task_id,
                task_title=task.title or "",
                task_description=merged_description,
                auto_deploy=True,
                dag_template="full",
                existing_project_dir=project_path or None,
            )

    final_status = "resolved" if result.get("ok") else "failed"
    for p in payloads:
        try:
            await _update_feedback_status(
                p["feedback_id"], final_status,
                f"{p['action']}: ok={result.get('ok')} url={result.get('url', '')}",
                p.get("iteration_count", 1),
            )
        except Exception as e:
            logger.warning(f"[feedback] update status failed for {p['feedback_id']}: {e}")

    await emit_event("feedback:apply-done", {
        "taskId": task_id,
        "feedbackId": primary_id,
        "ok": result.get("ok"),
        "url": result.get("url", ""),
        "mergedCount": len(payloads),
    })


def _to_uuid(task_id: str):
    try:
        return uuid.UUID(task_id)
    except (ValueError, TypeError):
        return task_id
