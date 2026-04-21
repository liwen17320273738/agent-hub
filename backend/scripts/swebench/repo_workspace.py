"""Per-instance repository workspace management.

For each SWE-Bench instance we:

1. Clone (or reuse) the upstream repo into a cache directory
2. Worktree-checkout the exact ``base_commit`` into a fresh per-instance dir
3. Apply the instance's ``test_patch`` (sets up the failing tests)
4. Hand the path to the agent / evaluator
5. Cleanup the worktree afterwards (the cache stays for reuse)

Network access is required for the initial clone of each repo; subsequent
instances on the same repo are O(seconds) since they reuse the cache.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class WorkspaceLayout:
    """Directory layout for one instance run."""

    instance_id: str
    repo_dir: Path           # the per-instance worktree (writable)
    cache_dir: Path          # the shared bare/git cache for this repo
    test_patch_applied: bool = False


class RepoWorkspace:
    """Manage clone cache + per-instance worktrees.

    Usage::

        ws = RepoWorkspace(root="/tmp/swebench-runs")
        async with ws.checkout(inst) as layout:
            ... # run agent + evaluator inside layout.repo_dir
    """

    def __init__(self, *, root: str | os.PathLike[str]):
        self.root = Path(root).expanduser().resolve()
        self.cache_root = self.root / "_cache"
        self.run_root = self.root / "runs"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.run_root.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def checkout(self, instance) -> AsyncIterator[WorkspaceLayout]:
        cache_dir = await self._ensure_cache(instance.repo)
        run_dir = self.run_root / instance.instance_id
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir(parents=True)

        await _git(cache_dir, "clone", "--no-tags", "--shared", str(cache_dir), str(run_dir))
        await _git(run_dir, "checkout", "--quiet", "--detach", instance.base_commit)
        await _git(run_dir, "config", "user.email", "swebench@agent-hub.local")
        await _git(run_dir, "config", "user.name", "agent-hub-swebench")

        layout = WorkspaceLayout(
            instance_id=instance.instance_id,
            repo_dir=run_dir,
            cache_dir=cache_dir,
        )
        if instance.test_patch:
            layout.test_patch_applied = await _apply_patch(run_dir, instance.test_patch)
            if not layout.test_patch_applied:
                logger.warning(
                    "[%s] failed to apply test_patch — proceeding but score will be invalid",
                    instance.instance_id,
                )
        try:
            yield layout
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    async def _ensure_cache(self, repo: str) -> Path:
        slug = repo.replace("/", "__")
        cache_dir = self.cache_root / f"{slug}.git"
        if (cache_dir / "HEAD").exists():
            return cache_dir
        url = f"https://github.com/{repo}.git"
        logger.info("[swebench] cloning %s -> %s", url, cache_dir)
        await _run(["git", "clone", "--bare", url, str(cache_dir)])
        return cache_dir


async def _git(cwd: Path, *args: str) -> None:
    await _run(["git", *args], cwd=cwd)


async def _run(cmd, *, cwd: Optional[Path] = None) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed (exit {proc.returncode}): {' '.join(cmd)}\n"
            f"stdout: {stdout.decode(errors='replace')[:1000]}\n"
            f"stderr: {stderr.decode(errors='replace')[:1000]}"
        )


async def _apply_patch(cwd: Path, patch_text: str) -> bool:
    patch_file = cwd / ".swebench_test.patch"
    patch_file.write_text(patch_text, encoding="utf-8")
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "apply",
            "--allow-empty",
            "--whitespace=nowarn",
            str(patch_file),
            cwd=str(cwd),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("git apply failed: %s", stderr.decode(errors="replace")[:500])
            return False
        return True
    finally:
        try:
            patch_file.unlink()
        except FileNotFoundError:
            pass


def list_repo_files(root: Path, *, max_files: int = 2000) -> list[str]:
    """Return tracked repo paths (best-effort, ignores .git and large generated dirs)."""
    skip_dirs = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".tox"}
    out: list[str] = []
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for name in filenames:
            full = Path(dirpath) / name
            try:
                rel = full.relative_to(root)
            except ValueError:
                continue
            out.append(str(rel))
            if len(out) >= max_files:
                return out
    return out


def read_file_safely(root: Path, rel_path: str, *, max_bytes: int = 80_000) -> Optional[Dict[str, object]]:
    """Read a single file inside the repo workspace; refuse anything outside it."""
    root = root.resolve()
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if not target.is_file():
        return None
    data = target.read_bytes()
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return {"path": rel_path, "content": text, "truncated": truncated, "byte_size": target.stat().st_size}
