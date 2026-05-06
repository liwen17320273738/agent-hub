from __future__ import annotations

from typing import Dict

STAGE_MIN_OUTPUT_HINTS: Dict[str, int] = {
    "planning": 1200,
    "design": 1800,
    "architecture": 1600,
    "development": 2500,
    "testing": 1200,
    "reviewing": 600,
}


def needs_output_top_up(stage_id: str, content: str) -> bool:
    text = (content or "").strip()
    min_len = STAGE_MIN_OUTPUT_HINTS.get(stage_id)
    if not min_len:
        return False
    if len(text) >= min_len:
        return False
    tail = text[-120:]
    return bool(text) and (
        text[-1:].isalnum()
        or tail.endswith("|")
        or "## " not in text
        or len(text) < int(min_len * 0.7)
    )
