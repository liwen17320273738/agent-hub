"""
Workspace API — CRUD + member management with RBAC.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..models.workspace import Workspace, WorkspaceMember
from ..models.user import User
from ..security import get_current_user, get_current_user_optional

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class CreateWorkspaceRequest(BaseModel):
    name: str
    description: str = ""


class AddMemberRequest(BaseModel):
    user_id: str
    role: str = "member"


class UpdateMemberRequest(BaseModel):
    role: str


def _ws_dict(ws: Workspace, members: list = None) -> dict:
    d = {
        "id": str(ws.id),
        "org_id": str(ws.org_id),
        "name": ws.name,
        "description": ws.description,
        "is_default": ws.is_default,
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
    }
    if members is not None:
        d["members"] = [
            {
                "id": str(m.id),
                "user_id": str(m.user_id),
                "role": m.role,
                "joined_at": m.joined_at.isoformat() if m.joined_at else None,
            }
            for m in members
        ]
    return d


@router.get("/")
async def list_workspaces(
    user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    if user is None:
        return []
    result = await db.execute(
        select(Workspace)
        .where(Workspace.org_id == user.org_id)
        .order_by(Workspace.created_at)
    )
    workspaces = result.scalars().all()
    return [_ws_dict(ws) for ws in workspaces]


@router.post("/", status_code=201)
async def create_workspace(
    body: CreateWorkspaceRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="只有 admin 或 manager 可创建工作区")

    ws = Workspace(
        org_id=user.org_id,
        name=body.name.strip(),
        description=body.description.strip(),
    )
    db.add(ws)
    await db.flush()

    member = WorkspaceMember(
        workspace_id=ws.id,
        user_id=user.id,
        role="admin",
    )
    db.add(member)
    await db.flush()
    return _ws_dict(ws, [member])


@router.get("/{ws_id}")
async def get_workspace(
    ws_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.execute(
        select(Workspace)
        .options(selectinload(Workspace.members))
        .where(Workspace.id == uuid.UUID(ws_id))
        .where(Workspace.org_id == user.org_id)
    )
    ws = row.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return _ws_dict(ws, ws.members)


@router.post("/{ws_id}/members", status_code=201)
async def add_member(
    ws_id: str,
    body: AddMemberRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ws = await _get_ws_or_404(db, ws_id, user.org_id)
    await _require_ws_admin(db, ws.id, user.id)

    if body.role not in ("admin", "manager", "member"):
        raise HTTPException(status_code=400, detail="角色必须是 admin/manager/member")

    existing = await db.execute(
        select(WorkspaceMember)
        .where(WorkspaceMember.workspace_id == ws.id)
        .where(WorkspaceMember.user_id == uuid.UUID(body.user_id))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="成员已存在")

    member = WorkspaceMember(
        workspace_id=ws.id,
        user_id=uuid.UUID(body.user_id),
        role=body.role,
    )
    db.add(member)
    await db.flush()
    return {"id": str(member.id), "user_id": body.user_id, "role": body.role}


@router.put("/{ws_id}/members/{member_user_id}")
async def update_member_role(
    ws_id: str,
    member_user_id: str,
    body: UpdateMemberRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ws = await _get_ws_or_404(db, ws_id, user.org_id)
    await _require_ws_admin(db, ws.id, user.id)

    if body.role not in ("admin", "manager", "member"):
        raise HTTPException(status_code=400, detail="角色必须是 admin/manager/member")

    row = await db.execute(
        select(WorkspaceMember)
        .where(WorkspaceMember.workspace_id == ws.id)
        .where(WorkspaceMember.user_id == uuid.UUID(member_user_id))
    )
    member = row.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")

    member.role = body.role
    await db.flush()
    return {"ok": True, "user_id": member_user_id, "role": body.role}


@router.delete("/{ws_id}/members/{member_user_id}")
async def remove_member(
    ws_id: str,
    member_user_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ws = await _get_ws_or_404(db, ws_id, user.org_id)
    await _require_ws_admin(db, ws.id, user.id)

    row = await db.execute(
        select(WorkspaceMember)
        .where(WorkspaceMember.workspace_id == ws.id)
        .where(WorkspaceMember.user_id == uuid.UUID(member_user_id))
    )
    member = row.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="成员不存在")

    await db.delete(member)
    await db.flush()
    return {"ok": True}


async def _get_ws_or_404(db: AsyncSession, ws_id: str, org_id) -> Workspace:
    row = await db.execute(
        select(Workspace)
        .where(Workspace.id == uuid.UUID(ws_id))
        .where(Workspace.org_id == org_id)
    )
    ws = row.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return ws


async def _require_ws_admin(db: AsyncSession, ws_id, user_id):
    row = await db.execute(
        select(WorkspaceMember)
        .where(WorkspaceMember.workspace_id == ws_id)
        .where(WorkspaceMember.user_id == user_id)
    )
    member = row.scalar_one_or_none()
    if not member or member.role != "admin":
        raise HTTPException(status_code=403, detail="需要工作区管理员权限")
