"""ORM models for observability — traces, spans, audit logs, approvals, feedback."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, Float, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..compat import GUID, JsonDict, utcnow_default


class TraceRecord(Base):
    """Persistent pipeline trace — survives Redis TTL expiry."""
    __tablename__ = "trace_records"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    task_id: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    task_title: Mapped[str] = mapped_column(String(500), default="")

    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[float] = mapped_column(Float, default=0.0)
    completed_at: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    total_prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    total_retries: Mapped[int] = mapped_column(Integer, default=0)

    models_used: Mapped[dict] = mapped_column(JsonDict(), default=dict)
    stage_durations: Mapped[dict] = mapped_column(JsonDict(), default=dict)

    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())


class SpanRecord(Base):
    """Persistent trace span."""
    __tablename__ = "span_records"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    span_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    trace_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    parent_span_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    task_id: Mapped[str] = mapped_column(String(200), index=True, nullable=False)

    stage_id: Mapped[str] = mapped_column(String(50), nullable=False)
    role: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), default="")
    tier: Mapped[str] = mapped_column(String(20), default="")

    status: Mapped[str] = mapped_column(String(20), default="running")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    started_at: Mapped[float] = mapped_column(Float, default=0.0)
    completed_at: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    verify_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    verify_checks: Mapped[dict] = mapped_column(JsonDict(), default=list)
    guardrail_level: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    approval_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    input_length: Mapped[int] = mapped_column(Integer, default=0)
    output_length: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_extra: Mapped[dict] = mapped_column(JsonDict(), default=dict)

    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())


class AuditLog(Base):
    """Permanent audit log — never TTL-expired, compliance-grade."""
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    stage_id: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(30), default="auto_approve")
    outcome: Mapped[str] = mapped_column(String(50), nullable=False)
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())

    __table_args__ = (
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_created_at", "created_at"),
    )


class ApprovalRecord(Base):
    """Persistent approval request — outlives Redis TTL."""
    __tablename__ = "approval_records"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    approval_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    task_id: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    stage_id: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    risk_level: Mapped[str] = mapped_column(String(30), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(200), default="system")

    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    reviewer: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    review_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    metadata_extra: Mapped[dict] = mapped_column(JsonDict(), default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class FeedbackRecord(Base):
    """Persistent feedback item — replaces in-memory FeedbackLoop storage."""
    __tablename__ = "feedback_records"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    feedback_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    task_id: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    user_id: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    feedback_type: Mapped[str] = mapped_column(String(30), default="revision")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    iteration_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
