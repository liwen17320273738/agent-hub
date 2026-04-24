from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String, Text, Boolean, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..compat import GUID, JsonDict, utcnow_default


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    author: Mapped[str] = mapped_column(String(100), default="system")

    prompt_template: Mapped[str] = mapped_column(Text, default="")
    input_schema: Mapped[dict] = mapped_column(JsonDict(), default=dict)
    output_schema: Mapped[dict] = mapped_column(JsonDict(), default=dict)
    config: Mapped[dict] = mapped_column(JsonDict(), default=dict)
    tags: Mapped[list] = mapped_column(JsonDict(), default=list)

    rules: Mapped[list] = mapped_column(JsonDict(), default=list)
    hooks: Mapped[list] = mapped_column(JsonDict(), default=list)
    plugins: Mapped[list] = mapped_column(JsonDict(), default=list)
    mcp_tools: Mapped[list] = mapped_column(JsonDict(), default=list)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    install_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())
    updated_at: Mapped[datetime] = mapped_column(server_default=utcnow_default(), onupdate=datetime.utcnow)


class SkillRating(Base):
    """One rating per (skill, user). Aggregated into avg_stars / rating_count
    when the marketplace endpoint lists skills."""

    __tablename__ = "skill_ratings"
    __table_args__ = (
        UniqueConstraint("skill_id", "user_id", name="uq_skill_ratings_skill_user"),
        Index("ix_skill_ratings_skill_id", "skill_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    skill_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    stars: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..5
    comment: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=utcnow_default(),
        onupdate=datetime.utcnow,
    )
