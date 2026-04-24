"""Code Extractor — parse fenced code blocks from LLM output and write real files.

Supports multiple patterns:
  1. ```language:path/to/file.ext
  2. ```language
     // filepath: path/to/file.ext
  3. ```language
     # filepath: path/to/file.ext
  4. Explicit file-section headers like "**文件: path/to/file.ext**" followed by a code block
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(
    r"```(\w+)?(?::([^\n`]+))?\n"
    r"(.*?)"
    r"\n```",
    re.DOTALL,
)

_FILEPATH_COMMENT_RE = re.compile(
    r"^(?://|#|--|/\*\*?)\s*(?:filepath|file|文件)[:\s]+(.+?)(?:\s*\*/)?$",
    re.IGNORECASE,
)

_BARE_PATH_COMMENT_RE = re.compile(
    r"^(?://|#)\s*([\w][\w./-]*\.(?:py|js|ts|vue|html|css|scss|json|yaml|yml|toml|sh|sql|java|go|rs|md|jsx|tsx|cpp|c|h|xml|dockerfile))\s*$",
    re.IGNORECASE,
)

_FILE_HEADER_RE = re.compile(
    r"\*\*(?:文件|File|filepath)[:\s]*`?([^`*]+)`?\*\*",
    re.IGNORECASE,
)

def _synthetic_filepath(lang: str, idx: int) -> str:
    """Stable relative path under generated/ when the model omits filepath."""
    low = (lang or "txt").lower().strip()
    ext = _LANG_TO_EXT.get(low, ".txt")
    if ext == "Dockerfile" or low in ("dockerfile", "docker"):
        return f"generated/Dockerfile.fragment{idx}"
    if ext and not str(ext).startswith("."):
        ext = f".{ext}"
    if not ext:
        ext = ".txt"
    return f"generated/extract_{idx:03d}{ext}"


_LANG_TO_EXT = {
    "python": ".py", "py": ".py",
    "javascript": ".js", "js": ".js",
    "typescript": ".ts", "ts": ".ts",
    "vue": ".vue",
    "html": ".html", "css": ".css", "scss": ".scss",
    "json": ".json", "yaml": ".yaml", "yml": ".yaml",
    "toml": ".toml",
    "dockerfile": "Dockerfile",
    "bash": ".sh", "shell": ".sh", "sh": ".sh",
    "sql": ".sql",
    "java": ".java", "go": ".go", "rust": ".rs",
    "markdown": ".md", "md": ".md",
    "xml": ".xml", "jsx": ".jsx", "tsx": ".tsx",
    "c": ".c", "cpp": ".cpp", "h": ".h",
}


@dataclass
class ExtractedFile:
    path: str
    content: str
    language: str = ""
    source_line: int = 0


@dataclass
class ExtractionResult:
    files: List[ExtractedFile] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    total_bytes: int = 0


def extract_code_blocks(text: str) -> ExtractionResult:
    """Parse all fenced code blocks with identifiable file paths."""
    result = ExtractionResult()
    if not text:
        return result

    file_header_positions: dict[int, str] = {}
    for m in _FILE_HEADER_RE.finditer(text):
        file_header_positions[m.end()] = m.group(1).strip()

    for m in _FENCE_RE.finditer(text):
        lang = (m.group(1) or "").strip()
        inline_path = (m.group(2) or "").strip()
        body = m.group(3)

        filepath: Optional[str] = None

        if inline_path:
            filepath = inline_path

        if not filepath and body:
            first_line = body.split("\n", 1)[0].strip()
            cm = _FILEPATH_COMMENT_RE.match(first_line)
            if not cm:
                cm = _BARE_PATH_COMMENT_RE.match(first_line)
            if cm:
                filepath = cm.group(1).strip()
                body = body.split("\n", 1)[1] if "\n" in body else ""

        if not filepath:
            search_start = max(0, m.start() - 200)
            for pos, hpath in file_header_positions.items():
                if search_start <= pos <= m.start():
                    filepath = hpath
                    break

        if not filepath:
            # issuse23: LLM 常输出 ```python 而无路径 — 生成可落盘的安全相对路径
            if lang and body and body.strip():
                idx = len(result.files) + 1
                filepath = _synthetic_filepath(lang, idx)
            else:
                continue

        filepath = filepath.strip("`'\" ")
        if filepath.startswith("/") or ".." in filepath:
            result.warnings.append(f"Skipped unsafe path: {filepath}")
            continue

        if not any(filepath.endswith(ext) or "/" in filepath for ext in (".py", ".js", ".ts", ".vue", ".html", ".css", ".json", ".yaml", ".yml", ".toml", ".sh", ".sql", ".java", ".go", ".rs", ".md", ".jsx", ".tsx", ".cpp", ".c", ".h")):
            ext = _LANG_TO_EXT.get(lang.lower(), "")
            if ext and not filepath.endswith(ext):
                filepath = filepath + ext

        content = body.rstrip()
        if not content:
            continue

        result.files.append(ExtractedFile(
            path=filepath,
            content=content,
            language=lang,
            source_line=text[:m.start()].count("\n") + 1,
        ))

    result.total_bytes = sum(len(f.content.encode("utf-8")) for f in result.files)
    return result


async def write_extracted_files(
    worktree_root: Path,
    extraction: ExtractionResult,
    sub_dir: str = "src",
) -> List[str]:
    """Write extracted files into the task worktree. Returns list of created paths."""
    created: List[str] = []
    src_root = worktree_root / sub_dir

    for ef in extraction.files:
        target = src_root / ef.path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(ef.content, encoding="utf-8")
            created.append(str(target.relative_to(worktree_root)))
            logger.info("[code-extractor] Wrote %s (%d bytes)", target, len(ef.content))
        except Exception as exc:
            logger.warning("[code-extractor] Failed to write %s: %s", ef.path, exc)

    return created
