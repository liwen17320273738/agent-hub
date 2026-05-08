"""Manage relay API keys and org balance for the OpenAI-compatible /v1 gateway."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..config import settings
from ..models.relay import RelayApiKey
from ..models.user import Org, User
from ..security import get_current_user
from ..services.relay_billing import generate_relay_key_plaintext, hash_relay_key

router = APIRouter(prefix="/relay", tags=["relay"])


class RelayKeyCreate(BaseModel):
    name: str = Field(default="", max_length=100)


class RelayKeyPublic(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None


class RelayKeyCreated(RelayKeyPublic):
    plaintext_key: str


class TopUpBody(BaseModel):
    amount_usd: float = Field(gt=0, le=1_000_000)


class BalanceOut(BaseModel):
    relay_balance_usd: float


class RelayPolicyOut(BaseModel):
    markup_multiplier: float
    fallback_usd_per_1k_total: float
    min_balance_usd: float
    rate_limit_per_minute: int


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.isoformat()


@router.get("/policy", response_model=RelayPolicyOut)
async def relay_policy(_user: Annotated[User, Depends(get_current_user)]):
    """Non-secret billing parameters for the OpenAI-compatible relay (JWT)."""
    rrl = settings.relay_rate_limit_per_minute
    eff_rl = int(rrl) if rrl is not None else int(settings.rate_limit_per_minute)
    return RelayPolicyOut(
        markup_multiplier=float(settings.relay_markup_multiplier or 1.0),
        fallback_usd_per_1k_total=float(settings.relay_fallback_usd_per_1k_total or 0.0),
        min_balance_usd=float(settings.relay_min_balance_usd or 0.0),
        rate_limit_per_minute=eff_rl,
    )


@router.get("/balance", response_model=BalanceOut)
async def get_balance(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    org = await db.get(Org, user.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return BalanceOut(relay_balance_usd=float(org.relay_balance_usd or 0.0))


@router.post("/balance/topup", response_model=BalanceOut)
async def topup_balance(
    body: TopUpBody,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="需要 admin 或 manager 角色才能充值")
    org = await db.get(Org, user.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    org.relay_balance_usd = round(float(org.relay_balance_usd or 0.0) + body.amount_usd, 6)
    return BalanceOut(relay_balance_usd=float(org.relay_balance_usd))


@router.post("/keys", response_model=RelayKeyCreated)
async def create_relay_key(
    body: RelayKeyCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    plain = generate_relay_key_plaintext()
    row = RelayApiKey(
        org_id=user.org_id,
        created_by_user_id=user.id,
        name=(body.name or "").strip()[:100],
        key_prefix=plain[:20],
        key_hash=hash_relay_key(plain),
    )
    db.add(row)
    await db.flush()
    return RelayKeyCreated(
        id=str(row.id),
        name=row.name,
        key_prefix=row.key_prefix,
        created_at=_iso(row.created_at),
        last_used_at=_iso(row.last_used_at),
        plaintext_key=plain,
    )


@router.get("/keys", response_model=List[RelayKeyPublic])
async def list_relay_keys(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    stmt = (
        select(RelayApiKey)
        .where(RelayApiKey.org_id == user.org_id, RelayApiKey.revoked_at.is_(None))
        .order_by(RelayApiKey.created_at.desc())
    )
    res = await db.execute(stmt)
    rows = res.scalars().all()
    return [
        RelayKeyPublic(
            id=str(r.id),
            name=r.name,
            key_prefix=r.key_prefix,
            created_at=_iso(r.created_at),
            last_used_at=_iso(r.last_used_at),
        )
        for r in rows
    ]


@router.delete("/keys/{key_id}")
async def revoke_relay_key(
    key_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = await db.get(RelayApiKey, key_id)
    if row is None or row.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="Key not found")

    row.revoked_at = datetime.now(timezone.utc)
    return {"ok": True}
