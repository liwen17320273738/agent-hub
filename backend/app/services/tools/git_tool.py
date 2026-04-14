"""Git tool — version control operations within the sandbox workspace."""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict

from .sandbox import get_sandbox_root

_MAX_OUTPUT = 100_000


async def _run_git(args: str, cwd: str, timeout: int = 30) -> Dict[str, Any]:
    proc = await asyncio.create_subprocess_shell(
        f"git {args}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"stdout": "", "stderr": f"git timed out after {timeout}s", "exit_code": -1}

    return {
        "stdout": stdout.decode("utf-8", errors="replace")[:_MAX_OUTPUT],
        "stderr": stderr.decode("utf-8", errors="replace")[:_MAX_OUTPUT],
        "exit_code": proc.returncode or 0,
    }


def _resolve_project_dir(params: Dict[str, Any]) -> str:
    project = params.get("project", "")
    root = get_sandbox_root()
    if project:
        d = os.path.join(root, "projects", project)
    else:
        d = os.path.join(root, "projects")
    os.makedirs(d, exist_ok=True)
    return d


async def git_init(params: Dict[str, Any]) -> str:
    """Initialize a new git repository."""
    cwd = _resolve_project_dir(params)
    r = await _run_git("init", cwd)
    if r["exit_code"] != 0:
        return f"Error: {r['stderr']}"
    await _run_git('config user.email "agent@hub.local"', cwd)
    await _run_git('config user.name "Agent Hub"', cwd)
    return f"Git repository initialized at {cwd}"


async def git_status(params: Dict[str, Any]) -> str:
    """Show current git status."""
    cwd = _resolve_project_dir(params)
    r = await _run_git("status --short", cwd)
    if r["exit_code"] != 0:
        return f"Error: {r['stderr']}"
    return r["stdout"] or "(clean working tree)"


async def git_add(params: Dict[str, Any]) -> str:
    """Stage files for commit."""
    files = params.get("files", ".")
    cwd = _resolve_project_dir(params)
    r = await _run_git(f"add {files}", cwd)
    if r["exit_code"] != 0:
        return f"Error: {r['stderr']}"
    return f"Staged: {files}"


async def git_commit(params: Dict[str, Any]) -> str:
    """Create a git commit."""
    message = params.get("message", "auto commit")
    cwd = _resolve_project_dir(params)
    r = await _run_git(f'commit -m "{message}"', cwd)
    if r["exit_code"] != 0:
        return f"Error: {r['stderr']}"
    return r["stdout"]


async def git_diff(params: Dict[str, Any]) -> str:
    """Show diff of current changes."""
    staged = params.get("staged", False)
    cwd = _resolve_project_dir(params)
    flag = "--cached" if staged else ""
    r = await _run_git(f"diff {flag} --stat", cwd)
    if r["exit_code"] != 0:
        return f"Error: {r['stderr']}"
    return r["stdout"] or "(no changes)"


async def git_log(params: Dict[str, Any]) -> str:
    """Show recent commit log."""
    count = min(params.get("count", 10), 50)
    cwd = _resolve_project_dir(params)
    r = await _run_git(f"log --oneline -n {count}", cwd)
    if r["exit_code"] != 0:
        return f"Error: {r['stderr']}"
    return r["stdout"] or "(no commits)"


async def git_branch(params: Dict[str, Any]) -> str:
    """Create or list branches."""
    branch_name = params.get("name", "")
    cwd = _resolve_project_dir(params)
    if branch_name:
        r = await _run_git(f"checkout -b {branch_name}", cwd)
    else:
        r = await _run_git("branch -a", cwd)
    if r["exit_code"] != 0:
        return f"Error: {r['stderr']}"
    return r["stdout"]


async def git_push(params: Dict[str, Any]) -> str:
    """Push commits to remote."""
    remote = params.get("remote", "origin")
    branch = params.get("branch", "main")
    cwd = _resolve_project_dir(params)
    r = await _run_git(f"push {remote} {branch}", cwd, timeout=60)
    if r["exit_code"] != 0:
        return f"Error: {r['stderr']}"
    return r["stdout"] or f"Pushed to {remote}/{branch}"
