"""
Project Binding — clone repos and validate local paths for existing project tasks.

Handles two modes:
1. repo_url → git clone into sandbox/projects/{slug}
2. project_path → validate the local path exists and register in whitelist
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from ipaddress import ip_address
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

from ..config import settings
from .tools.sandbox import get_sandbox_root
from .executor_bridge import ALLOWED_WORK_DIRS

logger = logging.getLogger(__name__)

_VALID_URL_PATTERN = re.compile(
    r"^(https?://|git@)[^\s]+\.git$|^(https?://)[^\s]+$"
)

_DEFAULT_ALLOWED_HOSTS = {
    "github.com", "gitee.com", "gitlab.com", "bitbucket.org",
    "codeup.aliyun.com",
}


def _allowed_hosts() -> set[str]:
    raw = (getattr(settings, "git_allowed_hosts", "") or "").strip()
    if not raw:
        return set(_DEFAULT_ALLOWED_HOSTS)
    hosts = {h.strip().lower() for h in raw.split(",") if h.strip()}
    return hosts or set(_DEFAULT_ALLOWED_HOSTS)


def _parse_repo_url(repo_url: str) -> Tuple[str, str]:
    """Return (scheme, hostname). Raises ValueError on malformed input."""
    s = (repo_url or "").strip()
    if not s:
        raise ValueError("repo_url is empty")

    # SSH-style: git@host:owner/repo.git
    m = re.match(r"^git@([^:]+):", s)
    if m:
        return "ssh", m.group(1).lower()

    parsed = urlparse(s)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if not scheme or not host:
        raise ValueError(f"repo_url is not a valid URL: {repo_url!r}")
    return scheme, host


def validate_repo_url(repo_url: str) -> str:
    """Validate `repo_url` against scheme + host allowlist + IP/network checks.

    - Only `https` (and `git@host:` SSH syntax) accepted; `http`/`file`/`ssh://`
      and friends rejected.
    - Hostname must be in `settings.git_allowed_hosts` (or its default set).
    - Hostname must not resolve to a literal IP (block direct-IP SSRF).
    - Rejects credentials embedded in the URL (`https://user:pass@host/...`)
      to avoid log leakage; users should use deploy keys instead.

    Returns the trimmed URL on success.
    """
    s = (repo_url or "").strip()
    scheme, host = _parse_repo_url(s)

    if scheme not in ("https", "ssh"):
        raise ValueError(
            f"Unsupported scheme '{scheme}'. Only HTTPS or SSH (git@host:) repos are allowed."
        )

    # Block raw-IP hosts even if literally listed.
    try:
        ip = ip_address(host)
        raise ValueError(
            f"IP-address hosts are not allowed (got {ip}). Use a registered domain."
        )
    except ValueError as e:
        if "does not appear to be an IPv4 or IPv6 address" not in str(e):
            raise

    if "@" in s.split("://", 1)[-1].split("/", 1)[0] and scheme == "https":
        raise ValueError(
            "Embedded credentials in repo_url are not allowed; use a deploy key or app token."
        )

    allowed = _allowed_hosts()
    if host not in allowed:
        raise ValueError(
            f"Host '{host}' is not in the git allowlist. "
            f"Allowed: {', '.join(sorted(allowed))}. "
            f"Add it to GIT_ALLOWED_HOSTS to enable."
        )
    return s


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:64].strip("-") or "project"


def _register_allowed_dir(path: str) -> None:
    """Add a directory to both executor and sandbox whitelists."""
    resolved = str(Path(path).resolve())
    if resolved not in ALLOWED_WORK_DIRS:
        ALLOWED_WORK_DIRS.append(resolved)
        logger.info(f"[project-binding] Registered allowed dir: {resolved}")


async def clone_and_bind(repo_url: str) -> str:
    """Clone a git repository into sandbox/projects/ and return the local path.

    Validates `repo_url` against the SSRF/scheme/host allowlist first.
    Raises ValueError if validation or clone fails.
    """
    if not repo_url:
        raise ValueError("repo_url is required")

    repo_url = validate_repo_url(repo_url)

    slug = _slugify(repo_url.rstrip("/").split("/")[-1].replace(".git", ""))
    projects_dir = os.path.join(get_sandbox_root(), "projects")
    os.makedirs(projects_dir, exist_ok=True)
    target = os.path.join(projects_dir, slug)

    if os.path.isdir(os.path.join(target, ".git")):
        logger.info(f"[project-binding] Repo already cloned at {target}, pulling latest")
        proc = await asyncio.create_subprocess_exec(
            "git", "pull", "--ff-only",
            cwd=target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()
        _register_allowed_dir(target)
        return target

    logger.info(f"[project-binding] Cloning {repo_url} → {target}")
    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth", "50", repo_url, target,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

    if proc.returncode != 0:
        error_msg = stderr.decode(errors="replace").strip()
        raise ValueError(f"Git clone failed: {error_msg}")

    _register_allowed_dir(target)
    return target


def validate_and_bind(project_path: str) -> str:
    """Validate a local project path exists and register it.

    Raises ValueError if path doesn't exist or looks suspicious.
    """
    resolved = str(Path(project_path).expanduser().resolve())

    if not os.path.isdir(resolved):
        raise ValueError(f"Project directory does not exist: {resolved}")

    dangerous_paths = ["/", "/etc", "/usr", "/var", "/bin", "/sbin", "/tmp"]
    if resolved in dangerous_paths:
        raise ValueError(f"Refusing to bind system directory: {resolved}")

    _register_allowed_dir(resolved)
    return resolved


def get_project_context(project_path: Optional[str]) -> str:
    """Scan an existing project and return a context summary for LLM prompts.

    Returns a Markdown summary of the project structure, key files, and tech stack.
    """
    if not project_path or not os.path.isdir(project_path):
        return ""

    skip_dirs = {
        "node_modules", ".git", "__pycache__", ".next", "dist", "build",
        ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache",
        "target", "coverage", ".turbo",
    }

    tree_lines: list[str] = []
    key_files: dict[str, str] = {}
    max_depth = 3
    max_files = 80

    file_count = 0
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in sorted(dirs) if d not in skip_dirs]
        depth = root.replace(project_path, "").count(os.sep)
        if depth >= max_depth:
            dirs.clear()
            continue

        indent = "  " * depth
        dirname = os.path.basename(root) or os.path.basename(project_path)
        tree_lines.append(f"{indent}{dirname}/")

        for f in sorted(files):
            if file_count >= max_files:
                break
            file_count += 1
            tree_lines.append(f"{indent}  {f}")

            if f in (
                "package.json", "requirements.txt", "pyproject.toml", "Cargo.toml",
                "go.mod", "pom.xml", "build.gradle", "Makefile", "Dockerfile",
                "docker-compose.yml", "README.md", ".env.example",
            ):
                fpath = os.path.join(root, f)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                        content = fh.read(2000)
                    rel = os.path.relpath(fpath, project_path)
                    key_files[rel] = content
                except Exception:
                    pass

    parts = ["## 项目结构\n```\n" + "\n".join(tree_lines[:100]) + "\n```"]

    if key_files:
        parts.append("## 关键文件")
        for rel_path, content in list(key_files.items())[:6]:
            parts.append(f"### {rel_path}\n```\n{content}\n```")

    tech_stack = _detect_tech_stack(project_path, key_files)
    if tech_stack:
        parts.append(f"## 检测到的技术栈\n{', '.join(tech_stack)}")

    return "\n\n".join(parts)


def _detect_tech_stack(project_path: str, key_files: dict[str, str]) -> list[str]:
    """Detect tech stack from project files."""
    stack: list[str] = []

    if "package.json" in key_files:
        pkg = key_files["package.json"]
        if "react" in pkg:
            stack.append("React")
        if "vue" in pkg:
            stack.append("Vue")
        if "next" in pkg:
            stack.append("Next.js")
        if "nuxt" in pkg:
            stack.append("Nuxt")
        if "typescript" in pkg:
            stack.append("TypeScript")
        if not stack or "node" not in " ".join(stack).lower():
            stack.append("Node.js")

    if "requirements.txt" in key_files or "pyproject.toml" in key_files:
        stack.append("Python")
        content = key_files.get("requirements.txt", "") + key_files.get("pyproject.toml", "")
        if "fastapi" in content.lower():
            stack.append("FastAPI")
        if "django" in content.lower():
            stack.append("Django")
        if "flask" in content.lower():
            stack.append("Flask")

    if "Cargo.toml" in key_files:
        stack.append("Rust")
    if "go.mod" in key_files:
        stack.append("Go")
    if "pom.xml" in key_files or "build.gradle" in key_files:
        stack.append("Java")

    if os.path.exists(os.path.join(project_path, "Dockerfile")):
        stack.append("Docker")

    return stack
