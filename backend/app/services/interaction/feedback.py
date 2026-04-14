"""Feedback Loop — process user feedback and trigger Agent iteration."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..sse import emit_event

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
        self.feedback_type = feedback_type  # approve, reject, revision, bug_report
        self.status = "pending"  # pending, processing, resolved
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


class FeedbackLoop:
    """Manages the user feedback → agent iteration cycle."""

    def __init__(self):
        self._items: Dict[str, FeedbackItem] = {}
        self._task_feedback: Dict[str, List[str]] = {}

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
        self._items[item.id] = item
        self._task_feedback.setdefault(task_id, []).append(item.id)

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
        """Process feedback and trigger appropriate agent action.

        For "approve" → proceed to deployment
        For "reject" / "revision" → re-run relevant pipeline stages
        For "bug_report" → create fix task
        """
        item = self._items.get(feedback_id)
        if not item:
            return {"ok": False, "error": "Feedback not found"}

        item.status = "processing"
        item.iteration_count += 1

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
            return {
                "ok": True,
                "action": "deploy",
                "taskId": item.task_id,
                "message": "User approved — proceeding to deployment",
            }

        if item.feedback_type in ("reject", "revision"):
            stages_to_rerun = self._determine_stages_to_rerun(item.content)

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

    def get_feedback(self, feedback_id: str) -> Optional[FeedbackItem]:
        return self._items.get(feedback_id)

    def get_task_feedback(self, task_id: str) -> List[FeedbackItem]:
        ids = self._task_feedback.get(task_id, [])
        return [self._items[fid] for fid in ids if fid in self._items]

    async def parse_im_feedback(
        self,
        task_id: str,
        message: str,
        source: str,
        user_id: str,
    ) -> FeedbackItem:
        """Parse feedback from IM channel messages.

        Convention:
        - "通过" / "approve" / "ok" → approve
        - "修改：xxx" / "改：xxx" → revision
        - "bug：xxx" → bug_report
        - anything else → revision
        """
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
