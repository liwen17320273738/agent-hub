"""Context compactor — auto-compress conversation history when nearing LLM context limits.

Strategy (modeled after Claude Code / Codex CLI):
1. Estimate token count of the full message list (chars / 4 heuristic).
2. When tokens exceed a configurable threshold (default 75% of model context),
   compact early messages by replacing them with an LLM-generated summary.
3. Always preserve:
   - The system prompt
   - The most recent N user messages
   - The most recent assistant response
4. Replace the middle portion with a single compacted summary message.

Integration point: `compact_messages_if_needed()` is called at the top of each
Agent Loop step in `agent_runtime.py`.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from .llm_router import chat_completion_with_fallback

logger = logging.getLogger(__name__)

# Default model context sizes (tokens). Used when model is unknown.
_DEFAULT_CONTEXT_SIZE = 128_000

# Known context sizes for common models.
_MODEL_CONTEXT_SIZES: Dict[str, int] = {
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "o1": 200_000,
    "o1-mini": 128_000,
    "o3-mini": 200_000,
    # Anthropic
    "claude-sonnet-4-20250514": 200_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-sonnet": 200_000,
    "claude-3-haiku": 200_000,
    "claude-3-opus": 200_000,
    # DeepSeek
    "deepseek-chat": 128_000,
    "deepseek-coder": 128_000,
    "deepseek-reasoner": 128_000,
    # Google
    "gemini-2.0-flash": 1_048_576,
    "gemini-1.5-pro": 2_097_152,
    # Zhipu
    "glm-4": 128_000,
    "glm-4-flash": 128_000,
    # Qwen
    "qwen-max": 32_768,
    "qwen-plus": 131_072,
}

# How much of the context window to use before triggering compaction.
_COMPACT_THRESHOLD_RATIO = 0.75

# Minimum number of recent message pairs to preserve during compaction.
_MIN_RECENT_PRESERVED = 4  # 2 user + 2 assistant turns


def get_model_context_size(model: str) -> int:
    """Return the context window size for a model, or the default."""
    model_lower = model.lower()
    for key, size in _MODEL_CONTEXT_SIZES.items():
        if key.lower() in model_lower:
            return size
    return _DEFAULT_CONTEXT_SIZE


def estimate_message_tokens(messages: List[Dict[str, Any]]) -> int:
    """Rough token estimate: chars / 4 (standard heuristic).

    More accurate than nothing, avoids adding tiktoken dependency.
    """
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            # Multimodal content blocks
            for block in content:
                if isinstance(block, dict):
                    total_chars += len(block.get("text", ""))
        # Tool calls contribute tokens too
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                args = tc.get("function", {}).get("arguments", "")
                total_chars += len(args)
    return max(1, total_chars // 4)


def should_compact(
    messages: List[Dict[str, Any]],
    model: str,
    threshold_ratio: float = _COMPACT_THRESHOLD_RATIO,
) -> bool:
    """Return True if the message list exceeds the compaction threshold."""
    context_size = get_model_context_size(model)
    threshold = int(context_size * threshold_ratio)
    current = estimate_message_tokens(messages)
    return current > threshold


def _split_messages(
    messages: List[Dict[str, Any]],
    min_recent: int = _MIN_RECENT_PRESERVED,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split messages into: [system], [compactable], [recent preserved].

    The system prompt (first message if role=system) is always kept.
    The last `min_recent` messages are always kept.
    Everything in between is compactable.
    """
    if not messages:
        return [], [], []

    system_msgs: List[Dict[str, Any]] = []
    rest = messages

    # Separate system messages
    if messages[0].get("role") == "system":
        system_msgs = [messages[0]]
        rest = messages[1:]

    # If there aren't enough messages to compact, return as-is
    if len(rest) <= min_recent:
        return system_msgs, [], rest

    compactable = rest[:-min_recent]
    recent = rest[-min_recent:]

    return system_msgs, compactable, recent


