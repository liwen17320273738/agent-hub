from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from ..compat import GUID, JsonDict, utcnow_default


class PipelineTask(Base):
    __tablename__ = "pipeline_tasks"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="web")
    source_message_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    source_user_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="active")
    current_stage_id: Mapped[str] = mapped_column(String(50), default="planning")

    created_by: Mapped[str] = mapped_column(String(200), default="system")
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(GUID(), ForeignKey("orgs.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())
    updated_at: Mapped[datetime] = mapped_column(server_default=utcnow_default(), onupdate=datetime.utcnow)

    stages: Mapped[list[PipelineStage]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="PipelineStage.sort_order"
    )
    artifacts: Mapped[list[PipelineArtifact]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class PipelineStage(Base):
    __tablename__ = "pipeline_stages"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("pipeline_tasks.id", ondelete="CASCADE"), index=True)
    stage_id: Mapped[str] = mapped_column(String(50))
    label: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    owner_role: Mapped[str] = mapped_column(String(100), default="")
    output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    task: Mapped[PipelineTask] = relationship(back_populates="stages")


class PipelineArtifact(Base):
    __tablename__ = "pipeline_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("pipeline_tasks.id", ondelete="CASCADE"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    stage_id: Mapped[str] = mapped_column(String(50))
    metadata_extra: Mapped[dict] = mapped_column(JsonDict(), default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())

    task: Mapped[PipelineTask] = relationship(back_populates="artifacts")
