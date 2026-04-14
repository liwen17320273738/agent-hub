"""Post-Launch Monitor — health checks and alerting after deployment."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional

import httpx

from ..sse import emit_event

logger = logging.getLogger(__name__)


class HealthCheck:
    def __init__(
        self,
        url: str,
        expected_status: int = 200,
        expected_body_contains: Optional[str] = None,
        timeout: float = 10.0,
    ):
        self.url = url
        self.expected_status = expected_status
        self.expected_body_contains = expected_body_contains
        self.timeout = timeout

    async def check(self) -> Dict[str, Any]:
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(self.url)
                latency_ms = int((time.monotonic() - started) * 1000)

                healthy = resp.status_code == self.expected_status
                if healthy and self.expected_body_contains:
                    healthy = self.expected_body_contains in resp.text

                return {
                    "url": self.url,
                    "healthy": healthy,
                    "statusCode": resp.status_code,
                    "latencyMs": latency_ms,
                    "timestamp": datetime.utcnow().isoformat(),
                }

        except httpx.TimeoutException:
            return {
                "url": self.url,
                "healthy": False,
                "error": "timeout",
                "latencyMs": int((time.monotonic() - started) * 1000),
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            return {
                "url": self.url,
                "healthy": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }


class MonitorRecord:
    def __init__(self, task_id: str, url: str):
        self.task_id = task_id
        self.url = url
        self.started_at = datetime.utcnow().isoformat()
        self.checks: List[Dict[str, Any]] = []
        self.alert_count = 0
        self.consecutive_failures = 0
        self.status = "monitoring"  # monitoring, healthy, degraded, down, stopped

    def add_check(self, result: Dict[str, Any]):
        self.checks.append(result)
        if len(self.checks) > 1000:
            self.checks = self.checks[-500:]

        if result.get("healthy"):
            self.consecutive_failures = 0
            self.status = "healthy"
        else:
            self.consecutive_failures += 1
            if self.consecutive_failures >= 3:
                self.status = "down"
                self.alert_count += 1
            elif self.consecutive_failures >= 1:
                self.status = "degraded"

    def to_dict(self) -> Dict[str, Any]:
        recent = self.checks[-10:] if self.checks else []
        uptime = (
            sum(1 for c in self.checks if c.get("healthy")) / len(self.checks) * 100
            if self.checks else 0
        )
        avg_latency = (
            sum(c.get("latencyMs", 0) for c in self.checks if c.get("healthy"))
            / max(1, sum(1 for c in self.checks if c.get("healthy")))
        )
        return {
            "taskId": self.task_id,
            "url": self.url,
            "status": self.status,
            "startedAt": self.started_at,
            "totalChecks": len(self.checks),
            "uptimePercent": round(uptime, 2),
            "avgLatencyMs": round(avg_latency),
            "consecutiveFailures": self.consecutive_failures,
            "alertCount": self.alert_count,
            "recentChecks": recent,
        }


AlertCallback = Callable[[str, str, Dict[str, Any]], Coroutine[Any, Any, None]]


class PostLaunchMonitor:
    """Monitors deployed services and sends alerts on failure."""

    def __init__(self):
        self._monitors: Dict[str, MonitorRecord] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._alert_callback: Optional[AlertCallback] = None

    def set_alert_callback(self, callback: AlertCallback):
        """Set a callback for alerts (e.g., send to Feishu/QQ)."""
        self._alert_callback = callback

    async def start_monitoring(
        self,
        task_id: str,
        url: str,
        interval: int = 60,
        expected_status: int = 200,
        expected_body_contains: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start monitoring a deployed URL."""
        key = f"{task_id}:{url}"
        if key in self._tasks and not self._tasks[key].done():
            return {"ok": False, "error": "Already monitoring this URL"}

        record = MonitorRecord(task_id, url)
        self._monitors[key] = record

        check = HealthCheck(url, expected_status, expected_body_contains)

        async def _poll():
            while record.status != "stopped":
                result = await check.check()
                record.add_check(result)

                await emit_event("monitor:check", {
                    "taskId": task_id,
                    "url": url,
                    "healthy": result.get("healthy"),
                    "status": record.status,
                    "latencyMs": result.get("latencyMs"),
                })

                if record.status == "down" and self._alert_callback:
                    await self._alert_callback(task_id, url, result)

                await asyncio.sleep(interval)

        task = asyncio.create_task(_poll())
        self._tasks[key] = task

        await emit_event("monitor:started", {
            "taskId": task_id,
            "url": url,
            "interval": interval,
        })

        return {"ok": True, "taskId": task_id, "url": url, "status": "monitoring"}

    async def stop_monitoring(self, task_id: str, url: str) -> Dict[str, Any]:
        """Stop monitoring a URL."""
        key = f"{task_id}:{url}"
        record = self._monitors.get(key)
        if record:
            record.status = "stopped"

        task = self._tasks.get(key)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        return {"ok": True, "message": "Monitoring stopped"}

    def get_status(self, task_id: str) -> List[Dict[str, Any]]:
        """Get all monitoring records for a task."""
        return [
            record.to_dict()
            for key, record in self._monitors.items()
            if record.task_id == task_id
        ]

    def get_all_status(self) -> List[Dict[str, Any]]:
        return [record.to_dict() for record in self._monitors.values()]


post_launch_monitor = PostLaunchMonitor()