async def _generate_summary(
    messages_to_compact: List[Dict[str, Any]],
    model: str,
) -> str:
    """Use LLM to generate a summary of the given messages."""
    # Build a compact representation for the summarizer
    parts: List[str] = []
    for msg in messages_to_compact:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            # Multimodal: extract text only
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            content = " ".join(text_parts)
        if isinstance(content, str) and content.strip():
            # Truncate individual messages to avoid blowing up the summary call
            snippet = content[:2000]
            if len(content) > 2000:
                snippet += "..."
            parts.append(f"[{role}]: {snippet}")
        # Also note tool calls
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                name = tc.get("function", {}).get("name", "unknown")
                parts.append(f"[tool_call]: {name}")

    conversation_text = "\n".join(parts)

    summary_prompt = (
        "You are a context compactor. Summarize the following conversation history concisely. "
        "Preserve ALL key facts, decisions, code snippets, file names, error messages, and tool results. "
        "Remove filler, repetitions, and verbose explanations. "
        "Output a dense Markdown summary that another AI agent can use to continue the task.\n\n"
        f"## Conversation to summarize:\n{conversation_text}"
    )

    try:
        result = await chat_completion_with_fallback(
            model=model,
            messages=[{"role": "user", "content": summary_prompt}],
            temperature=0.0,
            max_tokens=1024,
        )
        if result.get("error"):
            logger.warning("[compactor] Summary generation failed: %s", result["error"])
            # Fallback: simple truncation summary
            return _simple_truncation_summary(messages_to_compact)
        return result.get("content", "") or _simple_truncation_summary(messages_to_compact)
    except Exception as e:
        logger.warning("[compactor] Summary generation exception: %s", e)
        return _simple_truncation_summary(messages_to_compact)


def _simple_truncation_summary(messages: List[Dict[str, Any]]) -> str:
    """Fallback: generate a simple summary by truncating each message."""
    parts: List[str] = ["## Compacted History (truncation fallback)\n"]
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            content = " ".join(text_parts)
        if isinstance(content, str) and content.strip():
            snippet = content[:300]
            if len(content) > 300:
                snippet += "..."
            parts.append(f"- [{role}]: {snippet}")
    return "\n".join(parts)


async def compact_messages(
    messages: List[Dict[str, Any]],
    model: str,
    min_recent: int = _MIN_RECENT_PRESERVED,
) -> List[Dict[str, Any]]:
    """Compact messages by replacing the middle portion with an LLM summary.

    Returns a new message list with the same system prompt and recent messages,
    but with older messages replaced by a compact summary.
    """
    system_msgs, compactable, recent = _split_messages(messages, min_recent)

    if not compactable:
        # Nothing to compact
        return messages

    logger.info(
        "[compactor] Compacting %d messages (keeping %d system + %d recent), model=%s",
        len(compactable), len(system_msgs), len(recent), model,
    )

    summary = await _generate_summary(compactable, model)

    compacted_msg = {
        "role": "user",
        "content": (
            "## Context Summary (auto-compacted)\n\n"
            "The following is a summary of earlier conversation history. "
            "Use it as context but prefer recent messages for current state.\n\n"
            f"{summary}"
        ),
    }

    new_messages = system_msgs + [compacted_msg] + recent

    before_tokens = estimate_message_tokens(messages)
    after_tokens = estimate_message_tokens(new_messages)
    reduction = before_tokens - after_tokens
    pct = (reduction / before_tokens * 100) if before_tokens > 0 else 0

    logger.info(
        "[compactor] Compacted: %d → %d messages, ~%d → ~%d tokens (-%d, %.1f%%)",
        len(messages), len(new_messages),
        before_tokens, after_tokens, reduction, pct,
    )

    return new_messages


async def compact_messages_if_needed(
    messages: List[Dict[str, Any]],
    model: str,
) -> List[Dict[str, Any]]:
    """Check if compaction is needed and compact if so. Returns the (possibly compacted) message list."""
    if should_compact(messages, model):
        return await compact_messages(messages, model)
    return messages
