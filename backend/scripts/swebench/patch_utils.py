"""Pure-logic helpers for SWE-Bench patch handling.

Extract a unified diff from a free-form LLM response, do conservative
sanity checks, and normalize line endings.

This module has zero external dependencies (no LLM, no git, no docker)
so it can be exhaustively unit-tested.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

_FENCE_RE = re.compile(
    r"```(?:diff|patch)?\s*\n(?P<body>.*?)```",
    re.DOTALL | re.IGNORECASE,
)

_DIFF_HEADER_RE = re.compile(
    r"^(diff --git a/.+ b/.+|--- a/.+|--- /dev/null)$",
    re.MULTILINE,
)

_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@", re.MULTILINE)


@dataclass(frozen=True)
class PatchStats:
    """Lightweight summary of an extracted patch — used for cost / debugging."""

    files_changed: int
    hunks: int
    additions: int
    deletions: int

    @property
    def is_empty(self) -> bool:
        return self.files_changed == 0 and self.hunks == 0


def extract_unified_diff(text: str) -> Optional[str]:
    """Return the largest plausible unified-diff block in ``text``, or ``None``.

    Strategy (tried in order, first that yields a diff with at least one hunk wins):

    1. A fenced ``` ```diff ... ``` block (canonical Anthropic / OpenAI format)
    2. A fenced ``` ``` block whose body has both ``--- a/`` and ``+++ b/`` headers
    3. The substring from the first ``diff --git`` (or first ``--- a/``) to end of input
    4. ``None`` if no candidate has at least one ``@@ ... @@`` hunk header
    """
    if not text:
        return None

    candidates: List[str] = []

    for m in _FENCE_RE.finditer(text):
        body = m.group("body").strip("\n")
        if body:
            candidates.append(body)

    plain_idx = _find_first_diff_start(text)
    if plain_idx is not None:
        candidates.append(text[plain_idx:].rstrip())

    plausible = [c for c in candidates if _HUNK_HEADER_RE.search(c) and _DIFF_HEADER_RE.search(c)]
    if not plausible:
        return None

    plausible.sort(key=len, reverse=True)
    return _normalize_line_endings(plausible[0])


def _find_first_diff_start(text: str) -> Optional[int]:
    git_idx = text.find("\ndiff --git ")
    if git_idx == -1 and text.startswith("diff --git "):
        git_idx = 0
    elif git_idx != -1:
        git_idx += 1

    minus_idx = text.find("\n--- a/")
    if minus_idx == -1 and text.startswith("--- a/"):
        minus_idx = 0
    elif minus_idx != -1:
        minus_idx += 1

    candidates = [i for i in (git_idx, minus_idx) if i is not None and i >= 0]
    return min(candidates) if candidates else None


def _normalize_line_endings(patch: str) -> str:
    text = patch.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    return text


def patch_stats(patch: str) -> PatchStats:
    """Best-effort line counting; cheap, no external tools."""
    if not patch:
        return PatchStats(0, 0, 0, 0)

    files = 0
    hunks = 0
    additions = 0
    deletions = 0

    for line in patch.splitlines():
        if line.startswith("diff --git ") or line.startswith("--- "):
            if line.startswith("diff --git ") or line.startswith("--- a/") or line.startswith("--- /dev/null"):
                files += 1 if line.startswith("diff --git ") or line.startswith("--- /dev/null") else 0
        elif line.startswith("@@ "):
            hunks += 1
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1

    if files == 0 and hunks > 0:
        files = max(1, len([1 for ln in patch.splitlines() if ln.startswith("--- a/")]))

    return PatchStats(files, hunks, additions, deletions)


def split_per_file(patch: str) -> List[Tuple[str, str]]:
    """Return ``[(path, file_patch_text), ...]`` so callers can apply per-file safely.

    A SWE-Bench instance can produce a patch that touches several files; some
    may apply cleanly while others reject. Splitting lets us count partial
    successes for failure-case analysis even when the full ``git apply`` fails.
    """
    if not patch:
        return []

    pieces: List[Tuple[str, str]] = []
    current_path: Optional[str] = None
    current_lines: List[str] = []

    for line in patch.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current_path is not None and current_lines:
                pieces.append((current_path, "".join(current_lines)))
            current_lines = [line]
            m = re.match(r"diff --git a/(.+?) b/(.+)", line.strip())
            current_path = m.group(2) if m else None
        else:
            current_lines.append(line)
    if current_path is not None and current_lines:
        pieces.append((current_path, "".join(current_lines)))

    if not pieces and patch:
        m = re.search(r"^\+\+\+ b/(.+)$", patch, re.MULTILINE)
        if m:
            pieces.append((m.group(1).strip(), patch))

    return pieces


def looks_like_noop(patch: str) -> bool:
    """Return True when the patch has no real ``+``/``-`` change lines."""
    stats = patch_stats(patch)
    return stats.is_empty or (stats.additions == 0 and stats.deletions == 0)
