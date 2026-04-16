"""Preview Service — capture screenshots and send to IM channels."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
from ipaddress import ip_address
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from ..sse import emit_event

logger = logging.getLogger(__name__)


def _validate_preview_url(url: str) -> None:
    """Block requests to private/internal networks."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported scheme: {parsed.scheme}")
    hostname = parsed.hostname or ""
    if not hostname:
        raise ValueError("Missing hostname")
    try:
        addr = ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
            raise ValueError(f"Blocked private/internal address: {hostname}")
    except ValueError as e:
        if "does not appear to be" not in str(e):
            raise
    blocked_hosts = {"metadata.google.internal", "169.254.169.254"}
    if hostname.lower() in blocked_hosts:
        raise ValueError(f"Blocked metadata endpoint: {hostname}")


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
        _validate_preview_url(url)
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
        import json as _json

        script = """
const puppeteer = require('puppeteer');
const args = JSON.parse(process.argv[1]);
(async () => {
    const browser = await puppeteer.launch({
        headless: 'new',
        args: ['--no-sandbox', '--disable-setuid-sandbox'],
    });
    const page = await browser.newPage();
    await page.setViewport({ width: args.width, height: args.height });
    await page.goto(args.url, { waitUntil: 'networkidle0', timeout: 30000 });
    await new Promise(r => setTimeout(r, args.wait * 1000));
    await page.screenshot({
        path: args.outputPath,
        fullPage: args.fullPage,
    });
    await browser.close();
    console.log(JSON.stringify({ ok: true, path: args.outputPath }));
})().catch(err => {
    console.error(JSON.stringify({ ok: false, error: err.message }));
    process.exit(1);
});
"""
        args_json = _json.dumps({
            "url": url,
            "outputPath": output_path,
            "width": width,
            "height": height,
            "wait": wait,
            "fullPage": full_page,
        })
        proc = await asyncio.create_subprocess_exec(
            "node", "-e", script, args_json,
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
        _validate_preview_url(webhook_url)
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
        _validate_preview_url(bot_endpoint)
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
