"""
QaExecutor — Phase 6 real QA executor.

Executes actual commands (install, build, test) and browser smoke tests
in the task worktree. Structured results feed into TaskArtifact pipeline.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────────


@dataclass
class QaCommandResult:
    """Result of a single QA command execution."""
    command: str = ""
    exit_code: int = -1
    stdout_full: str = ""   # complete stdout
    stderr_full: str = ""   # complete stderr
    stdout_summary: str = ""  # first 5 kB (for JSON serialization)
    stderr_summary: str = ""  # first 5 kB (for JSON serialization)
    duration_ms: float = 0.0
    ok: bool = False


@dataclass
class QaExecutionPlan:
    """Commands to execute, extracted from source_manifest or defaults."""
    install_command: str = ""
    build_command: str = ""
    test_command: str = ""
    run_command: str = ""
    preview_port: int = 4173
    preview_url: str = "http://localhost:4173"

    def any_command(self) -> bool:
        return bool(self.install_command or self.build_command or self.test_command)


@dataclass
class QaResourceCheck:
    """Resource availability check result."""
    node_available: bool = False
    pnpm_available: bool = False
    playwright_available: bool = False
    has_source_manifest: bool = False
    all_ok: bool = False
    errors: List[str] = field(default_factory=list)


@dataclass
class QaBrowserResult:
    """Result of browser smoke test."""
    screenshot_path: str = ""
    console_errors: List[str] = field(default_factory=list)
    page_text_preview: str = ""
    page_opened: bool = False
    status_code: int = 0
    error: str = ""


@dataclass
class QaFullResult:
    """Complete QA execution output."""
    resource_check: Dict[str, Any] = field(default_factory=dict)
    install_result: Optional[QaCommandResult] = None
    build_result: Optional[QaCommandResult] = None
    test_result: Optional[QaCommandResult] = None
    browser_result: Optional[QaBrowserResult] = None
    test_log_full: str = ""
    overall_ok: bool = False
    report_markdown: str = ""


# ── Helpers ──────────────────────────────────────────────────────────────


def _which(cmd: str) -> bool:
    """Check if a command is available on PATH."""
    return shutil_which(cmd) is not None


def shutil_which(cmd: str):
    """Wrapper for shutil.which."""
    import shutil
    return shutil.which(cmd)


def _read_source_manifest(project_dir: str) -> Optional[Dict[str, Any]]:
    """Read source_manifest.json from project directory."""
    path = os.path.join(project_dir, "source_manifest.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("[qa_executor] Failed to read source_manifest: %s", e)
        return None


def _extract_plan_from_manifest(manifest: Dict[str, Any]) -> QaExecutionPlan:
    """Extract commands from source_manifest.json."""
    plan = QaExecutionPlan()
    if not manifest:
        return plan
    plan.install_command = (manifest.get("install_command") or "").strip()
    plan.build_command = (manifest.get("build_command") or "").strip()
    plan.test_command = (manifest.get("test_command") or "").strip()
    plan.run_command = (manifest.get("run_command") or "").strip()
    return plan


def _resolve_code_root(project_dir: str) -> str:
    """Locate the directory that holds package.json / source_manifest (may be app/)."""
    if os.path.isfile(os.path.join(project_dir, "source_manifest.json")):
        return project_dir
    for sub in ("app", "code", "frontend"):
        candidate = os.path.join(project_dir, sub)
        if os.path.isfile(os.path.join(candidate, "source_manifest.json")):
            return candidate
    if os.path.isfile(os.path.join(project_dir, "package.json")):
        return project_dir
    for sub in ("app", "code", "frontend"):
        candidate = os.path.join(project_dir, sub)
        if os.path.isfile(os.path.join(candidate, "package.json")):
            return candidate
    return project_dir


def _project_has_test_script(project_dir: str) -> bool:
    pkg_path = os.path.join(project_dir, "package.json")
    if not os.path.isfile(pkg_path):
        return False
    try:
        with open(pkg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        scripts = data.get("scripts") or {}
        return bool(str(scripts.get("test") or "").strip())
    except Exception:
        return False


def _fill_plan_defaults(plan: QaExecutionPlan, project_dir: str) -> QaExecutionPlan:
    """When source_manifest omits test_command, run pnpm test if package.json defines it."""
    if not plan.test_command and _project_has_test_script(project_dir):
        plan.test_command = _default_plan().test_command
    return plan


def _default_plan() -> QaExecutionPlan:
    """Default commands for a typical pnpm project."""
    return QaExecutionPlan(
        install_command="pnpm install",
        build_command="pnpm build",
        test_command="pnpm test",
        run_command="pnpm preview",
    )


# ── QaExecutor ───────────────────────────────────────────────────────────


class QaExecutor:
    """Executes real build/test/browser commands in a project directory."""

    def __init__(self, project_dir: str):
        self.worktree_root = project_dir
        self.project_dir = _resolve_code_root(project_dir)
        self._preview_process: Optional[subprocess.Popen] = None

    # ── Task 6.1: Resource Check ─────────────────────────────────────────

    def check_resources(self) -> QaResourceCheck:
        """Check available tools and source_manifest presence."""
        check = QaResourceCheck()

        manifest = _read_source_manifest(self.project_dir)
        check.has_source_manifest = manifest is not None
        if not manifest:
            check.errors.append("qa_blocked_no_source_manifest")

        check.node_available = _which("node") is not None
        check.pnpm_available = _which("pnpm") is not None
        check.playwright_available = _which("playwright") is not None

        if not check.node_available:
            check.errors.append("node not found on PATH")
        if not check.pnpm_available:
            check.errors.append("pnpm not found on PATH")
        if not check.playwright_available:
            check.errors.append("playwright not found on PATH")

        check.all_ok = (
            check.has_source_manifest
            and check.node_available
            and check.pnpm_available
        )
        return check

    # ── Task 6.2: Command Execution ──────────────────────────────────────

    async def run_command(
        self,
        cmd: str,
        timeout_sec: int = 120,
        cwd: Optional[str] = None,
    ) -> QaCommandResult:
        """Run a single shell command and capture output."""
        start = time.monotonic()
        result = QaCommandResult(command=cmd)

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd or self.project_dir,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout_sec,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                result.exit_code = -1
                result.ok = False
                result.stderr_summary = f"TIMEOUT after {timeout_sec}s"
                result.duration_ms = (time.monotonic() - start) * 1000
                return result

            result.exit_code = proc.returncode or 0
            result.ok = proc.returncode == 0
            result.stdout_full = (stdout.decode("utf-8", errors="replace") or "")
            result.stderr_full = (stderr.decode("utf-8", errors="replace") or "")
            result.stdout_summary = result.stdout_full[:5000]
            result.stderr_summary = result.stderr_full[:5000]
        except Exception as e:
            result.exit_code = -1
            result.ok = False
            result.stderr_summary = str(e)[:5000]

        result.duration_ms = (time.monotonic() - start) * 1000
        return result

    def _write_real_log(self, filename: str, result: QaCommandResult):
        """Write real command stdout/stderr to a log file (overwrites, not appends)."""
        path = os.path.join(self.project_dir, filename)
        try:
            os.makedirs(os.path.dirname(path) or self.project_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# Command: {result.command}\n")
                f.write(f"# Exit code: {result.exit_code}\n")
                f.write(f"# Duration: {result.duration_ms:.0f}ms\n")
                f.write(f"# Timestamp: {datetime.utcnow().isoformat()}Z\n")
                f.write("\n")
                if result.stdout_full:
                    f.write(result.stdout_full)
                if result.stderr_full:
                    f.write("\n# STDERR:\n")
                    f.write(result.stderr_full)
        except Exception as e:
            logger.warning("[qa_executor] Failed to write %s: %s", filename, e)

    async def run_all_commands(self) -> Dict[str, Any]:
        """Run install → build → test sequentially, collect results."""
        manifest = _read_source_manifest(self.project_dir)
        if manifest:
            plan = _fill_plan_defaults(_extract_plan_from_manifest(manifest), self.project_dir)
        else:
            plan = _default_plan()

        results: Dict[str, Any] = {}

        # Step 1: pnpm install
        if plan.install_command:
            logger.info("[qa_executor] Running install: %s", plan.install_command)
            install_result = await self.run_command(plan.install_command, timeout_sec=120)
            results["install"] = asdict(install_result)
            self._write_real_log("install.log", install_result)
            if not install_result.ok:
                results["ok"] = False
                results["failed_step"] = "install"
                results["error"] = f"Install failed: exit={install_result.exit_code}, stderr={install_result.stderr_summary[:500]}"
                return results

        # Step 2: pnpm build
        if plan.build_command:
            logger.info("[qa_executor] Running build: %s", plan.build_command)
            build_result = await self.run_command(plan.build_command, timeout_sec=120)
            results["build"] = asdict(build_result)
            self._write_real_log("qa-build.log", build_result)
            if not build_result.ok:
                results["ok"] = False
                results["failed_step"] = "build"
                results["error"] = f"Build failed: exit={build_result.exit_code}, stderr={build_result.stderr_summary[:500]}"
                return results

        # Step 3: pnpm test
        if plan.test_command:
            logger.info("[qa_executor] Running test: %s", plan.test_command)
            test_result = await self.run_command(plan.test_command, timeout_sec=60)
            results["test"] = asdict(test_result)
            self._write_real_log("test.log", test_result)
            if not test_result.ok:
                results["ok"] = False
                results["failed_step"] = "test"
                results["error"] = f"Test failed: exit={test_result.exit_code}, stderr={test_result.stderr_summary[:500]}"
                return results

        results["ok"] = True
        return results

    # ── Task 6.3: Browser Smoke Test ─────────────────────────────────────

    async def run_browser_smoke(self) -> QaBrowserResult:
        """Start preview server → screenshot → console errors → page text."""
        result = QaBrowserResult()
        manifest = _read_source_manifest(self.project_dir)
        plan = _extract_plan_from_manifest(manifest) if manifest else _default_plan()

        preview_cmd = plan.run_command or "pnpm preview"
        port = plan.preview_port

        # Start preview server in background
        try:
            self._preview_process = subprocess.Popen(
                preview_cmd.split(),
                cwd=self.project_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid,
            )
        except Exception as e:
            result.error = f"Failed to start preview: {e}"
            return result

        # Wait for server to be ready
        import socket
        url = plan.preview_url
        ready = False
        for _ in range(30):  # up to 15s
            await asyncio.sleep(0.5)
            try:
                s = socket.create_connection(("localhost", port), timeout=1)
                s.close()
                ready = True
                break
            except (ConnectionRefusedError, OSError):
                continue

        if not ready:
            self._cleanup_preview()
            result.error = f"Preview server on port {port} not ready after 15s"
            return result

        # Open page with Playwright / stealth_browser
        browser = None
        try:
            from ..services.stealth_browser import StealthBrowser
            browser = StealthBrowser()
            await browser.open(headless=True, viewport="1280x720")
            nav_result = await browser.navigate(url, wait_until="networkidle")

            result.page_opened = nav_result.get("success", False)
            result.status_code = nav_result.get("status", 0)

            if result.page_opened:
                # Screenshot
                ss_dir = os.path.join(self.project_dir, "screenshots")
                os.makedirs(ss_dir, exist_ok=True)
                ss_path = os.path.join(ss_dir, "browser_screenshot.png")
                await browser.screenshot(path=ss_path)
                result.screenshot_path = ss_path

                # Console errors
                try:
                    js_errors = await browser._page.evaluate("() => window.__qa_errors || []")  # noqa
                    if isinstance(js_errors, list):
                        result.console_errors = [str(e)[:1000] for e in js_errors[:50]]
                except Exception:
                    pass

                # Page text
                try:
                    text = await browser.extract_all_text()
                    result.page_text_preview = (text or "")[:2000]
                except Exception:
                    result.page_text_preview = ""
        except Exception as e:
            result.error = f"Browser error: {e}"
            # Still return partial result — screenshot may exist
        finally:
            # Always release the browser + driver, even on error, so chromium
            # does not leak as a zombie process.
            if browser is not None:
                try:
                    await browser.close()
                except Exception as close_err:
                    logger.warning("[qa] browser close failed: %s", close_err)

        self._cleanup_preview()
        return result

    def _cleanup_preview(self):
        """Kill the preview server process."""
        if self._preview_process:
            try:
                pgid = os.getpgid(self._preview_process.pid)
                os.killpg(pgid, signal.SIGTERM)
                self._preview_process.wait(timeout=5)
            except Exception:
                try:
                    self._preview_process.kill()
                except Exception:
                    pass
            self._preview_process = None

    # ── Full QA Run ──────────────────────────────────────────────────────

    async def run_full_qa(self) -> Dict[str, Any]:
        """Execute complete QA pipeline: check → commands → browser.

        Returns structured result dict suitable for pipeline integration.
        """
        # 1. Resource check
        rc = self.check_resources()
        if not rc.all_ok:
            return {
                "ok": False,
                "blocked": True,
                "resource_check": asdict(rc),
                "error": "; ".join(rc.errors),
            }

        # 2. Run commands
        cmd_results = await self.run_all_commands()
        if not cmd_results.get("ok"):
            cmd_results["resource_check"] = asdict(rc)
            return cmd_results

        # 3. Browser smoke test
        browser_result = await self.run_browser_smoke()
        cmd_results["browser"] = asdict(browser_result)
        cmd_results["resource_check"] = asdict(rc)

        # Browser smoke failure is critical: build/test passed but page doesn't render
        if not browser_result.page_opened or browser_result.error:
            cmd_results["ok"] = False
            cmd_results["failed_step"] = "browser_smoke"
            cmd_results["error"] = (
                f"Browser smoke failed: {browser_result.error or 'page not reachable'}"
            )
            return cmd_results

        return cmd_results
