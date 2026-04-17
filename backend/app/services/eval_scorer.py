"""Eval scorer plugins.

Each scorer maps `(output, expected) → ScoreOutcome`. Used by
`services.eval_runner.run_dataset` and isolated here so we can add new
scorers without touching the runner.

Built-ins:
  - contains   : every string in expected.substrings must appear in output (case-insensitive by default)
  - regex      : expected.pattern must match (re.search) the output
  - exact      : output.strip() == expected.value.strip()
  - json_path  : output is JSON-parsable; dotted paths in expected.paths must equal expected values
  - llm_judge  : ask an LLM to score 0..1 against a rubric

A scorer returns:
  {
    "score":   float in [0, 1],
    "passed":  bool,
    "detail":  {"matched": [...], "missing": [...], "reason": "..."},
  }
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

PASS_THRESHOLD = 0.6


def _empty(reason: str) -> Dict[str, Any]:
    return {"score": 0.0, "passed": False, "detail": {"reason": reason}}


def _ok(score: float, **detail) -> Dict[str, Any]:
    return {"score": float(score), "passed": float(score) >= PASS_THRESHOLD, "detail": detail}


def score_contains(output: str, expected: Dict[str, Any]) -> Dict[str, Any]:
    subs: List[str] = list(expected.get("substrings") or expected.get("any") or [])
    if not subs and isinstance(expected.get("contains"), str):
        subs = [expected["contains"]]
    if not subs:
        return _empty("no substrings configured")
    case_sensitive = bool(expected.get("case_sensitive", False))
    haystack = output if case_sensitive else output.lower()
    matched, missing = [], []
    for s in subs:
        needle = s if case_sensitive else s.lower()
        (matched if needle in haystack else missing).append(s)
    score = len(matched) / max(1, len(subs))
    return _ok(score, matched=matched, missing=missing, total=len(subs))


def score_regex(output: str, expected: Dict[str, Any]) -> Dict[str, Any]:
    pattern = expected.get("pattern") or expected.get("regex")
    if not pattern:
        return _empty("no pattern configured")
    flags = 0 if expected.get("case_sensitive") else re.IGNORECASE
    try:
        m = re.search(pattern, output, flags)
    except re.error as e:
        return _empty(f"invalid regex: {e}")
    return _ok(1.0 if m else 0.0, matched=bool(m), pattern=pattern)


def score_exact(output: str, expected: Dict[str, Any]) -> Dict[str, Any]:
    target = str(expected.get("value", ""))
    out = output.strip()
    return _ok(1.0 if out == target.strip() else 0.0, expected=target[:200], got=out[:200])


def _resolve_path(obj: Any, dotted: str) -> Any:
    cur: Any = obj
    for part in dotted.split("."):
        if part == "":
            continue
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except Exception:
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def score_json_path(output: str, expected: Dict[str, Any]) -> Dict[str, Any]:
    paths: Dict[str, Any] = expected.get("paths") or {}
    if not paths:
        return _empty("no paths configured")
    text = output.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
    except Exception as e:
        return _empty(f"output is not JSON: {e}")
    matched, mismatched = [], []
    for path, want in paths.items():
        got = _resolve_path(parsed, path)
        if got == want:
            matched.append({"path": path, "value": want})
        else:
            mismatched.append({"path": path, "expected": want, "got": got})
    score = len(matched) / max(1, len(paths))
    return _ok(score, matched=matched, mismatched=mismatched)


async def score_llm_judge(
    output: str, expected: Dict[str, Any], task: str = ""
) -> Dict[str, Any]:
    from ..config import settings
    from .llm_router import chat_completion

    rubric = expected.get("rubric") or "Grade how well the answer meets the implicit requirements."
    has_key = any([
        settings.openai_api_key, settings.anthropic_api_key, settings.deepseek_api_key,
        settings.google_api_key, settings.zhipu_api_key, settings.qwen_api_key,
        settings.llm_api_key,
    ])
    if not has_key:
        return _empty("no LLM key configured for llm_judge")

    sys = (
        "You are a strict evaluator. Score the answer on a scale of 0.0 to 1.0 "
        "against the rubric. Output ONLY JSON: "
        '{"score": float, "reason": "..."} — no markdown fences.'
    )
    user = (
        f"# Task\n{task}\n\n# Rubric\n{rubric}\n\n# Answer to grade\n{output[:4000]}\n\n"
        "Output JSON now."
    )
    try:
        rsp = await chat_completion(
            model=settings.llm_model or "deepseek-chat",
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
            temperature=0.0,
        )
    except Exception as e:
        return _empty(f"llm_judge call failed: {e}")
    if not rsp or rsp.get("error"):
        return _empty(f"llm_judge error: {rsp.get('error') if rsp else 'none'}")
    raw = (rsp.get("content") or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
    except Exception:
        return _empty(f"llm_judge JSON parse failed: {raw[:200]}")
    score = float(parsed.get("score") or 0.0)
    score = max(0.0, min(1.0, score))
    return _ok(score, reason=str(parsed.get("reason", ""))[:300])


SYNC_SCORERS = {
    "contains": score_contains,
    "regex": score_regex,
    "exact": score_exact,
    "json_path": score_json_path,
}


async def run_scorer(
    scorer: str, output: str, expected: Dict[str, Any], task: str = ""
) -> Dict[str, Any]:
    """Dispatch to the appropriate scorer (sync or async)."""
    scorer = (scorer or "contains").strip().lower()
    if scorer == "llm_judge":
        return await score_llm_judge(output, expected, task)
    fn = SYNC_SCORERS.get(scorer)
    if not fn:
        return _empty(f"unknown scorer '{scorer}'")
    try:
        return fn(output, expected)
    except Exception as e:
        logger.exception(f"[eval.scorer] {scorer} crashed: {e}")
        return _empty(f"scorer crashed: {e}")
