"""Deploy Tracker — monitors deployment and review status across platforms."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..sse import emit_event

logger = logging.getLogger(__name__)


class DeployRecord:
    def __init__(
        self,
        task_id: str,
        platform: str,
        deployment_id: str,
        url: str = "",
    ):
        self.task_id = task_id
        self.platform = platform
        self.deployment_id = deployment_id
        self.url = url
        self.status = "deploying"
        self.created_at = datetime.utcnow().isoformat()
        self.updated_at = self.created_at
        self.review_id: Optional[str] = None
        self.review_status: Optional[str] = None
        self.error: Optional[str] = None
        self.history: List[Dict[str, Any]] = []

    def update_status(self, status: str, **kwargs):
        self.status = status
        self.updated_at = datetime.utcnow().isoformat()
        self.history.append({
            "status": status,
            "timestamp": self.updated_at,
            **kwargs,
        })
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "taskId": self.task_id,
            "platform": self.platform,
            "deploymentId": self.deployment_id,
            "url": self.url,
            "status": self.status,
            "reviewId": self.review_id,
            "reviewStatus": self.review_status,
            "error": self.error,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "history": self.history,
        }


class DeployTracker:
    """Tracks and polls deployment status across all platforms."""

    def __init__(self):
        self._records: Dict[str, DeployRecord] = {}

    def register(
        self,
        task_id: str,
        platform: str,
        deployment_id: str,
        url: str = "",
    ) -> DeployRecord:
        key = f"{task_id}:{platform}"
        record = DeployRecord(task_id, platform, deployment_id, url)
        self._records[key] = record
        return record

    def get_record(self, task_id: str, platform: str) -> Optional[DeployRecord]:
        return self._records.get(f"{task_id}:{platform}")

    def get_all_for_task(self, task_id: str) -> List[DeployRecord]:
        return [r for r in self._records.values() if r.task_id == task_id]

    async def poll_vercel_status(
        self,
        task_id: str,
        deployment_id: str,
        token: str,
        interval: int = 10,
        max_polls: int = 30,
    ):
        """Poll Vercel deployment until ready or failed."""
        from .vercel import get_deployment_status

        record = self.get_record(task_id, "vercel")
        if not record:
            record = self.register(task_id, "vercel", deployment_id)

        for i in range(max_polls):
            result = await get_deployment_status(deployment_id, token)
            if not result.get("ok"):
                await asyncio.sleep(interval)
                continue

            state = result.get("state", "")
            record.update_status(state, url=result.get("url", ""))

            await emit_event("deploy:status", {
                "taskId": task_id,
                "platform": "vercel",
                "state": state,
                "url": result.get("url", ""),
                "poll": i + 1,
            })

            if state in ("READY", "ERROR", "CANCELED"):
                break

            await asyncio.sleep(interval)

    async def poll_wechat_audit(
        self,
        task_id: str,
        audit_id: int,
        app_id: str,
        app_secret: str,
        interval: int = 60,
        max_polls: int = 1440,  # 24 hours at 1min interval
    ):
        """Poll WeChat miniprogram audit status."""
        from .wechat_platform import WeChatPlatformAPI

        record = self.get_record(task_id, "wechat-miniprogram")
        if not record:
            record = self.register(task_id, "wechat-miniprogram", str(audit_id))

        api = WeChatPlatformAPI(app_id, app_secret)
        record.update_status("审核中", review_id=str(audit_id))

        for i in range(max_polls):
            try:
                result = await api.get_audit_status(audit_id)
                status = result.get("status", -1)

                status_map = {0: "审核通过", 1: "审核被拒", 2: "审核中", 3: "已撤回", 4: "审核延后"}
                status_text = status_map.get(status, f"未知状态({status})")
                reason = result.get("reason", "")

                record.update_status(status_text, review_status=status_text)

                await emit_event("deploy:audit-status", {
                    "taskId": task_id,
                    "platform": "wechat-miniprogram",
                    "auditId": audit_id,
                    "status": status_text,
                    "reason": reason,
                })

                if status in (0, 1, 3):
                    if status == 0:
                        release_result = await api.release()
                        record.update_status("已上线" if release_result.get("errcode") == 0 else "发布失败")
                    break

            except Exception as e:
                logger.warning(f"Audit poll error: {e}")

            await asyncio.sleep(interval)

    async def poll_appstore_review(
        self,
        task_id: str,
        app_id: str,
        issuer_id: str,
        key_id: str,
        private_key: str,
        interval: int = 300,
        max_polls: int = 288,  # 24 hours at 5min interval
    ):
        """Poll App Store Connect review status."""
        from .app_store import AppStoreConnect

        record = self.get_record(task_id, "appstore")
        if not record:
            record = self.register(task_id, "appstore", app_id)

        api = AppStoreConnect(issuer_id, key_id, private_key)
        record.update_status("submitted")

        for i in range(max_polls):
            try:
                result = await api.get_review_submission_status(app_id)
                if result.get("ok"):
                    status = result.get("status", "unknown")
                    record.update_status(status, review_status=status)

                    await emit_event("deploy:review-status", {
                        "taskId": task_id,
                        "platform": "appstore",
                        "status": status,
                    })

                    if status in ("COMPLETE", "REJECTED"):
                        break

            except Exception as e:
                logger.warning(f"App Store review poll error: {e}")

            await asyncio.sleep(interval)


deploy_tracker = DeployTracker()
