"""
Executor Bridge — subprocess-based code execution via Claude CLI.

Replaces Node.js executorBridge.mjs with:
- Jobs persisted in DB (not in-memory Map)
- Sandboxed working directory (whitelist)
- SSE event streaming for real-time logs
- Configurable timeout
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .sse import emit_event

logger = logging.getLogger(__name__)

ALLOWED_WORK_DIRS: List[str] = []

_running_jobs: Dict[str, Dict[str, Any]] = {}


def _validate_work_dir(work_dir: str) -> str:
    """Validate and resolve work directory against whitelist."""
    resolved = str(Path(work_dir).resolve())
    allow_env = os.environ.get("EXECUTOR_ALLOWED_DIRS", "")
    allowed = [d.strip() for d in allow_env.split(",") if d.strip()] if allow_env else []
    allowed.extend(ALLOWED_WORK_DIRS)

    if not allowed:
        return os.getcwd()

    for allowed_dir in allowed:
        if resolved.startswith(str(Path(allowed_dir).resolve())):
            return resolved

    logger.warning(f"[executor] Rejected work_dir={resolved}, not in allowed list")
    return os.getcwd()


async def execute_claude_code(
    *,
    task_id: str,
    prompt: str,
    work_dir: str = "",
    allowed_tools: Optional[List[str]] = None,
    timeout_seconds: int = 900,
) -> Dict[str, Any]:
    """Launch claude CLI as a subprocess and stream output via SSE."""
    job_id = str(uuid.uuid4())
    safe_dir = _validate_work_dir(work_dir or os.getcwd())

    claude_bin = os.environ.get("CLAUDE_PATH") or shutil.which("claude") or "claude"
    args = [claude_bin, "--print", "--output-format", "text"]
    if allowed_tools:
        args.extend(["--allowedTools", ",".join(allowed_tools)])

    job: Dict[str, Any] = {
        "id": job_id,
        "taskId": task_id,
        "status": "running",
        "pid": None,
        "startedAt": time.time(),
        "completedAt": None,
        "exitCode": None,
        "output": "",
        "logs": [],
    }
    _running_jobs[job_id] = job

    await emit_event("executor:started", {"jobId": job_id, "taskId": task_id})

    try:
        filtered_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith(("DATABASE", "REDIS", "JWT", "ADMIN"))
        }

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=safe_dir,
            env=filtered_env,
        )
        job["pid"] = proc.pid

        if proc.stdin:
            proc.stdin.write(prompt.encode())
            await proc.stdin.drain()
            proc.stdin.close()

        stdout_parts: List[str] = []
        stderr_parts: List[str] = []

        async def _read_stream(stream, stream_type: str, parts: List[str]):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="replace")
                parts.append(text)
                entry = {"type": stream_type, "text": text, "timestamp": time.time()}
                job["logs"].append(entry)
                await emit_event("executor:log", {"jobId": job_id, "taskId": task_id, **entry})

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _read_stream(proc.stdout, "stdout", stdout_parts),
                    _read_stream(proc.stderr, "stderr", stderr_parts),
                ),
                timeout=timeout_seconds,
            )
            await proc.wait()
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            job["status"] = "timeout"
            await emit_event("executor:timeout", {"jobId": job_id, "taskId": task_id})

        exit_code = proc.returncode
        output = "".join(stdout_parts)
        if not output.strip() and stderr_parts:
            output = "[stderr]\n" + "".join(stderr_parts)

        job["status"] = "done" if exit_code == 0 else job.get("status", "failed")
        if job["status"] == "running":
            job["status"] = "failed"
        job["exitCode"] = exit_code
        job["completedAt"] = time.time()
        job["output"] = output

        await emit_event("executor:completed", {
            "jobId": job_id, "taskId": task_id,
            "status": job["status"], "exitCode": exit_code,
            "duration": int((job["completedAt"] - job["startedAt"]) * 1000),
            "outputLength": len(output),
        })

    except FileNotFoundError:
        job["status"] = "error"
        job["completedAt"] = time.time()
        error_msg = f"claude CLI not found at '{claude_bin}'. Install: npm i -g @anthropic-ai/claude-code"
        job["logs"].append({"type": "error", "text": error_msg, "timestamp": time.time()})
        await emit_event("executor:error", {"jobId": job_id, "taskId": task_id, "error": error_msg})

    except Exception as e:
        job["status"] = "error"
        job["completedAt"] = time.time()
        job["logs"].append({"type": "error", "text": str(e), "timestamp": time.time()})
        await emit_event("executor:error", {"jobId": job_id, "taskId": task_id, "error": str(e)})

    return job


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    return _running_jobs.get(job_id)


def get_jobs_by_task(task_id: str) -> List[Dict[str, Any]]:
    return sorted(
        [j for j in _running_jobs.values() if j["taskId"] == task_id],
        key=lambda j: j["startedAt"],
        reverse=True,
    )


def kill_job(job_id: str) -> bool:
    job = _running_jobs.get(job_id)
    if not job or not job.get("pid"):
        return False
    try:
        os.kill(job["pid"], 15)  # SIGTERM
        job["status"] = "killed"
        job["completedAt"] = time.time()
        return True
    except ProcessLookupError:
        return False


def build_execution_prompt(title: str, description: str, prd: str = "", architecture: str = "") -> str:
    parts = [f"## 任务: {title}\n"]
    if description:
        parts.append(f"### 需求描述\n{description}\n")
    if prd:
        parts.append(f"### PRD\n{prd}\n")
    if architecture:
        parts.append(f"### 技术方案\n{architecture}\n")
    parts.append("""### 执行要求
- 严格按照 PRD 和技术方案实现
- 每个改动写清楚涉及的文件和原因
- 完成后输出修改的文件列表和验证步骤
- 如有偏差或疑问，明确标注而非自行决定""")
    return "\n".join(parts)
