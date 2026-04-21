"""Minimal "Agentless"-style patch-producing agent for SWE-Bench.

Three phases, each one LLM call:

1. **Locate** — given the issue + a flat list of repo paths, the model
   returns up to ``MAX_FILES_TO_READ`` paths that look most relevant.
2. **Read** — we ship the contents of those files (each capped at
   ``MAX_FILE_BYTES``) back to the model.
3. **Patch** — the model returns a unified diff. We extract it,
   validate it locally, and return it.

This is deliberately *not* a tool-using agent loop — keeps cost
predictable (~3 LLM calls/instance, ~30-60K tokens) and makes the
scoring honest (Agentless is the public baseline most papers cite).
The agent never executes code; the evaluator does that in Docker.

Cost ballpark (Claude Sonnet 4.5, average 50K tokens per attempt):
~$0.15/instance × 300 Lite instances ≈ $45 per full run.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional

from .patch_utils import PatchStats, extract_unified_diff, looks_like_noop, patch_stats
from .repo_workspace import list_repo_files, read_file_safely

logger = logging.getLogger(__name__)

DEFAULT_MAX_FILES_TO_READ = 6
DEFAULT_MAX_FILE_BYTES = 60_000
DEFAULT_MAX_PATHS_IN_PROMPT = 600


@dataclass
class AgentAttempt:
    """Outcome of one full locate→read→patch attempt."""

    instance_id: str
    patch: Optional[str]
    stats: PatchStats
    selected_files: List[str]
    error: Optional[str] = None
    raw_responses: List[str] = field(default_factory=list)
    token_usage: Dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.patch is not None and not self.stats.is_empty and not looks_like_noop(self.patch)


LlmFn = Callable[[str, List[Dict[str, str]]], Awaitable[Dict[str, object]]]


async def run_agentless_attempt(
    *,
    instance_id: str,
    problem_statement: str,
    repo_dir: Path,
    llm: LlmFn,
    max_files_to_read: int = DEFAULT_MAX_FILES_TO_READ,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_paths_in_prompt: int = DEFAULT_MAX_PATHS_IN_PROMPT,
) -> AgentAttempt:
    """Run a single attempt; never raises — failures land in ``AgentAttempt.error``."""
    raw: List[str] = []
    usage_total: Dict[str, int] = {}

    try:
        all_paths = list_repo_files(repo_dir)
        if not all_paths:
            return AgentAttempt(instance_id, None, PatchStats(0, 0, 0, 0), [], error="empty repo")

        candidate_paths = _shortlist_paths(all_paths, problem_statement, limit=max_paths_in_prompt)

        locate_msgs = _build_locate_messages(problem_statement, candidate_paths)
        locate_resp = await llm("locate", locate_msgs)
        raw.append(_resp_text(locate_resp))
        _accumulate_usage(usage_total, locate_resp)
        selected = _parse_selected_paths(_resp_text(locate_resp), valid=set(candidate_paths))[:max_files_to_read]
        if not selected:
            return AgentAttempt(instance_id, None, PatchStats(0, 0, 0, 0), [],
                                error="locate returned no valid paths", raw_responses=raw, token_usage=usage_total)

        file_blobs: List[Dict[str, object]] = []
        for rel in selected:
            blob = read_file_safely(repo_dir, rel, max_bytes=max_file_bytes)
            if blob:
                file_blobs.append(blob)
        if not file_blobs:
            return AgentAttempt(instance_id, None, PatchStats(0, 0, 0, 0), selected,
                                error="read phase produced no usable files",
                                raw_responses=raw, token_usage=usage_total)

        patch_msgs = _build_patch_messages(problem_statement, file_blobs)
        patch_resp = await llm("patch", patch_msgs)
        raw.append(_resp_text(patch_resp))
        _accumulate_usage(usage_total, patch_resp)
        diff = extract_unified_diff(_resp_text(patch_resp))
        if not diff:
            return AgentAttempt(instance_id, None, PatchStats(0, 0, 0, 0), selected,
                                error="no unified diff in model output",
                                raw_responses=raw, token_usage=usage_total)

        return AgentAttempt(
            instance_id=instance_id,
            patch=diff,
            stats=patch_stats(diff),
            selected_files=selected,
            raw_responses=raw,
            token_usage=usage_total,
        )
    except Exception as exc:
        logger.exception("[%s] agent attempt crashed", instance_id)
        return AgentAttempt(instance_id, None, PatchStats(0, 0, 0, 0), [],
                            error=f"{type(exc).__name__}: {exc}",
                            raw_responses=raw, token_usage=usage_total)


def _build_locate_messages(problem: str, paths: List[str]) -> List[Dict[str, str]]:
    listing = "\n".join(paths)
    return [
        {"role": "system", "content": (
            "You are an expert software engineer triaging an open-source bug. "
            "You will pick the SMALLEST set of files most likely to contain the fix. "
            "Reply with a JSON object: {\"files\": [\"path/one.py\", ...]}. "
            "No prose, no explanation, no markdown. Maximum 6 files."
        )},
        {"role": "user", "content": (
            f"### Issue\n{problem.strip()[:8000]}\n\n"
            f"### Repository file listing (truncated)\n{listing}\n\n"
            "Return JSON only."
        )},
    ]


def _build_patch_messages(problem: str, blobs: List[Dict[str, object]]) -> List[Dict[str, str]]:
    rendered = []
    for blob in blobs:
        rendered.append(f"### {blob['path']}\n```\n{blob['content']}\n```")
    bodies = "\n\n".join(rendered)
    return [
        {"role": "system", "content": (
            "You are an expert software engineer fixing a bug in an open-source project. "
            "Output exactly one unified diff (`diff --git ...`) inside a single ```diff fenced block. "
            "Use a/ and b/ prefixes for paths. Match indentation exactly. "
            "Touch only the files listed. Do not include explanations outside the fenced block."
        )},
        {"role": "user", "content": (
            f"### Issue\n{problem.strip()[:8000]}\n\n"
            f"### Files\n{bodies}\n\n"
            "Produce the smallest correct patch."
        )},
    ]


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _shortlist_paths(paths: List[str], problem: str, *, limit: int) -> List[str]:
    """Heuristic shortlist: keep paths whose name shares a token with the issue.

    If the issue mentions ``foo_bar`` we surface ``foo_bar.py`` and any file
    inside ``foo_bar/``. Falls back to the full sorted list if nothing matches.
    """
    if len(paths) <= limit:
        return sorted(paths)
    tokens = {t.lower() for t in _TOKEN_RE.findall(problem) if len(t) >= 4}
    if not tokens:
        return sorted(paths)[:limit]

    scored: List[tuple[int, str]] = []
    for p in paths:
        lower = p.lower()
        score = sum(1 for t in tokens if t in lower)
        if score:
            scored.append((score, p))
    if not scored:
        return sorted(paths)[:limit]
    scored.sort(key=lambda kv: (-kv[0], kv[1]))
    out = [p for _, p in scored[:limit]]

    seen = set(out)
    for p in sorted(paths):
        if len(out) >= limit:
            break
        if p not in seen:
            out.append(p)
            seen.add(p)
    return out


def _parse_selected_paths(text: str, *, valid: set[str]) -> List[str]:
    """Extract a JSON ``files`` list, fall back to line-scan if JSON is broken."""
    if not text:
        return []
    fence = re.search(r"```(?:json)?\s*\n(.+?)```", text, re.DOTALL | re.IGNORECASE)
    payload = fence.group(1).strip() if fence else text.strip()

    obj_match = re.search(r"\{[^{}]*\"files\"\s*:\s*\[[^\]]*\][^{}]*\}", payload, re.DOTALL)
    if obj_match:
        try:
            obj = json.loads(obj_match.group(0))
            files = obj.get("files") if isinstance(obj, dict) else None
            if isinstance(files, list):
                return [str(p) for p in files if isinstance(p, str) and p in valid]
        except json.JSONDecodeError:
            pass

    out: List[str] = []
    for line in payload.splitlines():
        s = line.strip().strip("-*•").strip().strip("`\"' ,")
        if s in valid:
            out.append(s)
    return out


def _resp_text(resp: Dict[str, object]) -> str:
    if not isinstance(resp, dict):
        return ""
    if isinstance(resp.get("content"), str):
        return resp["content"]  # type: ignore[return-value]
    if "error" in resp:
        return ""
    return ""


def _accumulate_usage(total: Dict[str, int], resp: Dict[str, object]) -> None:
    usage = resp.get("usage") if isinstance(resp, dict) else None
    if not isinstance(usage, dict):
        return
    for k, v in usage.items():
        if isinstance(v, int):
            total[k] = int(total.get(k, 0)) + v
