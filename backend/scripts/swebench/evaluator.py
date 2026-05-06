"""Apply the model patch + run target tests to score one instance.

Order of operations (mirrors SWE-Bench official harness):

1. ``git apply --check`` the agent's patch — fail fast if it doesn't apply
2. ``git apply`` it
3. Run ``FAIL_TO_PASS`` tests; they were broken before, must pass now
4. Run ``PASS_TO_PASS`` tests (sample); they were green before, must stay green
5. Aggregate into a single :class:`InstanceResult`

We prefer Docker (via ``app.services.tools.docker_sandbox.docker_exec``) when
it's available — same container hardening as production code execution.
Local fallback is gated on ``allow_local_exec`` because running 300 random
test suites on the host is a footgun.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class InstanceResult:
    instance_id: str
    resolved: bool
    apply_ok: bool
    fail_to_pass_passed: List[str] = field(default_factory=list)
    fail_to_pass_failed: List[str] = field(default_factory=list)
    pass_to_pass_passed: List[str] = field(default_factory=list)
    pass_to_pass_regressed: List[str] = field(default_factory=list)
    duration_s: float = 0.0
    error: Optional[str] = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    engine: str = "unknown"

    def to_dict(self) -> Dict[str, object]:
        return {
            "instance_id": self.instance_id,
            "resolved": self.resolved,
            "apply_ok": self.apply_ok,
            "fail_to_pass_passed": self.fail_to_pass_passed,
            "fail_to_pass_failed": self.fail_to_pass_failed,
            "pass_to_pass_passed": self.pass_to_pass_passed,
            "pass_to_pass_regressed": self.pass_to_pass_regressed,
            "duration_s": round(self.duration_s, 3),
            "error": self.error,
            "stdout_tail": self.stdout_tail[-2000:],
            "stderr_tail": self.stderr_tail[-2000:],
            "engine": self.engine,
        }


async def evaluate_patch(
    *,
    instance,
    patch_text: str,
    repo_dir: Path,
    test_command: Optional[str] = None,
    setup_cmd: Optional[str] = None,
    timeout_s: int = 600,
    allow_local_exec: bool = False,
    docker_image: Optional[str] = None,
    force_local: bool = False,
) -> InstanceResult:
    """Apply ``patch_text`` and run the instance's tests.

    ``test_command`` overrides the default ``pytest`` invocation. Many
    SWE-Bench repos ship custom test runners; expose this knob explicitly
    so per-repo configs can be added later without touching this module.
    """
    started = time.monotonic()
    result = InstanceResult(instance_id=instance.instance_id, resolved=False, apply_ok=False)

    apply_ok, apply_err = await _apply_agent_patch(repo_dir, patch_text)
    result.apply_ok = apply_ok
    if not apply_ok:
        result.error = apply_err
        result.duration_s = time.monotonic() - started
        return result

    if setup_cmd:
        setup_engine, setup_result = await _run_tests(
            repo_dir, setup_cmd, timeout_s=max(60, timeout_s // 2),
            allow_local_exec=allow_local_exec, docker_image=docker_image, force_local=force_local,
        )
        if not setup_result.get("ok"):
            result.engine = setup_engine
            result.stdout_tail = str(setup_result.get("stdout") or "")
            result.stderr_tail = str(setup_result.get("stderr") or "")
            result.error = "setup-failed"
            result.duration_s = time.monotonic() - started
            return result

    if test_command:
        cmd = test_command.replace(
            "{tests}",
            " ".join(_quote(t) for t in (instance.fail_to_pass + instance.pass_to_pass)[:50]),
        )
    else:
        cmd = _default_pytest_command(instance.fail_to_pass + instance.pass_to_pass)

    engine, exec_result = await _run_tests(
        repo_dir, cmd, timeout_s=timeout_s,
        allow_local_exec=allow_local_exec, docker_image=docker_image, force_local=force_local,
    )
    result.engine = engine
    result.stdout_tail = str(exec_result.get("stdout") or "")
    result.stderr_tail = str(exec_result.get("stderr") or "")
    if not exec_result.get("ok") and exec_result.get("exit_code") in (-1, None):
        result.error = (result.stderr_tail or "test runner failed")[-500:]
        result.duration_s = time.monotonic() - started
        return result

    output = result.stdout_tail + "\n" + result.stderr_tail

    f2p_pass, f2p_fail = _split_results(instance.fail_to_pass, output)
    p2p_pass, p2p_regressed = _split_results(instance.pass_to_pass, output, default_pass=True)
    result.fail_to_pass_passed = f2p_pass
    result.fail_to_pass_failed = f2p_fail
    result.pass_to_pass_passed = p2p_pass
    result.pass_to_pass_regressed = p2p_regressed

    has_f2p = bool(instance.fail_to_pass)
    result.resolved = (
        has_f2p
        and not f2p_fail
        and not p2p_regressed
        and bool(f2p_pass)
    )
    result.duration_s = time.monotonic() - started
    return result


async def _apply_agent_patch(repo_dir: Path, patch_text: str) -> Tuple[bool, Optional[str]]:
    if not patch_text or not patch_text.strip():
        return False, "empty patch"

    patch_file = repo_dir / ".swebench_agent.patch"
    patch_file.write_text(patch_text, encoding="utf-8")
    try:
        check = await asyncio.create_subprocess_exec(
            "git", "apply", "--check", "--allow-empty", "--whitespace=nowarn", str(patch_file),
            cwd=str(repo_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await check.communicate()
        if check.returncode != 0:
            return False, f"git apply --check failed: {stderr.decode(errors='replace')[:500]}"

        proc = await asyncio.create_subprocess_exec(
            "git", "apply", "--allow-empty", "--whitespace=nowarn", str(patch_file),
            cwd=str(repo_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            return False, f"git apply failed: {stderr.decode(errors='replace')[:500]}"
        return True, None
    finally:
        try:
            patch_file.unlink()
        except FileNotFoundError:
            pass


def _default_pytest_command(test_ids: List[str]) -> str:
    """Build a pytest invocation. Quoting kept basic; SWE-Bench IDs are alphanumeric."""
    if not test_ids:
        return "python -m pytest -x --tb=short"
    safe_ids = " ".join(_quote(t) for t in test_ids[:50])
    return f"python -m pytest -x --tb=short {safe_ids}"


def _quote(t: str) -> str:
    if any(c in t for c in (" ", "\"", "'", "$", "`", ";", "|", "&")):
        return "'" + t.replace("'", "'\"'\"'") + "'"
    return t


async def _run_tests(
    repo_dir: Path,
    command: str,
    *,
    timeout_s: int,
    allow_local_exec: bool,
    docker_image: Optional[str],
    force_local: bool = False,
) -> Tuple[str, Dict[str, object]]:
    try:
        from app.services.tools import docker_sandbox  # type: ignore
    except ImportError:
        docker_sandbox = None  # type: ignore

    if docker_sandbox is not None and not force_local:
        try:
            available = await docker_sandbox.is_docker_available_async()
        except Exception as exc:
            logger.debug("docker probe failed: %s", exc)
            available = False
        if available:
            res = await docker_sandbox.docker_exec(
                command=command,
                workspace_dir=str(repo_dir),
                timeout=timeout_s,
                image=docker_image,
                network="bridge",
            )
            return "docker", res

    if not allow_local_exec:
        return "none", {
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": (
                "Docker not available and allow_local_exec=False. "
                "Pass --allow-local-exec to run on the host (NOT recommended for full runs)."
            ),
        }

    return "local", await _local_exec(command, cwd=repo_dir, timeout_s=timeout_s)


async def _local_exec(command: str, *, cwd: Path, timeout_s: int) -> Dict[str, object]:
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": f"timed out after {timeout_s}s"}
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode if proc.returncode is not None else -1,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
    }


def _split_results(test_ids: List[str], output: str, *, default_pass: bool = False) -> Tuple[List[str], List[str]]:
    """Best-effort pytest output parser.

    Pytest prints ``PASSED foo::bar`` / ``FAILED foo::bar`` lines with ``-v``;
    we look for substring matches both ways since SWE-Bench IDs can use
    either ``foo.py::bar`` or ``foo/bar.py::Class::test``.
    """
    passed: List[str] = []
    failed: List[str] = []
    if not test_ids:
        return passed, failed
    for tid in test_ids:
        marker_pass = _has_status_line(output, tid, ("PASSED", "passed"))
        marker_fail = _has_status_line(output, tid, ("FAILED", "ERROR", "failed", "error"))
        if marker_pass and not marker_fail:
            passed.append(tid)
        elif marker_fail:
            failed.append(tid)
        elif default_pass:
            passed.append(tid)
        else:
            failed.append(tid)
    return passed, failed


def _has_status_line(output: str, tid: str, statuses: Tuple[str, ...]) -> bool:
    for line in output.splitlines():
        if tid in line and any(s in line for s in statuses):
            return True
    return False
