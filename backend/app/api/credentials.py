"""
Credentials Vault API — encrypted storage for API keys and OAuth tokens.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.credential import Credential
from ..models.user import User
from ..security import get_current_user

router = APIRouter(prefix="/credentials", tags=["credentials"])


class CreateCredentialRequest(BaseModel):
    name: str
    provider: str
    credential_type: str = "api_key"
    value: str
    workspace_id: Optional[str] = None


class UpdateCredentialRequest(BaseModel):
    name: Optional[str] = None
    value: Optional[str] = None


def _cred_dict(c: Credential) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "provider": c.provider,
        "credential_type": c.credential_type,
        "workspace_id": str(c.workspace_id) if c.workspace_id else None,
        "has_value": bool(c.encrypted_value),
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.get("/")
async def list_credentials(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Credential)
        .where(Credential.org_id == user.org_id)
        .order_by(Credential.created_at)
    )
    return [_cred_dict(c) for c in result.scalars().all()]


@router.post("/", status_code=201)
async def create_credential(
    body: CreateCredentialRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cred = Credential(
        org_id=user.org_id,
        workspace_id=uuid.UUID(body.workspace_id) if body.workspace_id else None,
        name=body.name.strip(),
        provider=body.provider.strip(),
        credential_type=body.credential_type,
        created_by=user.id,
    )
    cred.set_value(body.value)
    db.add(cred)
    await db.flush()
    return _cred_dict(cred)


@router.put("/{cred_id}")
async def update_credential(
    cred_id: str,
    body: UpdateCredentialRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.execute(
        select(Credential)
        .where(Credential.id == uuid.UUID(cred_id))
        .where(Credential.org_id == user.org_id)
    )
    cred = row.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="凭证不存在")

    if body.name is not None:
        cred.name = body.name.strip()
    if body.value is not None:
        cred.set_value(body.value)
    await db.flush()
    return _cred_dict(cred)


@router.delete("/{cred_id}")
async def delete_credential(
    cred_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.execute(
        select(Credential)
        .where(Credential.id == uuid.UUID(cred_id))
        .where(Credential.org_id == user.org_id)
    )
    cred = row.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="凭证不存在")

    await db.delete(cred)
    await db.flush()
    return {"ok": True}
