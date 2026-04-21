"""ORM models for the learning loop — failure signals + prompt overrides."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, Float, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..compat import GUID, JsonDict, utcnow_default


class LearningSignal(Base):
    """One row per stage outcome that the learning loop should consider:
    REJECT (peer reviewer said no), GATE_FAIL (quality gate missed), RETRY,
    APPROVE_AFTER_RETRY (treated as a positive signal for the corrected prompt),
    HUMAN_OVERRIDE (human flipped the auto-decision).
    """
    __tablename__ = "learning_signals"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    stage_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(100), default="")

    signal_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="info")  # info|warn|error

    reviewer: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    reviewer_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    metadata_extra: Mapped[dict] = mapped_column(JsonDict(), default=dict)

    distilled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    distilled_into_id: Mapped[Optional[uuid.UUID]] = mapped_column(GUID(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default(), index=True)


class PromptOverride(Base):
    """A learned addendum injected into a stage's system prompt at runtime.

    Lifecycle:
        proposed -> active -> archived (by user) | superseded (by next version)
    Can also be `disabled` at runtime by user (kept for audit, not injected).
    """
    __tablename__ = "prompt_overrides"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    stage_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(100), default="")

    title: Mapped[str] = mapped_column(String(200), default="")
    addendum: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="proposed", index=True)
    auto_apply: Mapped[bool] = mapped_column(Boolean, default=False)

    sample_signal_ids: Mapped[list] = mapped_column(JsonDict(), default=list)
    distilled_from_n: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(GUID(), nullable=True)

    activated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    activated_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    impact_uses: Mapped[int] = mapped_column(Integer, default=0)
    impact_approves: Mapped[int] = mapped_column(Integer, default=0)
    impact_rejects: Mapped[int] = mapped_column(Integer, default=0)

    # Targeting: optional segment filter for shadow / active overrides.
    # When non-empty, the override is only injected when the runtime
    # context matches. Schema:
    #   {"templates": ["full","fast"], "complexities": ["simple","medium"]}
    # Missing keys / empty lists = match-anything for that dimension.
    # Default empty dict = legacy behaviour (matches everything).
    targeting: Mapped[dict] = mapped_column(JsonDict(), default=dict)

    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=utcnow_default(), onupdate=datetime.utcnow,
    )

    __table_args__ = (
        Index("ix_prompt_overrides_stage_status", "stage_id", "status"),
    )
