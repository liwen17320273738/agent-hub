"""Build tool — run project build commands with log streaming."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional

from .sandbox import get_sandbox_root

logger = logging.getLogger(__name__)

_MAX_OUTPUT = 200_000

BUILD_PRESETS: Dict[str, Dict[str, Any]] = {
    "npm": {
        "install": "npm install",
        "build": "npm run build",
        "dev": "npm run dev",
        "test": "npm test",
    },
    "pnpm": {
        "install": "pnpm install",
        "build": "pnpm run build",
        "dev": "pnpm run dev",
        "test": "pnpm test",
    },
    "pip": {
        "install": "pip install -r requirements.txt",
        "build": "python -m build",
        "test": "python -m pytest",
    },
    "make": {
        "install": "make install",
        "build": "make build",
        "test": "make test",
    },
}

LogCallback = Optional[Callable[[str], Coroutine[Any, Any, None]]]


async def build_project(params: Dict[str, Any], log_callback: LogCallback = None) -> str:
    """Run a build command for a project, optionally streaming logs."""
    project = params.get("project", "")
    command = params.get("command", "")
    preset = params.get("preset", "")
    action = params.get("action", "build")
    timeout = min(params.get("timeout", 300), 600)

    root = get_sandbox_root()
    if project:
        cwd = os.path.join(root, "projects", project)
    else:
        cwd = root

    if not os.path.isdir(cwd):
        return f"Error: Project directory not found: {cwd}"

    if not command:
        if preset and preset in BUILD_PRESETS:
            command = BUILD_PRESETS[preset].get(action, "")
        else:
            command = _detect_build_command(cwd, action)

    if not command:
        return f"Error: No build command found for action '{action}'. Specify 'command' or 'preset'."

    if log_callback:
        await log_callback(f"[build] Running: {command}\n[build] Directory: {cwd}\n")

    started = time.monotonic()
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
    )

    output_lines: List[str] = []
    total_bytes = 0

    try:
        while True:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                output_lines.append(f"\n[build] TIMEOUT after {timeout}s")
                break

            if not line:
                break

            decoded = line.decode("utf-8", errors="replace")
            output_lines.append(decoded)
            total_bytes += len(decoded)

            if log_callback and total_bytes < _MAX_OUTPUT:
                await log_callback(decoded)

            if total_bytes > _MAX_OUTPUT:
                output_lines.append("\n[build] Output truncated...")
                break

        await proc.wait()
    except Exception as e:
        return f"Error: Build failed - {e}"

    elapsed = round(time.monotonic() - started, 1)
    full_output = "".join(output_lines)

    summary = (
        f"\n---\n"
        f"[build] Exit code: {proc.returncode}\n"
        f"[build] Duration: {elapsed}s\n"
        f"[build] Command: {command}"
    )

    return full_output + summary


def _detect_build_command(cwd: str, action: str) -> str:
    """Auto-detect the build system from project files."""
    if os.path.exists(os.path.join(cwd, "package.json")):
        if os.path.exists(os.path.join(cwd, "pnpm-lock.yaml")):
            return BUILD_PRESETS["pnpm"].get(action, "")
        return BUILD_PRESETS["npm"].get(action, "")
    if os.path.exists(os.path.join(cwd, "requirements.txt")):
        return BUILD_PRESETS["pip"].get(action, "")
    if os.path.exists(os.path.join(cwd, "Makefile")):
        return BUILD_PRESETS["make"].get(action, "")
    return ""


async def install_dependencies(params: Dict[str, Any]) -> str:
    """Install project dependencies."""
    params["action"] = "install"
    return await build_project(params)


async def run_tests(params: Dict[str, Any]) -> str:
    """Run project tests."""
    params["action"] = "test"
    return await build_project(params)
