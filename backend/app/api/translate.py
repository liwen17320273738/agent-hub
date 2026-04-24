"""REST API for runtime translation of dynamic content.

Two shapes:
  POST /api/translate           → single string { text, target } → { text }
  POST /api/translate/batch     → { texts: [...], target } → { texts: [...] }

Both require auth (same as every other API in this project) and are
rate-limited via the global RateLimitMiddleware.

Frontend composable (src/composables/useAutoTranslate.ts) wraps these so
Vue components can declaratively render auto-translated text with no
manual cache handling.
"""
from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..models.user import User
from ..security import get_current_user
from ..services.translator import (
    SUPPORTED_TARGETS,
    cache_stats,
    translate_batch,
    translate_text,
)

router = APIRouter(prefix="/api/translate", tags=["translate"])


class TranslateReq(BaseModel):
    text: str = Field(..., max_length=4000)
    target: str = Field(..., description="Target locale: en|ja|ko|zh")


class TranslateResp(BaseModel):
    text: str
    target: str


class TranslateBatchReq(BaseModel):
    texts: List[str] = Field(..., max_length=100)
    target: str


class TranslateBatchResp(BaseModel):
    texts: List[str]
    target: str


def _validate_target(target: str) -> str:
    if target not in SUPPORTED_TARGETS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported target locale: {target}. "
                   f"Supported: {sorted(SUPPORTED_TARGETS)}",
        )
    return target


@router.post("", response_model=TranslateResp)
async def translate_single(
    req: TranslateReq,
    _user: Annotated[User, Depends(get_current_user)],
) -> TranslateResp:
    target = _validate_target(req.target)
    out = await translate_text(req.text, target)
    return TranslateResp(text=out, target=target)


@router.post("/batch", response_model=TranslateBatchResp)
async def translate_many(
    req: TranslateBatchReq,
    _user: Annotated[User, Depends(get_current_user)],
) -> TranslateBatchResp:
    target = _validate_target(req.target)
    outs = await translate_batch(req.texts, target)
    return TranslateBatchResp(texts=outs, target=target)


@router.get("/stats")
async def translate_cache_stats(
    _user: Annotated[User, Depends(get_current_user)],
) -> dict:
    return cache_stats()
