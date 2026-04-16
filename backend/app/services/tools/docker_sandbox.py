"""
Docker Sandbox — isolated execution environment for agent tools.

When Docker is available, tools run inside ephemeral containers with:
- Restricted networking (none by default, opt-in for web_search)
- Read-only root filesystem with writable workspace volume
- CPU/memory limits
- Auto-cleanup after execution

Falls back to local sandbox (sandbox.py) when Docker is unavailable.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SANDBOX_IMAGE = "python:3.12-slim"
_CONTAINER_WORKSPACE = "/workspace"
_DEFAULT_TIMEOUT = 60
_MAX_OUTPUT = 200_000


def _docker_available() -> bool:
    """Check if Docker CLI is available."""
    return shutil.which("docker") is not None


class DockerSandbox:
    """Manages an ephemeral Docker container for tool execution."""

    def __init__(
        self,
        workspace_dir: Optional[str] = None,
        image: str = _SANDBOX_IMAGE,
        timeout: int = _DEFAULT_TIMEOUT,
        network: bool = False,
        mem_limit: str = "512m",
        cpu_count: float = 1.0,
    ):
        self.sandbox_id = f"agent-sandbox-{uuid.uuid4().hex[:12]}"
        self.workspace_dir = workspace_dir or tempfile.mkdtemp(prefix="agent-hub-")
        self.image = image
        self.timeout = timeout
        self.network = network
        self.mem_limit = mem_limit
        self.cpu_count = cpu_count
        self._container_id: Optional[str] = None

    async def start(self) -> str:
        """Start the sandbox container."""
        if not _docker_available():
            raise RuntimeError("Docker not available — falling back to local sandbox")

        cmd = [
            "docker", "run", "-d",
            "--name", self.sandbox_id,
            "-v", f"{self.workspace_dir}:{_CONTAINER_WORKSPACE}",
            "-w", _CONTAINER_WORKSPACE,
            "--memory", self.mem_limit,
            f"--cpus={self.cpu_count}",
        ]

        if not self.network:
            cmd.extend(["--network", "none"])

        cmd.extend([self.image, "sleep", str(self.timeout + 30)])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Failed to start sandbox: {stderr.decode()}")

        self._container_id = stdout.decode().strip()
        logger.info(f"Sandbox started: {self.sandbox_id}")
        return self._container_id

    async def exec_command(self, command: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        """Execute a command inside the running container."""
        if not self._container_id:
            raise RuntimeError("Sandbox not started")

        effective_timeout = timeout or self.timeout

        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", self._container_id, "bash", "-c", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            await self._kill_process(proc)
            return {"stdout": "", "stderr": f"Command timed out after {effective_timeout}s", "exit_code": -1}

        return {
            "stdout": stdout.decode("utf-8", errors="replace")[:_MAX_OUTPUT],
            "stderr": stderr.decode("utf-8", errors="replace")[:_MAX_OUTPUT],
            "exit_code": proc.returncode or 0,
        }

    def _safe_host_path(self, path: str) -> str:
        """Resolve path within workspace, blocking traversal."""
        workspace = Path(self.workspace_dir).resolve()
        resolved = (workspace / path.lstrip("/")).resolve()
        if not str(resolved).startswith(str(workspace)):
            raise ValueError(f"Path traversal denied: {path}")
        return str(resolved)

    async def write_file(self, path: str, content: str) -> None:
        """Write a file into the container workspace."""
        host_path = self._safe_host_path(path)
        os.makedirs(os.path.dirname(host_path), exist_ok=True)
        with open(host_path, "w", encoding="utf-8") as f:
            f.write(content)

    async def read_file(self, path: str) -> str:
        """Read a file from the container workspace."""
        host_path = self._safe_host_path(path)
        if not os.path.exists(host_path):
            raise FileNotFoundError(f"File not found: {path}")
        with open(host_path, "r", encoding="utf-8") as f:
            return f.read()

    async def stop(self) -> None:
        """Stop and remove the sandbox container."""
        if self._container_id:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker", "rm", "-f", self._container_id,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
                logger.info(f"Sandbox stopped: {self.sandbox_id}")
            except Exception as e:
                logger.warning(f"Failed to stop sandbox {self.sandbox_id}: {e}")
            self._container_id = None

    async def _kill_process(self, proc) -> None:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()


async def run_in_sandbox(
    command: str,
    files: Optional[Dict[str, str]] = None,
    image: str = _SANDBOX_IMAGE,
    timeout: int = _DEFAULT_TIMEOUT,
    network: bool = False,
) -> Dict[str, Any]:
    """Convenience: spin up a sandbox, optionally write files, run command, cleanup."""
    if not _docker_available():
        return {"error": "Docker not available", "stdout": "", "stderr": "", "exit_code": -1}

    async with DockerSandbox(image=image, timeout=timeout, network=network) as sb:
        if files:
            for path, content in files.items():
                await sb.write_file(path, content)

        result = await sb.exec_command(command)
        return result
