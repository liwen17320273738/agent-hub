"""Token usage tracking and cost analysis."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.model_provider import TokenUsage

PRICING_PER_1K: Dict[str, Dict[str, Tuple[float, float]]] = {
    "openai": {
        "gpt-4o": (0.0025, 0.01),
        "gpt-4o-mini": (0.00015, 0.0006),
        "gpt-4.5": (0.075, 0.15),
        "gpt-4.1-mini": (0.0004, 0.0016),
    },
    "anthropic": {
        "claude-sonnet-4-20250514": (0.003, 0.015),
        "claude-opus-4-20250514": (0.015, 0.075),
    },
    "deepseek": {
        "deepseek-chat": (0.00014, 0.00028),
        "deepseek-reasoner": (0.00055, 0.0022),
    },
    "google": {
        "gemini-2.5-pro": (0.00125, 0.01),
        "gemini-2.5-flash": (0.00015, 0.0006),
    },
    "zhipu": {
        "glm-4-plus": (0.0007, 0.0007),
        "glm-4-flash": (0.0001, 0.0001),
    },
    "qwen": {
        "qwen-turbo": (0.00003, 0.00006),
        "qwen-plus": (0.00056, 0.00168),
        "qwen-max": (0.0016, 0.0064),
    },
}


def estimate_cost(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    prices = PRICING_PER_1K.get(provider, {})
    matched = None
    for model_key in prices:
        if model_key in model:
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
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    agent_id: Optional[str],
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int = 0,
    endpoint: str = "chat",
) -> TokenUsage:
    total = prompt_tokens + completion_tokens
    cost = estimate_cost(provider, model, prompt_tokens, completion_tokens)

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
    )
    db.add(usage)
    await db.flush()
    return usage


async def get_usage_summary(
    db: AsyncSession,
    org_id: uuid.UUID,
    days: int = 30,
) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    stmt = (
        select(
            TokenUsage.provider,
            TokenUsage.model,
            func.sum(TokenUsage.prompt_tokens).label("total_prompt"),
            func.sum(TokenUsage.completion_tokens).label("total_completion"),
            func.sum(TokenUsage.total_tokens).label("total_tokens"),
            func.sum(TokenUsage.cost_usd).label("total_cost"),
            func.count().label("request_count"),
        )
        .where(TokenUsage.org_id == org_id, TokenUsage.created_at >= cutoff)
        .group_by(TokenUsage.provider, TokenUsage.model)
        .order_by(func.sum(TokenUsage.cost_usd).desc())
    )

    result = await db.execute(stmt)
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
