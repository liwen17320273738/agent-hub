"""
Git Workflow Tool — enables agents to interact with Git repositories.

Capabilities:
- Clone repositories
- Create/switch branches
- Stage and commit changes
- Create pull requests (via GitHub API)
- Check status, diff, log
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ALLOWED_GIT_DIRS: List[str] = []
_MAX_DIFF_LENGTH = 50000


def _validate_repo_dir(repo_dir: str) -> str:
    """Validate repo directory against whitelist."""
    resolved = str(Path(repo_dir).resolve())
    allow_env = os.environ.get("GIT_ALLOWED_DIRS", "")
    allowed = [d.strip() for d in allow_env.split(",") if d.strip()] if allow_env else []
    allowed.extend(ALLOWED_GIT_DIRS)

    if not allowed:
        workspace = os.environ.get("WORKSPACE_DIR", "")
        if workspace and resolved.startswith(str(Path(workspace).resolve())):
            return resolved
        temp = tempfile.gettempdir()
        if resolved.startswith(temp):
            return resolved
        raise ValueError(f"Directory {resolved} not in allowed list. Set GIT_ALLOWED_DIRS env var.")

    for allowed_dir in allowed:
        if resolved.startswith(str(Path(allowed_dir).resolve())):
            return resolved

    raise ValueError(f"Directory {resolved} not in allowed list")


async def _run_git(args: List[str], cwd: str, timeout: int = 60) -> Dict[str, Any]:
    """Run a git command and return result."""
    cmd = ["git"] + args
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "stdout": stdout.decode(errors="replace").strip(),
            "stderr": stderr.decode(errors="replace").strip(),
            "returncode": proc.returncode,
        }
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "error": "Git command timed out", "returncode": -1}
    except Exception as e:
        return {"ok": False, "error": str(e), "returncode": -1}


def _sanitize_ref_name(name: str) -> str:
    """Reject ref names that look like CLI flags."""
    if name.startswith("-"):
        raise ValueError(f"Invalid ref name (cannot start with '-'): {name}")
    return name


async def git_clone(url: str, target_dir: str, branch: Optional[str] = None) -> Dict[str, Any]:
    """Clone a git repository."""
    target = _validate_repo_dir(target_dir)
    if url.startswith("-"):
        return {"ok": False, "error": "Invalid repository URL"}
    args = ["clone", "--depth", "50"]
    if branch:
        args.extend(["-b", _sanitize_ref_name(branch)])
    args.extend(["--", url, target])

    parent = str(Path(target).parent)
    os.makedirs(parent, exist_ok=True)
    return await _run_git(args, parent, timeout=120)


async def git_status(repo_dir: str) -> Dict[str, Any]:
    """Get repository status."""
    cwd = _validate_repo_dir(repo_dir)
    result = await _run_git(["status", "--porcelain", "-b"], cwd)
    if not result["ok"]:
        return result

    lines = result["stdout"].split("\n")
    branch = ""
    changes: List[Dict[str, str]] = []
    for line in lines:
        if line.startswith("##"):
            branch = line[3:].split("...")[0]
        elif line.strip():
            status = line[:2].strip()
            filepath = line[3:].strip()
            changes.append({"status": status, "file": filepath})

    result["branch"] = branch
    result["changes"] = changes
    result["clean"] = len(changes) == 0
    return result


async def git_checkout(repo_dir: str, branch: str, create: bool = False) -> Dict[str, Any]:
    """Switch to or create a branch."""
    cwd = _validate_repo_dir(repo_dir)
    branch = _sanitize_ref_name(branch)
    args = ["checkout"]
    if create:
        args.append("-b")
    args.extend(["--", branch])
    return await _run_git(args, cwd)


async def git_add(repo_dir: str, files: Optional[List[str]] = None) -> Dict[str, Any]:
    """Stage files for commit."""
    cwd = _validate_repo_dir(repo_dir)
    args = ["add"]
    if files:
        args.extend(files)
    else:
        args.append("-A")
    return await _run_git(args, cwd)


async def git_commit(
    repo_dir: str,
    message: str,
    author: str = "Agent Hub <agent@agenthub.dev>",
) -> Dict[str, Any]:
    """Create a commit."""
    cwd = _validate_repo_dir(repo_dir)
    return await _run_git(
        ["commit", "-m", message, f"--author={author}"],
        cwd,
    )


async def git_push(
    repo_dir: str,
    remote: str = "origin",
    branch: Optional[str] = None,
    set_upstream: bool = False,
) -> Dict[str, Any]:
    """Push commits to remote."""
    cwd = _validate_repo_dir(repo_dir)
    remote = _sanitize_ref_name(remote)
    args = ["push"]
    if set_upstream:
        args.append("-u")
    args.append(remote)
    if branch:
        args.append(_sanitize_ref_name(branch))
    return await _run_git(args, cwd, timeout=120)


async def git_diff(repo_dir: str, staged: bool = False) -> Dict[str, Any]:
    """Get diff of changes."""
    cwd = _validate_repo_dir(repo_dir)
    args = ["diff"]
    if staged:
        args.append("--staged")
    args.append("--stat")
    result = await _run_git(args, cwd)

    full_diff = await _run_git(["diff"] + (["--staged"] if staged else []), cwd)
    if full_diff["ok"]:
        diff_text = full_diff["stdout"]
        if len(diff_text) > _MAX_DIFF_LENGTH:
            diff_text = diff_text[:_MAX_DIFF_LENGTH] + "\n... (truncated)"
        result["full_diff"] = diff_text

    return result


async def git_log(repo_dir: str, limit: int = 10) -> Dict[str, Any]:
    """Get recent commit log."""
    cwd = _validate_repo_dir(repo_dir)
    result = await _run_git(
        ["log", f"-{limit}", "--pretty=format:%H|%an|%ae|%s|%ci"],
        cwd,
    )
    if not result["ok"]:
        return result

    commits = []
    for line in result["stdout"].split("\n"):
        if "|" in line:
            parts = line.split("|", 4)
            if len(parts) == 5:
                commits.append({
                    "hash": parts[0],
                    "author": parts[1],
                    "email": parts[2],
                    "message": parts[3],
                    "date": parts[4],
                })
    result["commits"] = commits
    return result


async def git_create_pr(
    repo_dir: str,
    title: str,
    body: str,
    base: str = "main",
    head: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a pull request using GitHub CLI (gh)."""
    cwd = _validate_repo_dir(repo_dir)

    if not head:
        status = await git_status(cwd)
        head = status.get("branch", "")

    args = ["pr", "create", "--title", title, "--body", body, "--base", base, "--head", head]

    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        return {
            "ok": proc.returncode == 0,
            "url": stdout.decode(errors="replace").strip(),
            "stderr": stderr.decode(errors="replace").strip(),
        }
    except FileNotFoundError:
        return {"ok": False, "error": "GitHub CLI (gh) not installed. Install: https://cli.github.com"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def write_file(repo_dir: str, filepath: str, content: str) -> Dict[str, Any]:
    """Write content to a file in the repo."""
    cwd = _validate_repo_dir(repo_dir)
    full_path = (Path(cwd) / filepath).resolve()

    if not str(full_path).startswith(str(Path(cwd).resolve())):
        return {"ok": False, "error": "Path traversal not allowed"}

    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")

    return {"ok": True, "path": str(full_path), "size": len(content)}


GIT_TOOL_DEFINITIONS = [
    {
        "name": "git_clone",
        "description": "Clone a git repository to a local directory",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Repository URL"},
                "target_dir": {"type": "string", "description": "Target directory path"},
                "branch": {"type": "string", "description": "Branch to clone (optional)"},
            },
            "required": ["url", "target_dir"],
        },
    },
    {
        "name": "git_status",
        "description": "Get current repository status (branch, changes)",
        "parameters": {
            "type": "object",
            "properties": {"repo_dir": {"type": "string"}},
            "required": ["repo_dir"],
        },
    },
    {
        "name": "git_checkout",
        "description": "Switch to or create a branch",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_dir": {"type": "string"},
                "branch": {"type": "string"},
                "create": {"type": "boolean", "default": False},
            },
            "required": ["repo_dir", "branch"],
        },
    },
    {
        "name": "git_add",
        "description": "Stage files for commit",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_dir": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}, "description": "Files to stage (empty = all)"},
            },
            "required": ["repo_dir"],
        },
    },
    {
        "name": "git_commit",
        "description": "Create a commit with staged changes",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_dir": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["repo_dir", "message"],
        },
    },
    {
        "name": "git_push",
        "description": "Push commits to remote repository",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_dir": {"type": "string"},
                "remote": {"type": "string", "default": "origin"},
                "branch": {"type": "string"},
                "set_upstream": {"type": "boolean", "default": False},
            },
            "required": ["repo_dir"],
        },
    },
    {
        "name": "git_diff",
        "description": "Get diff of current changes",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_dir": {"type": "string"},
                "staged": {"type": "boolean", "default": False},
            },
            "required": ["repo_dir"],
        },
    },
    {
        "name": "git_log",
        "description": "Get recent commit history",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_dir": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["repo_dir"],
        },
    },
    {
        "name": "git_create_pr",
        "description": "Create a GitHub pull request",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_dir": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "base": {"type": "string", "default": "main"},
            },
            "required": ["repo_dir", "title", "body"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file in the repository",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_dir": {"type": "string"},
                "filepath": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["repo_dir", "filepath", "content"],
        },
    },
]


async def execute_git_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a git tool by name."""
    tools = {
        "git_clone": lambda a: git_clone(a["url"], a["target_dir"], a.get("branch")),
        "git_status": lambda a: git_status(a["repo_dir"]),
        "git_checkout": lambda a: git_checkout(a["repo_dir"], a["branch"], a.get("create", False)),
        "git_add": lambda a: git_add(a["repo_dir"], a.get("files")),
        "git_commit": lambda a: git_commit(a["repo_dir"], a["message"]),
        "git_push": lambda a: git_push(a["repo_dir"], a.get("remote", "origin"), a.get("branch"), a.get("set_upstream", False)),
        "git_diff": lambda a: git_diff(a["repo_dir"], a.get("staged", False)),
        "git_log": lambda a: git_log(a["repo_dir"], a.get("limit", 10)),
        "git_create_pr": lambda a: git_create_pr(a["repo_dir"], a["title"], a["body"], a.get("base", "main")),
        "write_file": lambda a: write_file(a["repo_dir"], a["filepath"], a["content"]),
    }

    handler = tools.get(name)
    if not handler:
        return {"ok": False, "error": f"Unknown git tool: {name}"}

    try:
        return await handler(args)
    except Exception as e:
        return {"ok": False, "error": str(e)}
