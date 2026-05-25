"""
Local Preview — Phase 7 local deployment closure.

Starts a pnpm preview server, health-checks the URL, takes a screenshot,
and returns structured result for artifact writing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class LocalPreviewResult:
    """Result of a local preview deployment."""
    url: str = ""
    provider: str = "local"
    environment: str = "preview"
    health_status: str = "unknown"  # healthy | unhealthy | unknown
    screenshot_path: str = ""
    deployed_at: str = ""
    error: str = ""
    ok: bool = False
    port_used: int = 4173


def _which(cmd: str) -> Optional[str]:
    import shutil
    return shutil.which(cmd)


def check_local_preview_resources() -> Dict[str, Any]:
    """Check if local preview is feasible."""
    node_ok = _which("node") is not None
    pnpm_ok = _which("pnpm") is not None
    return {
        "node_available": node_ok,
        "pnpm_available": pnpm_ok,
        "local_available": node_ok and pnpm_ok,
    }


def check_vercel_resources() -> Dict[str, Any]:
    """Check if Vercel deployment is feasible."""
    token = os.environ.get("VERCEL_TOKEN", "")
    return {
        "vercel_token_available": bool(token),
        "vercel_available": bool(token),
    }


def check_deploy_resources() -> Dict[str, Any]:
    """Combined deploy resource check."""
    local = check_local_preview_resources()
    vercel = check_vercel_resources()
    return {
        **local,
        **vercel,
        "any_available": local["local_available"] or vercel["vercel_available"],
        "local_preferred": local["local_available"],
        "vercel_preferred": vercel["vercel_available"],
    }


class LocalPreview:
    """Start, health-check, screenshot, and clean up a local preview server."""

    def __init__(self, project_dir: str):
        self.project_dir = project_dir
        self._process: Optional[subprocess.Popen] = None
        self._used_port: int = 4173

    # ── Core preview ──────────────────────────────────────────────────────

    async def deploy(self) -> LocalPreviewResult:
        """Start preview → health check → screenshot → return result.

        Tries port 4173, falls back to 4174, 4175 if occupied.
        """
        result = LocalPreviewResult()
        result.deployed_at = datetime.now(timezone.utc).isoformat()

        # 1. Find free port
        port = self._find_free_port(4173)
        if not port:
            result.error = "No free port available (4173-4175 all occupied)"
            return result

        # 2. Start preview server
        try:
            self._process = subprocess.Popen(
                ["pnpm", "preview", "--port", str(port)],
                cwd=self.project_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid,
            )
        except Exception as e:
            result.error = f"Failed to start preview: {e}"
            return result

        self._used_port = port
        url = f"http://localhost:{port}"
        result.url = url
        result.port_used = port

        # 3. Health check (up to 15s)
        healthy = False
        for _ in range(30):
            await asyncio.sleep(0.5)
            try:
                s = socket.create_connection(("localhost", port), timeout=1)
                s.close()
                healthy = True
                break
            except (ConnectionRefusedError, OSError):
                continue

        if not healthy:
            self._cleanup()
            result.error = f"Preview server on port {port} not healthy after 15s"
            result.health_status = "unhealthy"
            return result

        result.health_status = "healthy"

        # 4. Screenshot via Playwright
        try:
            from ..stealth_browser import StealthBrowser
            browser = StealthBrowser()
            await browser.open(headless=True, viewport="1280x720")
            nav_result = await browser.navigate(url, wait_until="networkidle")

            if nav_result.get("success"):
                ss_dir = os.path.join(self.project_dir, "screenshots")
                os.makedirs(ss_dir, exist_ok=True)
                ss_path = os.path.join(ss_dir, "deployed_screenshot.png")
                await browser.screenshot(path=ss_path)
                result.screenshot_path = ss_path

            await browser.close()
        except Exception as e:
            logger.warning("[local_preview] Screenshot failed (non-fatal): %s", e)

        result.ok = True
        return result

    def _find_free_port(self, start: int, max_tries: int = 3) -> Optional[int]:
        """Find a free port starting from `start`."""
        for port in range(start, start + max_tries):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("localhost", port))
                s.close()
                return port
            except OSError:
                continue
        return None

    def _cleanup(self):
        """Kill the preview server process."""
        if self._process:
            try:
                pgid = os.getpgid(self._process.pid)
                os.killpg(pgid, signal.SIGTERM)
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

    def detach(self):
        """Leave the preview server running after a successful deploy.

        The pipeline returns a clickable local URL as a delivery artifact. If
        we keep owning the process and call ``close()``, that URL becomes dead
        before the user can inspect it.
        """
        self._process = None

    async def close(self):
        self._cleanup()
