"""
Executor Bridge — subprocess-based code execution via Claude CLI.

Job state is persisted in Redis:
- Job metadata: `executor:job:{job_id}` (JSON, 24h TTL)
- Job logs:     `executor:job:{job_id}:logs` (Redis list, 24h TTL)
- Task index:   `executor:task:{task_id}` (Redis set of job IDs, 24h TTL)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..redis_client import get_redis
from .sse import emit_event

logger = logging.getLogger(__name__)

ALLOWED_WORK_DIRS: List[str] = []


def _ensure_sandbox_allowed():
    """Auto-register the sandbox projects directory so codegen can use Claude Code."""
    try:
        from .tools.sandbox import get_sandbox_root
        projects_dir = os.path.join(get_sandbox_root(), "projects")
        if projects_dir not in ALLOWED_WORK_DIRS:
            ALLOWED_WORK_DIRS.append(projects_dir)
    except Exception:
        pass


_ensure_sandbox_allowed()

_JOB_TTL = 86400  # 24 hours


def _job_key(job_id: str) -> str:
    return f"executor:job:{job_id}"


def _logs_key(job_id: str) -> str:
    return f"executor:job:{job_id}:logs"


def _task_index_key(task_id: str) -> str:
    return f"executor:task:{task_id}"


async def _save_job(job: Dict[str, Any]) -> None:
    """Persist job metadata (excluding logs) to Redis with 24h TTL."""
    r = get_redis()
    data = {k: v for k, v in job.items() if k != "logs"}
    await r.setex(_job_key(job["id"]), _JOB_TTL, json.dumps(data, ensure_ascii=False))


async def _append_log(job_id: str, entry: Dict[str, Any]) -> None:
    """Append a log entry to the job's separate log list in Redis."""
    r = get_redis()
    await r.rpush(_logs_key(job_id), json.dumps(entry, ensure_ascii=False))
    await r.expire(_logs_key(job_id), _JOB_TTL)


async def _index_job_to_task(task_id: str, job_id: str) -> None:
    """Register job in the task's index set for lookup by task."""
    r = get_redis()
    await r.sadd(_task_index_key(task_id), job_id)
    await r.expire(_task_index_key(task_id), _JOB_TTL)


def _validate_work_dir(work_dir: str) -> str:
    """Validate and resolve work directory against whitelist.

    Raises ValueError if the directory is not in the allowed list,
    instead of silently falling back to cwd.
    """
    resolved = str(Path(work_dir).resolve())
    allow_env = os.environ.get("EXECUTOR_ALLOWED_DIRS", "")
    allowed = [d.strip() for d in allow_env.split(",") if d.strip()] if allow_env else []
    allowed.extend(ALLOWED_WORK_DIRS)

    if not allowed:
        logger.warning(
            "[executor] No EXECUTOR_ALLOWED_DIRS configured — "
            "falling back to cwd. Set this env var in production."
        )
        return os.getcwd()

    for allowed_dir in allowed:
        if resolved.startswith(str(Path(allowed_dir).resolve())):
            return resolved

    raise ValueError(
        f"Directory {resolved} not in allowed list. "
        f"Allowed: {allowed}"
    )


async def execute_claude_code(
    *,
    task_id: str,
    prompt: str,
    work_dir: str = "",
    allowed_tools: Optional[List[str]] = None,
    timeout_seconds: int = 900,
    created_by: str = "",
) -> Dict[str, Any]:
    """Launch claude CLI as a subprocess and stream output via SSE."""
    job_id = str(uuid.uuid4())
    try:
        safe_dir = _validate_work_dir(work_dir or os.getcwd())
    except ValueError as e:
        return {
            "id": job_id, "taskId": task_id, "status": "error",
            "output": str(e), "startedAt": time.time(), "completedAt": time.time(),
        }

    claude_bin = os.environ.get("CLAUDE_PATH") or shutil.which("claude") or "claude"
    args = [claude_bin, "-p", "--output-format", "text", "--permission-mode", "auto"]
    if allowed_tools:
        args.extend(["--allowedTools", ",".join(allowed_tools)])

    job: Dict[str, Any] = {
        "id": job_id,
        "taskId": task_id,
        "createdBy": created_by,
        "status": "running",
        "pid": None,
        "startedAt": time.time(),
        "completedAt": None,
        "exitCode": None,
        "output": "",
    }
    await _save_job(job)
    await _index_job_to_task(task_id, job_id)

    log_count = 0
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
        await _save_job(job)

        if proc.stdin:
            proc.stdin.write(prompt.encode())
            await proc.stdin.drain()
            proc.stdin.close()

        stdout_parts: List[str] = []
        stderr_parts: List[str] = []

        async def _read_stream(stream, stream_type: str, parts: List[str]):
            nonlocal log_count
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="replace")
                parts.append(text)
                entry = {"type": stream_type, "text": text, "timestamp": time.time()}
                await _append_log(job_id, entry)
                log_count += 1
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
        await _save_job(job)

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
        await _append_log(job_id, {"type": "error", "text": error_msg, "timestamp": time.time()})
        log_count += 1
        await _save_job(job)
        await emit_event("executor:error", {"jobId": job_id, "taskId": task_id, "error": error_msg})

    except Exception as e:
        job["status"] = "error"
        job["completedAt"] = time.time()
        await _append_log(job_id, {"type": "error", "text": str(e), "timestamp": time.time()})
        log_count += 1
        await _save_job(job)
        await emit_event("executor:error", {"jobId": job_id, "taskId": task_id, "error": str(e)})

    job["logCount"] = log_count
    return job


async def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Fetch job metadata from Redis. Includes logCount but not the logs themselves."""
    r = get_redis()
    raw = await r.get(_job_key(job_id))
    if raw is None:
        return None
    job = json.loads(raw)
    job["logCount"] = await r.llen(_logs_key(job_id))
    return job


async def get_job_logs(job_id: str) -> List[Dict[str, Any]]:
    """Fetch all log entries for a job from the separate Redis list."""
    r = get_redis()
    raw_entries = await r.lrange(_logs_key(job_id), 0, -1)
    return [json.loads(entry) for entry in raw_entries]


async def get_jobs_by_task(task_id: str) -> List[Dict[str, Any]]:
    """Fetch all jobs for a task using the Redis set index."""
    r = get_redis()
    job_ids = await r.smembers(_task_index_key(task_id))
    jobs = []
    for jid in job_ids:
        job = await get_job(jid)
        if job:
            jobs.append(job)
    return sorted(jobs, key=lambda j: j.get("startedAt", 0), reverse=True)


async def kill_job(job_id: str) -> bool:
    """Send SIGTERM to a running job's process.

    NOTE: kill only works on the same machine where the process was started.
    In a multi-node deployment, the PID stored in Redis is only meaningful
    on the originating host. A distributed kill would require a pub/sub
    command channel to the correct worker node.
    """
    job = await get_job(job_id)
    if not job or not job.get("pid"):
        return False
    try:
        os.kill(job["pid"], 15)  # SIGTERM
        job["status"] = "killed"
        job["completedAt"] = time.time()
        job.pop("logCount", None)
        await _save_job(job)
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
