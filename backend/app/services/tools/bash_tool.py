"""Bash tool — execute shell commands within sandbox constraints.

Two execution modes:
1. **Docker container** (`SANDBOX_USE_DOCKER=true` AND docker available)
   — runs inside a `--network none --read-only --cap-drop ALL` container with
   the per-task workspace mounted at `/workspace`. Host is fully isolated.
2. **Strict subprocess fallback** — runs on host with `cwd=sandbox_root`,
   minimal env, and an aggressive deny-list that blocks common bypasses
   (cd /, fork bombs, base64 piped to shell, /etc/shadow access, …).

NEVER falls back to "loose" execution — if `sandbox_strict_bash` is true and
a command matches a deny pattern, it is rejected with a clear error.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Dict

from ...config import settings
from .docker_sandbox import docker_exec, is_docker_available_async
from .sandbox import get_sandbox_root

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30
_MAX_OUTPUT_BYTES = 100_000

_HARD_BLOCK_PATTERNS = [
    r"\brm\s+-rf?\s+/(?:\s|$|\*)",
    r"\bdd\s+if=",
    r"\bmkfs(\.|\s)",
    r">\s*/dev/(?:sd|nvme|hd|disk|mem|kmem|core)",
    r":\(\)\s*\{\s*:\s*\|\s*:",
    r"\bchmod\s+-R\s+777\s+/(?:\s|$)",
    r"\bchown\s+-R\s+.+\s+/(?:\s|$)",
    r"/etc/shadow",
    r"/etc/sudoers(\.d)?",
    r"\b(curl|wget|fetch)\b[^|;&\n]*\|\s*(sh|bash|zsh|fish|python|perl|node)",
    r"\b(curl|wget)\b[^|;&\n]*\|\s*sudo",
    r"\bbase64\b[^|;&\n]*\|\s*(sh|bash|zsh|python|node)",
    r"\beval\s+\$\(",
    r"\bnohup\b.*&\s*$",
    r"\bcrontab\s+-",
    r":/dev/tcp/",
    r"/proc/self/(mem|maps)",
    r"\bsudo\s+",
    r"\bsu\s+(-|root)",
    r"\biptables\s+",
    r"\bnc\s+-l",
    r"\bncat\s+-l",
    r"\bsocat\b",
    r"\bdocker\s+(run|exec|build)",
    r"\bkubectl\s+",
    r"\bsystemctl\s+",
    r"\bservice\s+\w+\s+(stop|restart|start)",
    r"\bshutdown\b|\breboot\b|\bpoweroff\b|\bhalt\b",
]

_BYPASS_PATTERNS = [
    r"\bcd\s+/(?!workspace|tmp|var/tmp)",
    r"^\s*\.\./",
    r"\$\{?HOME\}?[^a-zA-Z0-9_]?",
]

_COMPILED_HARD = [re.compile(p, re.IGNORECASE) for p in _HARD_BLOCK_PATTERNS]
_COMPILED_BYPASS = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in _BYPASS_PATTERNS]


def _scan(command: str) -> str:
    """Return the offending pattern string if blocked, else empty string."""
    for pat in _COMPILED_HARD:
        if pat.search(command):
            return pat.pattern
    if settings.sandbox_strict_bash:
        for pat in _COMPILED_BYPASS:
            if pat.search(command):
                return pat.pattern
    return ""


async def bash_execute(params: Dict[str, Any]) -> str:
    """Execute a bash command within the sandbox directory."""
    command = params.get("command", "")
    if not command:
        return "Error: 'command' parameter is required"

    raw_timeout = int(params.get("timeout", _DEFAULT_TIMEOUT) or _DEFAULT_TIMEOUT)
    timeout = max(1, min(raw_timeout, int(settings.sandbox_docker_timeout)))

    blocked_pat = _scan(command)
    if blocked_pat:
        logger.warning(f"[bash] Blocked command (pattern: {blocked_pat}): {command[:200]}")
        return (
            f"Error: command blocked by sandbox policy (pattern: {blocked_pat}). "
            "If this is a legitimate operation, escalate via human approval."
        )

    sandbox_root = get_sandbox_root()
    workspace_dir = params.get("workspace_dir") or sandbox_root

    if settings.sandbox_use_docker and await is_docker_available_async():
        try:
            result = await docker_exec(
                command=command,
                workspace_dir=workspace_dir,
                timeout=timeout,
                env=None,
            )
        except Exception as e:
            logger.error(f"[bash] docker_exec raised: {e}; refusing to fall back to host")
            return f"Error: docker execution failed: {e}"
        stdout = (result.get("stdout") or "")[:_MAX_OUTPUT_BYTES]
        stderr = (result.get("stderr") or "")[:_MAX_OUTPUT_BYTES]
        parts = []
        if stdout.strip():
            parts.append(stdout)
        if stderr.strip():
            parts.append(f"[stderr]\n{stderr}")
        parts.append(f"[exit code: {result.get('exit_code', -1)}] [engine: docker]")
        return "\n".join(parts)

    safe_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": sandbox_root,
        "TMPDIR": sandbox_root,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace_dir,
            env=safe_env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"Error: Command timed out after {timeout}s"

        stdout_str = stdout.decode("utf-8", errors="replace")[:_MAX_OUTPUT_BYTES]
        stderr_str = stderr.decode("utf-8", errors="replace")[:_MAX_OUTPUT_BYTES]

        parts = []
        if stdout_str.strip():
            parts.append(stdout_str)
        if stderr_str.strip():
            parts.append(f"[stderr]\n{stderr_str}")
        parts.append(f"[exit code: {proc.returncode}] [engine: subprocess]")

        return "\n".join(parts)

    except Exception as e:
        return f"Error executing command: {e}"
