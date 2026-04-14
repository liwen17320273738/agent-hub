"""Skill center: CRUD for skills + assignment to agents."""
from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.skill import Skill
from ..models.user import User
from ..schemas.skill import SkillOut, SkillCreate, SkillUpdate
from ..security import get_current_user, require_admin

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("/", response_model=List[SkillOut])
async def list_skills(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category: Optional[str] = None,
):
    stmt = select(Skill).order_by(Skill.sort_order)
    if category:
        stmt = stmt.where(Skill.category == category)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{skill_id}", response_model=SkillOut)
async def get_skill(
    skill_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")
    return skill


@router.post("/", response_model=SkillOut, status_code=201)
async def create_skill(
    body: SkillCreate,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    existing = await db.get(Skill, body.id)
    if existing:
        raise HTTPException(status_code=409, detail="技能 ID 已存在")

    skill = Skill(**body.model_dump(), author="admin", is_builtin=False)
    db.add(skill)
    await db.flush()
    return skill


@router.patch("/{skill_id}", response_model=SkillOut)
async def update_skill(
    skill_id: str,
    body: SkillUpdate,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(skill, field, value)
    await db.flush()
    return skill


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: str,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")
    if skill.is_builtin:
        raise HTTPException(status_code=400, detail="内置技能不可删除")
    await db.delete(skill)
    return {"ok": True}


# --- Marketplace ---

@router.get("/marketplace/catalog")
async def marketplace_catalog(
    user: Annotated[User, Depends(get_current_user)],
):
    from ..services.skill_marketplace import get_marketplace_catalog
    catalog = await get_marketplace_catalog()
    return {"catalog": catalog, "total": len(catalog)}


@router.post("/marketplace/install/{skill_id}")
async def marketplace_install(
    skill_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from ..services.skill_marketplace import install_skill
    skill = await install_skill(db, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="技能不在市场中")
    return {"ok": True, "skill": {"id": skill.id, "name": skill.name, "version": skill.version}}


class ExecuteSkillRequest(BaseModel):
    input_data: dict = {}
    model: str = ""
    timeout_seconds: int = 300


@router.post("/{skill_id}/execute")
async def execute_skill_endpoint(
    skill_id: str,
    body: ExecuteSkillRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from ..services.skill_marketplace import execute_skill
    result = await execute_skill(
        db,
        skill_id=skill_id,
        input_data=body.input_data,
        model=body.model,
        timeout_seconds=body.timeout_seconds,
    )
    return result
