"""Bash tool — execute shell commands within sandbox constraints."""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict

from .sandbox import get_sandbox_root

_DEFAULT_TIMEOUT = 30
_MAX_OUTPUT_BYTES = 100_000


async def bash_execute(params: Dict[str, Any]) -> str:
    """Execute a bash command within the sandbox directory."""
    command = params.get("command", "")
    if not command:
        return "Error: 'command' parameter is required"

    timeout = min(params.get("timeout", _DEFAULT_TIMEOUT), 120)
    sandbox_root = get_sandbox_root()

    blocked = [
        "rm -rf /", "rm -rf /*", "dd if=", "mkfs", "> /dev/",
        ":(){ :|:", "fork bomb", "chmod -R 777 /", "chown -R",
        "/etc/shadow", "/etc/passwd", "curl.*|.*sh", "wget.*|.*sh",
    ]
    cmd_lower = command.lower()
    for b in blocked:
        if b in cmd_lower:
            return f"Error: Blocked dangerous command pattern: {b}"

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
            cwd=sandbox_root,
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
        parts.append(f"[exit code: {proc.returncode}]")

        return "\n".join(parts)

    except Exception as e:
        return f"Error executing command: {e}"
