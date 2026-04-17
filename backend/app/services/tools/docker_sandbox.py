"""Docker-based sandbox for risky shell / build operations.

Runs a command inside an ephemeral container with:
- Network locked down (default `--network none`)
- CPU + memory limits
- Read-only root FS, with the per-task workspace mounted RW at `/workspace`
- No SUID, drop all caps, no privilege escalation

If Docker is not available, the caller MUST fall back to the local strict-bash
path. This module never silently runs commands on the host.

Usage:
    if is_docker_available():
        out = await docker_exec(
            command="pip install requests && pytest",
            workspace_dir="/tmp/agent-hub-sandbox/proj-42",
            timeout=600,
        )
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import Dict, Optional

from ...config import settings

logger = logging.getLogger(__name__)

_docker_available_cache: Optional[bool] = None
_image_pulled_cache: Dict[str, bool] = {}

_FALLBACK_IMAGE = "python:3.11-slim"


def _docker_bin() -> Optional[str]:
    return shutil.which("docker")


async def is_docker_available_async() -> bool:
    """Async-safe variant; preferred inside coroutines."""
    global _docker_available_cache
    if _docker_available_cache is not None:
        return _docker_available_cache
    if not _docker_bin():
        _docker_available_cache = False
        return False
    _docker_available_cache = await _docker_info()
    return _docker_available_cache


async def _docker_info() -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            _docker_bin() or "docker", "info",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return False
        return rc == 0
    except Exception as e:
        logger.debug(f"[sandbox] docker info probe failed: {e}")
        return False


async def _ensure_image(image: str) -> str:
    """Try to use `image`; if missing locally and pull fails, fall back to a public slim image."""
    if _image_pulled_cache.get(image):
        return image
    inspect = await asyncio.create_subprocess_exec(
        _docker_bin() or "docker", "image", "inspect", image,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    rc = await inspect.wait()
    if rc == 0:
        _image_pulled_cache[image] = True
        return image
    pull = await asyncio.create_subprocess_exec(
        _docker_bin() or "docker", "pull", image,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        rc = await asyncio.wait_for(pull.wait(), timeout=120)
    except asyncio.TimeoutError:
        pull.kill()
        rc = -1
    if rc == 0:
        _image_pulled_cache[image] = True
        return image
    logger.warning(f"[sandbox] image '{image}' unavailable, falling back to {_FALLBACK_IMAGE}")
    fb_inspect = await asyncio.create_subprocess_exec(
        _docker_bin() or "docker", "image", "inspect", _FALLBACK_IMAGE,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    if (await fb_inspect.wait()) != 0:
        fb_pull = await asyncio.create_subprocess_exec(
            _docker_bin() or "docker", "pull", _FALLBACK_IMAGE,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(fb_pull.wait(), timeout=180)
        except asyncio.TimeoutError:
            fb_pull.kill()
    _image_pulled_cache[_FALLBACK_IMAGE] = True
    return _FALLBACK_IMAGE


async def docker_exec(
    *,
    command: str,
    workspace_dir: str,
    timeout: int = 120,
    env: Optional[Dict[str, str]] = None,
    image: Optional[str] = None,
    network: Optional[str] = None,
    extra_mounts: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    """Run `command` inside a fresh container with the workspace mounted at /workspace.

    Returns: {"ok": bool, "stdout": str, "stderr": str, "exit_code": int, "engine": "docker"}.
    """
    if not _docker_bin():
        return {"ok": False, "stdout": "", "stderr": "docker CLI not on PATH",
                "exit_code": -1, "engine": "docker"}

    os.makedirs(workspace_dir, exist_ok=True)
    image_name = await _ensure_image(image or settings.sandbox_docker_image)
    net = network or settings.sandbox_docker_network or "none"
    timeout = min(int(timeout), int(settings.sandbox_docker_timeout))

    args = [
        _docker_bin() or "docker", "run", "--rm",
        "--network", net,
        "--memory", settings.sandbox_docker_memory,
        "--cpus", settings.sandbox_docker_cpus,
        "--read-only",
        "--tmpfs", "/tmp:rw,size=256m",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "-v", f"{workspace_dir}:/workspace:rw",
        "-w", "/workspace",
    ]
    if extra_mounts:
        for host, container in extra_mounts.items():
            args.extend(["-v", f"{host}:{container}:ro"])
    safe_env = {
        "HOME": "/workspace",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    }
    if env:
        for k, v in env.items():
            if k.upper() in {"PATH", "HOME", "TMPDIR"} or "=" in k:
                continue
            safe_env[k] = str(v)
    for k, v in safe_env.items():
        args.extend(["-e", f"{k}={v}"])
    args.extend([image_name, "sh", "-lc", command])

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"ok": False, "stdout": "", "stderr": f"docker exec timed out after {timeout}s",
                "exit_code": -1, "engine": "docker"}
    return {
        "ok": proc.returncode == 0,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
        "exit_code": proc.returncode if proc.returncode is not None else -1,
        "engine": "docker",
    }
