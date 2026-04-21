from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, Float, ForeignKey
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
    template: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    repo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    project_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_by: Mapped[str] = mapped_column(String(200), default="system")
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(GUID(), ForeignKey("orgs.id"), nullable=True)

    quality_gate_config: Mapped[Optional[dict]] = mapped_column(JsonDict(), nullable=True)
    overall_quality_score: Mapped[Optional[float]] = mapped_column(nullable=True)

    # ── Final acceptance terminus ─────────────────────────────────────
    # After all stages succeed and ``compile_deliverables`` runs, the task
    # transitions to ``status="awaiting_final_acceptance"`` and parks here
    # until a human (or ``auto_final_accept=True``) calls one of the
    # ``/final-accept`` / ``/final-reject`` endpoints. See migration
    # ``5f8a9b0c1d2e_add_final_acceptance_fields`` for the column shape
    # rationale.
    final_acceptance_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    final_acceptance_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    final_acceptance_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    final_acceptance_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Bypass the human terminus — useful for CI / batch runs that want the
    # legacy "straight to done" behavior. Defaults to FALSE so existing
    # interactive flows pick up the new gate automatically.
    auto_final_accept: Mapped[Optional[bool]] = mapped_column(nullable=True, default=False)

    # Workflow Builder spec — when ``template == "custom"``, this holds the
    # verbatim DAG shape (incl. ``depends_on``, per-stage retry / gate /
    # quality config) so the orchestrator can rehydrate it without
    # re-asking the client. NULL = use the named template instead.
    custom_stages: Mapped[Optional[list]] = mapped_column(JsonDict(), nullable=True)

    # Bidirectional issue-tracker links. Stored as a JSON list of
    # ``ExternalIssueRef.to_dict()`` shapes:
    #   [{"kind": "jira",   "key": "AI-7",        "url": "...", "project": "AI"},
    #    {"kind": "github", "key": "acme/web#42", "url": "...", "project": "acme/web"}]
    # Populated by ``POST /api/integrations/tasks/{id}/links`` (manual
    # bind) or by the auto-create-on-task-creation hook (future).
    # The DAG REJECT path mirrors review verdicts back to every entry
    # here so reviewers can follow the AI in their own queue.
    external_links: Mapped[list] = mapped_column(JsonDict(), default=list, nullable=False)

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

    review_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    reviewer_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewer_agent: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    review_attempts: Mapped[int] = mapped_column(Integer, default=0)
    approval_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    verify_status: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    verify_checks: Mapped[Optional[dict]] = mapped_column(JsonDict(), nullable=True)
    quality_score: Mapped[Optional[float]] = mapped_column(nullable=True)

    gate_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    gate_score: Mapped[Optional[float]] = mapped_column(nullable=True)
    gate_details: Mapped[Optional[dict]] = mapped_column(JsonDict(), nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # ── Wave 4: collaboration loop ────────────────────────────────────
    # Last raw error string from the most recent failed execution attempt.
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # How many times this stage has been retried after a failure.
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    # Per-stage retry budget (overrides task default; 0 = no auto-retry).
    max_retries: Mapped[int] = mapped_column(Integer, default=0)
    # Behavior when this stage fails after retries are exhausted:
    #   "halt"     — stop the pipeline (default, today's behavior)
    #   "rollback" — reset this stage + downstream to pending and pause
    #   "skip"     — mark stage skipped and proceed
    on_failure: Mapped[str] = mapped_column(String(20), default="halt")
    # When True, the stage requires human approval AFTER it produces output
    # before the next stage can start (DAG-side mid-pipeline gate).
    human_gate: Mapped[bool] = mapped_column(default=False)

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
