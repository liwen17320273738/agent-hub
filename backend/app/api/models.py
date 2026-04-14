"""Real-time model listing and token usage endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..security import get_current_user
from ..services.model_registry import fetch_all_models, clear_model_cache
from ..services.token_tracker import get_usage_summary

router = APIRouter(prefix="/models", tags=["models"])


@router.get("/live")
async def list_live_models(user: Annotated[User, Depends(get_current_user)]):
    """Fetch latest available models from all configured providers (cached in Redis)."""
    provider_models = await fetch_all_models()
    total = sum(len(models) for models in provider_models.values())
    return {"providers": provider_models, "total": total}


@router.post("/refresh")
async def refresh_models(user: Annotated[User, Depends(get_current_user)]):
    """Clear model cache and fetch fresh data."""
    await clear_model_cache()
    provider_models = await fetch_all_models()
    total = sum(len(models) for models in provider_models.values())
    return {"providers": provider_models, "total": total, "refreshed": True}


@router.get("/usage")
async def token_usage(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = 30,
):
    """Get token usage summary for the organization."""
    return await get_usage_summary(db, user.org_id, days=days)
