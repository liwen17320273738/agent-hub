"""Codebase indexing — lightweight repo map + literal/regex search.

Goal: give agents a quick "where is what" view of an existing project
without waiting for a heavy embedding pass.

Two pieces:
1. **repo_map(project_dir)** — walks the tree, lists files (skipping
   node_modules / .git / dist / etc.), and extracts top-level symbols
   from .py / .ts / .js / .tsx / .jsx / .vue / .go / .rs / .java
   using simple regex. Output is a structured Markdown summary capped
   to ~10K chars (so it fits in an LLM prompt).

2. **search_repo(project_dir, query)** — runs ripgrep when on PATH
   (fast, respects .gitignore), else a pure-Python fallback. Always
   returns line-numbered matches grouped by file.

Bonus tool `codebase_read_chunk` is just `file_read` with line range —
provided as a thin wrapper so agents can drill down after a search.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...config import settings

logger = logging.getLogger(__name__)

_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache", ".mypy_cache",
    "node_modules", "dist", "build", "out", "target", "vendor",
    ".next", ".nuxt", ".turbo", ".cache", ".venv", "venv", "env",
    ".idea", ".vscode", ".DS_Store",
}
_SKIP_EXTS = {
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".class", ".o", ".a",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".ico", ".svg",
    ".mp3", ".mp4", ".mov", ".avi", ".webm", ".wav", ".flac",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".db", ".sqlite", ".sqlite3", ".lock",
    ".woff", ".woff2", ".ttf", ".eot",
}
_INDEXABLE_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte",
    ".go", ".rs", ".java", ".kt", ".swift", ".rb", ".php",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".cs",
    ".md", ".mdx", ".rst", ".txt",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".env",
    ".html", ".css", ".scss", ".less",
    ".sh", ".bash", ".zsh", ".fish",
    ".sql", ".graphql", ".proto",
    ".dockerfile", "Dockerfile", "Makefile",
}

_SYMBOL_REGEXES: Dict[str, List[re.Pattern]] = {
    ".py": [
        re.compile(r"^class\s+(\w+)", re.MULTILINE),
        re.compile(r"^(?:async\s+)?def\s+(\w+)", re.MULTILINE),
    ],
    ".ts": [
        re.compile(r"^export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)", re.MULTILINE),
        re.compile(r"^export\s+(?:default\s+)?class\s+(\w+)", re.MULTILINE),
        re.compile(r"^export\s+(?:default\s+)?(?:const|let|var)\s+(\w+)", re.MULTILINE),
        re.compile(r"^export\s+interface\s+(\w+)", re.MULTILINE),
        re.compile(r"^export\s+type\s+(\w+)", re.MULTILINE),
    ],
    ".tsx": [],
    ".js": [
        re.compile(r"^export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)", re.MULTILINE),
        re.compile(r"^export\s+(?:default\s+)?class\s+(\w+)", re.MULTILINE),
        re.compile(r"^(?:module\.)?exports\.(\w+)\s*=", re.MULTILINE),
    ],
    ".jsx": [],
    ".vue": [
        re.compile(r"defineComponent\(\s*\{?\s*name:\s*['\"](\w+)['\"]", re.MULTILINE),
    ],
    ".go": [
        re.compile(r"^func\s+(?:\([^)]+\)\s+)?(\w+)", re.MULTILINE),
        re.compile(r"^type\s+(\w+)", re.MULTILINE),
    ],
    ".rs": [
        re.compile(r"^(?:pub(?:\([^)]+\))?\s+)?fn\s+(\w+)", re.MULTILINE),
        re.compile(r"^(?:pub(?:\([^)]+\))?\s+)?struct\s+(\w+)", re.MULTILINE),
        re.compile(r"^(?:pub(?:\([^)]+\))?\s+)?enum\s+(\w+)", re.MULTILINE),
        re.compile(r"^(?:pub(?:\([^)]+\))?\s+)?trait\s+(\w+)", re.MULTILINE),
    ],
    ".java": [
        re.compile(r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?class\s+(\w+)", re.MULTILINE),
        re.compile(r"^\s*(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?\S+\s+(\w+)\s*\(", re.MULTILINE),
    ],
}
_SYMBOL_REGEXES[".tsx"] = _SYMBOL_REGEXES[".ts"]
_SYMBOL_REGEXES[".jsx"] = _SYMBOL_REGEXES[".js"]


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _should_skip_dir(name: str) -> bool:
    return name in _SKIP_DIRS or name.startswith(".")


def _should_skip_file(path: Path, max_bytes: int) -> bool:
    if path.suffix.lower() in _SKIP_EXTS:
        return True
    try:
        if path.stat().st_size > max_bytes:
            return True
    except OSError:
        return True
    return False


def _is_indexable(path: Path) -> bool:
    if path.name in _INDEXABLE_EXTS:
        return True
    return path.suffix.lower() in _INDEXABLE_EXTS


def _extract_symbols(path: Path, content: str, limit: int = 12) -> List[str]:
    ext = path.suffix.lower()
    patterns = _SYMBOL_REGEXES.get(ext, [])
    if not patterns:
        return []
    seen: List[str] = []
    for pat in patterns:
        for m in pat.finditer(content):
            sym = m.group(1)
            if sym and sym not in seen:
                seen.append(sym)
                if len(seen) >= limit:
                    return seen
    return seen


def _walk(project_dir: Path, max_files: int):
    count = 0
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if not _should_skip_dir(d)]
        for fname in files:
            if count >= max_files:
                return
            yield Path(root) / fname
            count += 1


async def repo_map(params: Dict[str, Any]) -> str:
    """Build a Markdown overview of a project tree with key symbols per file."""
    project_dir = (params.get("project_dir") or "").strip()
    if not project_dir:
        return "Error: 'project_dir' is required"
    root = Path(project_dir).expanduser()
    if not root.exists() or not root.is_dir():
        return f"Error: project_dir not found or not a directory: {project_dir}"

    max_files = int(params.get("max_files") or settings.codebase_index_max_files)
    max_bytes = int(settings.codebase_index_max_file_kb) * 1024
    output_limit = int(params.get("output_limit") or 10000)

    files_by_dir: Dict[str, List[Dict[str, Any]]] = {}
    total = 0

    for path in _walk(root, max_files):
        rel = path.relative_to(root).as_posix()
        if _should_skip_file(path, max_bytes):
            continue
        rel_dir = str(Path(rel).parent) if Path(rel).parent.as_posix() != "." else "."
        info: Dict[str, Any] = {"name": path.name, "rel": rel}
        if _is_indexable(path):
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                info["lines"] = content.count("\n") + 1
                info["symbols"] = _extract_symbols(path, content)
            except Exception:
                info["lines"] = 0
                info["symbols"] = []
        else:
            info["lines"] = 0
            info["symbols"] = []
        files_by_dir.setdefault(rel_dir, []).append(info)
        total += 1

    lines: List[str] = [f"# Repo map: {root.name}", f"_indexed {total} files (cap={max_files})_", ""]
    for rel_dir in sorted(files_by_dir.keys()):
        lines.append(f"## `{rel_dir}/`" if rel_dir != "." else "## (root)")
        for info in sorted(files_by_dir[rel_dir], key=lambda i: i["name"]):
            sym_part = ""
            if info.get("symbols"):
                sym_part = "  — " + ", ".join(info["symbols"][:8])
            line_part = f" ({info['lines']}L)" if info.get("lines") else ""
            lines.append(f"- `{info['name']}`{line_part}{sym_part}")
        lines.append("")
        if sum(len(s) for s in lines) > output_limit:
            lines.append(f"…[truncated at {output_limit} chars; total files indexed: {total}]")
            break

    return "\n".join(lines)


async def _ripgrep(project_dir: Path, query: str, regex: bool, max_count: int) -> Optional[str]:
    rg = shutil.which("rg")
    if not rg:
        return None
    args = [rg, "--no-heading", "--line-number", "--color", "never",
            "--max-count", str(max_count), "--max-filesize", "200K"]
    if not regex:
        args.append("--fixed-strings")
    args.extend([query, "."])
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(project_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
    except asyncio.TimeoutError:
        proc.kill()
        return "Error: ripgrep timed out (20s)"
    return stdout.decode("utf-8", errors="replace")


async def _python_grep(project_dir: Path, query: str, regex: bool, max_count: int) -> str:
    pat = re.compile(query) if regex else None
    out: List[str] = []
    seen_per_file: Dict[str, int] = {}
    max_bytes = int(settings.codebase_index_max_file_kb) * 1024
    for path in _walk(project_dir, settings.codebase_index_max_files):
        if not _is_indexable(path) or _should_skip_file(path, max_bytes):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        rel = path.relative_to(project_dir).as_posix()
        for i, line in enumerate(content.splitlines(), start=1):
            hit = bool(pat.search(line)) if pat else (query in line)
            if not hit:
                continue
            count = seen_per_file.get(rel, 0)
            if count >= max_count:
                break
            out.append(f"{rel}:{i}:{line}")
            seen_per_file[rel] = count + 1
        if sum(len(s) for s in out) > 50_000:
            out.append("[truncated at ~50KB]")
            break
    return "\n".join(out) if out else "(no matches)"


async def search_repo(params: Dict[str, Any]) -> str:
    """Search codebase for a literal string or regex; returns line-numbered hits."""
    project_dir = (params.get("project_dir") or "").strip()
    query = params.get("query") or ""
    if not project_dir or not query:
        return "Error: both 'project_dir' and 'query' are required"
    root = Path(project_dir).expanduser()
    if not root.exists() or not root.is_dir():
        return f"Error: project_dir not found: {project_dir}"
    regex = bool(params.get("regex", False))
    max_count = int(params.get("max_count") or 5)
    max_count = max(1, min(max_count, 50))

    rg_out = await _ripgrep(root, query, regex, max_count)
    if rg_out is not None:
        if not rg_out.strip():
            return "(no matches)"
        return f"[engine: ripgrep]\n{rg_out}"
    py_out = await _python_grep(root, query, regex, max_count)
    return f"[engine: python]\n{py_out}"


async def read_chunk(params: Dict[str, Any]) -> str:
    """Read a slice of a file with optional line range. Returns numbered lines."""
    project_dir = (params.get("project_dir") or "").strip()
    rel_path = (params.get("path") or "").strip()
    if not project_dir or not rel_path:
        return "Error: both 'project_dir' and 'path' are required"
    root = Path(project_dir).expanduser().resolve()
    target = (root / rel_path).resolve()
    if not _is_under(target, root):
        return "Error: path escapes project_dir"
    if not target.exists() or not target.is_file():
        return f"Error: file not found: {rel_path}"
    start = max(1, int(params.get("start") or 1))
    end_raw = params.get("end")
    end = int(end_raw) if end_raw else None
    try:
        content = target.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"Error reading file: {e}"
    lines = content.splitlines()
    if end is None or end > len(lines):
        end = len(lines)
    if start > len(lines):
        return f"(file has only {len(lines)} lines)"
    width = len(str(end))
    out = [f"{i:>{width}} | {lines[i-1]}" for i in range(start, end + 1)]
    return f"# {rel_path} (lines {start}-{end} of {len(lines)})\n" + "\n".join(out)
