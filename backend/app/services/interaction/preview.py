"""Preview Service — capture screenshots and send to IM channels."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
from typing import Any, Dict, Optional

from ..sse import emit_event

logger = logging.getLogger(__name__)


class PreviewService:
    """Capture web app screenshots and deliver to IM channels."""

    async def capture_screenshot(
        self,
        url: str,
        output_path: str,
        viewport_width: int = 1280,
        viewport_height: int = 800,
        wait_seconds: int = 3,
        full_page: bool = False,
    ) -> Dict[str, Any]:
        """Capture a screenshot of a web page using Puppeteer.

        Falls back gracefully if puppeteer is not installed.
        """
        try:
            check = await asyncio.create_subprocess_exec(
                "node", "-e", "require('puppeteer')",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await check.communicate()
            if check.returncode == 0:
                return await self._capture_with_puppeteer(
                    url, output_path, viewport_width, viewport_height, wait_seconds, full_page,
                )
        except FileNotFoundError:
            pass

        logger.info(f"[preview] puppeteer not available, skipping screenshot for {url}")
        return {
            "ok": True,
            "skipped": True,
            "reason": "puppeteer not installed (optional: npm i -g puppeteer)",
            "previewUrl": url,
        }

    async def _capture_with_puppeteer(
        self,
        url: str,
        output_path: str,
        width: int,
        height: int,
        wait: int,
        full_page: bool,
    ) -> Dict[str, Any]:
        script = f"""
const puppeteer = require('puppeteer');
(async () => {{
    const browser = await puppeteer.launch({{
        headless: 'new',
        args: ['--no-sandbox', '--disable-setuid-sandbox'],
    }});
    const page = await browser.newPage();
    await page.setViewport({{ width: {width}, height: {height} }});
    await page.goto('{url}', {{ waitUntil: 'networkidle0', timeout: 30000 }});
    await new Promise(r => setTimeout(r, {wait * 1000}));
    await page.screenshot({{
        path: '{output_path}',
        fullPage: {str(full_page).lower()},
    }});
    await browser.close();
    console.log(JSON.stringify({{ ok: true, path: '{output_path}' }}));
}})().catch(err => {{
    console.error(JSON.stringify({{ ok: false, error: err.message }}));
    process.exit(1);
}});
"""
        proc = await asyncio.create_subprocess_exec(
            "node", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            return {"ok": False, "error": "Screenshot capture timed out"}

        if proc.returncode != 0:
            return {"ok": False, "error": stderr.decode()[:1000]}

        return {
            "ok": True,
            "path": output_path,
            "exists": os.path.exists(output_path),
        }

    async def screenshot_to_base64(self, path: str) -> Optional[str]:
        """Read a screenshot file and return base64-encoded data."""
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    async def send_preview_to_feishu(
        self,
        task_id: str,
        screenshot_path: str,
        message: str,
        webhook_url: str,
    ) -> Dict[str, Any]:
        """Send a preview screenshot to Feishu via webhook."""
        import httpx

        b64 = await self.screenshot_to_base64(screenshot_path)
        if not b64:
            return {"ok": False, "error": "Screenshot file not found"}

        body = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"预览 — {task_id[:8]}"},
                    "template": "blue",
                },
                "elements": [
                    {"tag": "div", "text": {"tag": "plain_text", "content": message}},
                    {"tag": "img", "img_key": "", "alt": {"tag": "plain_text", "content": "preview"}},
                    {
                        "tag": "action",
                        "actions": [
                            {
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": "✅ 通过"},
                                "type": "primary",
                                "value": {"action": "approve", "task_id": task_id},
                            },
                            {
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": "❌ 需要修改"},
                                "type": "danger",
                                "value": {"action": "reject", "task_id": task_id},
                            },
                        ],
                    },
                ],
            },
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(webhook_url, json=body)
            return {"ok": resp.status_code == 200, "status": resp.status_code}

    async def send_preview_to_qq(
        self,
        task_id: str,
        url: str,
        message: str,
        bot_endpoint: str,
    ) -> Dict[str, Any]:
        """Send preview link to QQ bot."""
        import httpx

        body = {
            "content": f"{message}\n\n🔗 预览链接: {url}\n\n回复「通过」确认上线，回复「修改：xxx」反馈修改意见",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(bot_endpoint, json=body)
            return {"ok": resp.status_code == 200}

    async def capture_and_notify(
        self,
        task_id: str,
        preview_url: str,
        channel: str = "feishu",
        webhook_url: str = "",
        output_dir: str = "/tmp/agent-hub-previews",
    ) -> Dict[str, Any]:
        """Convenience: capture screenshot + send to IM in one call."""
        os.makedirs(output_dir, exist_ok=True)
        screenshot_path = os.path.join(output_dir, f"{task_id}.png")

        capture_result = await self.capture_screenshot(
            url=preview_url,
            output_path=screenshot_path,
        )
        if not capture_result.get("ok"):
            return capture_result

        await emit_event("preview:captured", {
            "taskId": task_id,
            "url": preview_url,
            "screenshotPath": screenshot_path,
        })

        message = f"项目预览已就绪\n\n🔗 {preview_url}"

        if channel == "feishu" and webhook_url:
            return await self.send_preview_to_feishu(
                task_id, screenshot_path, message, webhook_url,
            )

        return {
            "ok": True,
            "screenshotPath": screenshot_path,
            "previewUrl": preview_url,
            "notification": "manual" if not webhook_url else "sent",
        }
