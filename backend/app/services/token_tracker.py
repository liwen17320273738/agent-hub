"""Token usage tracking and cost analysis."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple, Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.model_provider import TokenUsage

PRICING_PER_1K: Dict[str, Dict[str, Tuple[float, float]]] = {
    "openai": {
        "gpt-4o": (0.0025, 0.01),
        "gpt-4o-mini": (0.00015, 0.0006),
        "gpt-4.5": (0.075, 0.15),
        "gpt-4.1-mini": (0.0004, 0.0016),
        "o1": (0.015, 0.06),
        "o3-mini": (0.0011, 0.0044),
    },
    "anthropic": {
        "claude-sonnet-4-20250514": (0.003, 0.015),
        "claude-opus-4-20250514": (0.015, 0.075),
        "claude-3-5-sonnet": (0.003, 0.015),
        "claude-3-5-haiku": (0.0008, 0.004),
    },
    "deepseek": {
        "deepseek-chat": (0.00014, 0.00028),
        "deepseek-reasoner": (0.00055, 0.0022),
    },
    "google": {
        "gemini-2.5-pro": (0.00125, 0.01),
        "gemini-2.5-flash": (0.00015, 0.0006),
        "gemini-2.0-flash": (0.0001, 0.0004),
    },
    "zhipu": {
        "glm-4-plus": (0.0007, 0.0007),
        "glm-4-flash": (0.0001, 0.0001),
        "glm-4.5": (0.0007, 0.0007),
        "glm-4.6": (0.0007, 0.0007),
        "glm-4.7": (0.0007, 0.0007),
        "glm-5": (0.0007, 0.0007),
    },
    "qwen": {
        "qwen-turbo": (0.00003, 0.00006),
        "qwen-plus": (0.00056, 0.00168),
        "qwen-max": (0.0016, 0.0064),
    },
    # Gateway / local LLM — 使用 relay fallback 价格或本地零成本标记
    "gateway": {},
    "local": {},
}

# Relay fallback price (USD per 1k total tokens) — used when no provider-specific pricing matches
_RELAY_FALLBACK_USD_PER_1K = 0.00015


def _token_estimate_from_chars(text: str) -> int:
    """粗略 token 估算: 英文约 4 chars/token, 中文约 1.5 chars/token."""
    if not text:
        return 0
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other = len(text) - chinese
    return max(1, int(chinese / 1.5 + other / 4))


def estimate_cost(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    prices = PRICING_PER_1K.get(provider, {})
    matched = None
    for model_key in prices:
        if model_key in model:
            matched = prices[model_key]
            break
    if not matched:
        # 对 gateway/local 使用 settings 中配置的 relay fallback 价格
        if provider in ("gateway", "local", "unknown"):
            from ..config import settings
            fb = float(getattr(settings, "relay_fallback_usd_per_1k_total", 0.0) or 0.0)
            if fb > 0:
                return round((prompt_tokens + completion_tokens) / 1000 * fb, 6)
            return round((prompt_tokens + completion_tokens) / 1000 * _RELAY_FALLBACK_USD_PER_1K, 6)
        # 尝试模糊匹配
        for model_key in prices:
            if any(part in model for part in model_key.split("-") if len(part) > 2):
                matched = prices[model_key]
                break
    if not matched:
        return 0.0

    prompt_cost = (prompt_tokens / 1000) * matched[0]
    completion_cost = (completion_tokens / 1000) * matched[1]
    return round(prompt_cost + completion_cost, 6)


async def record_usage(
    db: AsyncSession,
    *,
    org_id: Optional[uuid.UUID],
    user_id: Optional[uuid.UUID],
    agent_id: Optional[str],
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int = 0,
    endpoint: str = "chat",
    metadata_extra: Optional[Dict[str, Any]] = None,
    cost_usd_override: Optional[float] = None,
) -> Optional[TokenUsage]:
    # org_id 或 user_id 缺失时跳过记录（不会 crash 整个 Pipeline）
    if org_id is None or user_id is None:
        logger.warning(
            "[token_tracker] 跳过用量记录 — org_id=%s user_id=%s model=%s",
            org_id, user_id, model,
        )
        return None
    total = prompt_tokens + completion_tokens
    cost = (
        round(float(cost_usd_override), 6)
        if cost_usd_override is not None
        else estimate_cost(provider, model, prompt_tokens, completion_tokens)
    )

    usage = TokenUsage(
        org_id=org_id,
        user_id=user_id,
        agent_id=agent_id,
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total,
        cost_usd=cost,
        latency_ms=latency_ms,
        endpoint=endpoint,
        metadata_extra=dict(metadata_extra) if metadata_extra else {},
    )
    db.add(usage)
    await db.flush()
    return usage


async def get_usage_summary(
    db: AsyncSession,
    org_id: uuid.UUID,
    days: int = 30,
) -> dict:
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    stmt = text("""
        SELECT provider, model,
               SUM(prompt_tokens) AS total_prompt,
               SUM(completion_tokens) AS total_completion,
               SUM(total_tokens) AS total_tokens,
               SUM(cost_usd) AS total_cost,
               COUNT(*) AS request_count
        FROM token_usage
        WHERE org_id = :org_id AND created_at >= :cutoff::timestamp
        GROUP BY provider, model
        ORDER BY SUM(cost_usd) DESC
    """)

    result = await db.execute(stmt, {"org_id": org_id, "cutoff": cutoff})
    rows = result.all()

    summaries = []
    total_cost = 0.0
    total_tokens_all = 0
    for row in rows:
        cost = float(row.total_cost or 0)
        tokens = int(row.total_tokens or 0)
        total_cost += cost
        total_tokens_all += tokens
        summaries.append({
            "provider": row.provider,
            "model": row.model,
            "total_prompt_tokens": int(row.total_prompt or 0),
            "total_completion_tokens": int(row.total_completion or 0),
            "total_tokens": tokens,
            "total_cost_usd": cost,
            "request_count": int(row.request_count or 0),
        })

    return {
        "period": f"last_{days}_days",
        "summaries": summaries,
        "total_cost_usd": round(total_cost, 4),
        "total_tokens": total_tokens_all,
    }
