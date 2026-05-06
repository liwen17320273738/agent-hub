"""
Workspace model — sub-unit of Org for resource isolation.

Org 1-* Workspace 1-* WorkspaceMember
Resources (task/workflow/etc.) get nullable workspace_id FK.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from ..compat import GUID, utcnow_default


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("orgs.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(1000), default="")
    is_default: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())
    updated_at: Mapped[datetime] = mapped_column(server_default=utcnow_default(), onupdate=datetime.utcnow)

    members: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan",
    )


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_ws_member"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"),
    )
    role: Mapped[str] = mapped_column(String(20), default="member")
    joined_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())

    workspace: Mapped[Workspace] = relationship(back_populates="members")
