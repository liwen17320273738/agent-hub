"""Relay gateway: customer API keys, org wallet debit, usage attribution."""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.relay import RelayApiKey
from ..models.user import Org
from .token_tracker import estimate_cost, record_usage

RELAY_KEY_PREFIX = "ahrelay_"
AuthKind = Literal["pipeline", "relay"]


@dataclass(frozen=True)
class RelayAuthContext:
    key_id: UUID
    org_id: UUID
    user_id: UUID


def hash_relay_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def generate_relay_key_plaintext() -> str:
    return f"{RELAY_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def relay_charge_amount(base_cost_usd: float) -> float:
    mult = max(0.0, float(settings.relay_markup_multiplier or 1.0))
    return round(max(0.0, base_cost_usd) * mult, 6)


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts)
    return str(content or "")


def rough_prompt_tokens(messages: List[Dict[str, Any]]) -> int:
    total = 0
    for msg in messages:
        text = _message_text(msg.get("content"))
        total += max(1, len(text) // 4)
    return max(total, 1)


async def resolve_openai_compat_bearer(
    db: AsyncSession,
    token: str,
) -> Tuple[AuthKind, Optional[RelayAuthContext]]:
    if not token:
        raise HTTPException(status_code=401, detail="Missing API key")

    if settings.pipeline_api_key and secrets.compare_digest(token, settings.pipeline_api_key):
        return "pipeline", None

    digest = hash_relay_key(token)
    stmt = select(RelayApiKey).where(
        RelayApiKey.key_hash == digest,
        RelayApiKey.revoked_at.is_(None),
    )
    res = await db.execute(stmt)
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return "relay", RelayAuthContext(
        key_id=row.id,
        org_id=row.org_id,
        user_id=row.created_by_user_id,
    )


async def require_relay_balance(db: AsyncSession, org_id: UUID) -> None:
    org = await db.get(Org, org_id)
    if org is None:
        raise HTTPException(status_code=403, detail="Organization not found")
    bal = float(org.relay_balance_usd or 0.0)
    min_b = float(settings.relay_min_balance_usd or 0.0)
    if bal <= min_b:
        raise HTTPException(
            status_code=402,
            detail="Insufficient relay balance — top up in the console (API: POST /api/relay/balance/topup).",
        )


async def touch_relay_key_used(db: AsyncSession, key_id: UUID) -> None:
    row = await db.get(RelayApiKey, key_id)
    if row is None:
        return
    row.last_used_at = datetime.now(timezone.utc)


async def debit_relay_and_record(
    db: AsyncSession,
    *,
    ctx: RelayAuthContext,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int = 0,
) -> None:
    base = estimate_cost(provider, model, prompt_tokens, completion_tokens)
    total_tok = max(0, prompt_tokens + completion_tokens)
    fb = float(getattr(settings, "relay_fallback_usd_per_1k_total", 0.0) or 0.0)
    used_fallback = False
    if base <= 0 and fb > 0 and total_tok > 0:
        base = round((total_tok / 1000.0) * fb, 6)
        used_fallback = True
    charged = relay_charge_amount(base)
    org = await db.get(Org, ctx.org_id)
    if org is None:
        return
    if charged > 0:
        org.relay_balance_usd = round(float(org.relay_balance_usd or 0.0) - charged, 6)

    extra: Dict[str, Any] = {
        "relay_key_id": str(ctx.key_id),
        "relay_base_cost_usd": base,
        "relay_charged_usd": charged,
    }
    if used_fallback:
        extra["relay_pricing_fallback"] = True

    await record_usage(
        db,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        agent_id=None,
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        endpoint="relay_openai",
        metadata_extra=extra,
        cost_usd_override=base,
    )


async def settle_relay_stream_usage(
    db: AsyncSession,
    *,
    ctx: RelayAuthContext,
    model: str,
    messages: List[Dict[str, Any]],
    assistant_text: str,
    provider: str,
    latency_ms: int = 0,
) -> None:
    pt = rough_prompt_tokens(messages)
    ct = max(1, len(assistant_text) // 4)
    await debit_relay_and_record(
        db,
        ctx=ctx,
        provider=provider or "unknown",
        model=model,
        prompt_tokens=pt,
        completion_tokens=ct,
        latency_ms=latency_ms,
    )
