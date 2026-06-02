"""
Outcome Contract — Wave 1 of route B (accountable AI delivery).

Three tables form the cornerstone of the "we refund if metrics aren't met"
business model:

* ``outcome_contracts`` — the signed agreement between customer and the AI
  team. Stores the business goal, measurable success metrics, refund policy,
  and verification plan (typically 30 / 60 / 90 day checkpoints).
* ``outcome_metric_readings`` — time-series of metric values, either pushed
  manually by the customer (with screenshot evidence) or pulled from an
  external system (GA, Stripe, Plausible, internal PG view).
* ``outcome_checkpoints`` — record of each verification event: at day N the
  agent runs through the metrics, compares against targets, and writes a
  verdict (passed / failed / partial). The checkpoint outcome decides
  whether to fulfill, refund, or re-iterate.

Relationships:

    PipelineTask 1—1 OutcomeContract 1—* OutcomeMetricReading
                                   1—* OutcomeCheckpoint

The contract is created BEFORE the pipeline starts (during the Clarify
gate). Its existence is the entry condition for the rest of the pipeline.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..compat import GUID, JsonDict, utcnow_default, utcnow_callable
from ..database import Base

# ── Allowed enum values (validated at API layer, stored as plain strings
#    for cross-database portability — SQLite has no native enums).
CONTRACT_STATUS_VALUES = (
    "draft",            # agent has drafted, not yet sent to customer
    "proposed",         # sent to customer, awaiting signature
    "signed",           # customer has signed; pipeline can proceed
    "in_delivery",      # delivery in progress
    "verifying",        # delivered, checkpoint(s) running
    "fulfilled",        # all checkpoints passed
    "breached",         # one or more checkpoints failed
    "refunded",         # refund issued per policy
    "cancelled",        # cancelled before signing or by mutual consent
)

REFUND_POLICY_VALUES = (
    "full",             # 100% refund if any checkpoint fails
    "partial_50",       # 50% refund
    "partial_30",       # 30% refund
    "no_refund",        # delivery only, no money-back
)

METRIC_DIRECTION_VALUES = ("increase", "decrease", "reach")

METRIC_SOURCE_VALUES = (
    "manual",           # customer enters value with screenshot
    "google_analytics",
    "plausible",
    "posthog",
    "mixpanel",
    "stripe",
    "internal_db",      # query against customer's read-replica
    "webhook",          # customer pushes via webhook
)

CHECKPOINT_VERDICT_VALUES = ("pending", "passed", "failed", "partial", "skipped")


class OutcomeContract(Base):
    """The signed agreement between customer and the AI delivery team.

    One-to-one with ``PipelineTask`` (a task may not have a contract — that's
    the legacy "no money-back" path — but a contract always has a task).
    """

    __tablename__ = "outcome_contracts"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("pipeline_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── The "why" — a paragraph in the customer's own words about what
    #    success looks like for THEIR business.
    business_goal: Mapped[str] = mapped_column(Text, default="")

    # ── Success metrics — JSON list of metric definitions:
    #    [{"name": "weekly_active_users", "source": "plausible",
    #      "target_value": 500, "direction": "increase",
    #      "measurement_window_days": 30, "baseline_value": 100}, ...]
    success_metrics: Mapped[list] = mapped_column(JsonDict(), default=list, nullable=False)

    # ── Refund policy & threshold
    refund_policy: Mapped[str] = mapped_column(String(20), default="full")
    # JSON: {"trigger": "any_metric_failed" | "all_metrics_failed" | "ratio_below",
    #        "ratio": 0.5}  — when does refund kick in
    refund_trigger: Mapped[dict] = mapped_column(JsonDict(), default=dict, nullable=False)

    # ── Verification plan — JSON list of checkpoints:
    #    [{"day": 30, "method": "auto_metric_check"},
    #     {"day": 60, "method": "auto_metric_check"},
    #     {"day": 90, "method": "customer_survey"}]
    verification_plan: Mapped[list] = mapped_column(JsonDict(), default=list, nullable=False)

    # ── Pricing (informational; actual payment handled out-of-band for now)
    price_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    deposit_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delivery_deadline: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # ── State machine
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)

    # ── Signatures (lightweight — actual eSign is a Year-2 problem)
    drafted_by_agent: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    drafted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    signed_by_customer: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    signed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    customer_signature_meta: Mapped[dict] = mapped_column(JsonDict(), default=dict, nullable=False)

    # ── Outcome (populated after final checkpoint)
    fulfilled_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    breached_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    refunded_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    refund_amount_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ── Free-form notes (rationale, manual overrides, customer comments)
    notes: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(
        default=utcnow_callable, server_default=utcnow_default(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=utcnow_callable,
        server_default=utcnow_default(),
        onupdate=utcnow_callable,
    )

    readings: Mapped[list["OutcomeMetricReading"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan",
    )
    checkpoints: Mapped[list["OutcomeCheckpoint"]] = relationship(
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="OutcomeCheckpoint.day_offset",
    )

    __table_args__ = (
        UniqueConstraint("task_id", name="uq_outcome_contract_task"),
        Index("ix_outcome_contracts_workspace_status", "workspace_id", "status"),
        Index("ix_outcome_contracts_status_created", "status", "created_at"),
    )


class OutcomeMetricReading(Base):
    """A single (timestamp, metric_name, value) datapoint.

    Multiple readings per metric get aggregated by checkpoints when computing
    pass/fail (typically: average over measurement_window_days, or latest
    reading, depending on metric semantics).
    """

    __tablename__ = "outcome_metric_readings"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("outcome_contracts.id", ondelete="CASCADE"),
        nullable=False,
    )

    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="manual")

    # ── Evidence — when source == "manual", customer must attach a screenshot
    #    or link. When source is automated, we store the raw API response
    #    here for audit.
    evidence_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    evidence_meta: Mapped[dict] = mapped_column(JsonDict(), default=dict, nullable=False)

    recorded_by: Mapped[str] = mapped_column(String(200), default="system")
    recorded_at: Mapped[datetime] = mapped_column(
        default=utcnow_callable,
        server_default=utcnow_default(),
        index=True,
    )

    contract: Mapped[OutcomeContract] = relationship(back_populates="readings")

    __table_args__ = (
        Index("ix_outcome_readings_contract_metric", "contract_id", "metric_name"),
        Index("ix_outcome_readings_contract_recorded", "contract_id", "recorded_at"),
    )


class OutcomeCheckpoint(Base):
    """A verification event at day N — comparing actual metrics vs targets.

    Created from the contract's ``verification_plan`` at signing time. Each
    checkpoint either passes (all metrics meet target), fails (refund
    triggered), or comes back partial (re-iteration negotiation).
    """

    __tablename__ = "outcome_checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("outcome_contracts.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Day N relative to signing date (30 / 60 / 90 are typical).
    day_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(30), default="auto_metric_check")

    scheduled_for: Mapped[datetime] = mapped_column(nullable=False, index=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # ── Verdict
    verdict: Mapped[str] = mapped_column(String(20), default="pending")
    # JSON: per-metric pass/fail breakdown
    # [{"metric": "wau", "target": 500, "actual": 423, "passed": false,
    #   "ratio": 0.846}, ...]
    metric_results: Mapped[list] = mapped_column(JsonDict(), default=list, nullable=False)

    # Human-readable summary stored on the checkpoint for the share page
    # ("3 of 4 metrics passed; conversion fell short by 14%").
    summary: Mapped[str] = mapped_column(Text, default="")

    # If the verdict triggers a refund, this row links to the refund record
    # (a future ``refunds`` table — for now, just a free-form reference).
    refund_decision: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        default=utcnow_callable, server_default=utcnow_default(),
    )

    contract: Mapped[OutcomeContract] = relationship(back_populates="checkpoints")

    __table_args__ = (
        UniqueConstraint(
            "contract_id", "day_offset", name="uq_checkpoint_contract_day",
        ),
        Index("ix_outcome_checkpoints_verdict", "verdict"),
    )


__all__ = [
    "OutcomeContract",
    "OutcomeMetricReading",
    "OutcomeCheckpoint",
    "CONTRACT_STATUS_VALUES",
    "REFUND_POLICY_VALUES",
    "METRIC_DIRECTION_VALUES",
    "METRIC_SOURCE_VALUES",
    "CHECKPOINT_VERDICT_VALUES",
]
