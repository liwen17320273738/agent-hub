"""add outcome contract tables (route B, Wave 1)

Revision ID: x0y1z2a3b4c5
Revises: w9x0y1z2a3b4
Create Date: 2026-05-25

Three new tables for the "accountable AI delivery" business model:

* ``outcome_contracts`` — signed agreement (goal, metrics, refund policy,
  verification plan).
* ``outcome_metric_readings`` — time-series of metric values.
* ``outcome_checkpoints`` — verification events at day N with verdict.

All three tables are cross-database (PG + SQLite). Stage-string enums are
stored as plain ``String`` columns rather than native ENUM types for
portability.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "x0y1z2a3b4c5"
down_revision = "w9x0y1z2a3b4"
branch_labels = None
depends_on = None


def _guid_type(bind) -> sa.types.TypeEngine:
    """Return the right UUID-ish type for the dialect."""
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import UUID as PG_UUID
        return PG_UUID(as_uuid=True)
    return sa.String(36)


def _json_type(bind) -> sa.types.TypeEngine:
    """Return JSONB on PG, JSON elsewhere."""
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB
        return JSONB()
    return sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    guid = _guid_type(bind)
    jsn = _json_type(bind)

    # ── outcome_contracts ─────────────────────────────────────────────
    op.create_table(
        "outcome_contracts",
        sa.Column("id", guid, primary_key=True),
        sa.Column(
            "task_id", guid,
            sa.ForeignKey("pipeline_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id", guid,
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("business_goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("success_metrics", jsn, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("refund_policy", sa.String(20), nullable=False, server_default="full"),
        sa.Column("refund_trigger", jsn, nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "verification_plan", jsn, nullable=False, server_default=sa.text("'[]'"),
        ),
        sa.Column("price_usd", sa.Float(), nullable=True),
        sa.Column("deposit_pct", sa.Float(), nullable=True),
        sa.Column("delivery_deadline", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("drafted_by_agent", sa.String(100), nullable=True),
        sa.Column("drafted_at", sa.DateTime(), nullable=True),
        sa.Column("signed_by_customer", sa.String(200), nullable=True),
        sa.Column("signed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "customer_signature_meta", jsn, nullable=False, server_default=sa.text("'{}'"),
        ),
        sa.Column("fulfilled_at", sa.DateTime(), nullable=True),
        sa.Column("breached_at", sa.DateTime(), nullable=True),
        sa.Column("refunded_at", sa.DateTime(), nullable=True),
        sa.Column("refund_amount_usd", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint("task_id", name="uq_outcome_contract_task"),
    )
    op.create_index(
        "ix_outcome_contracts_workspace_status",
        "outcome_contracts", ["workspace_id", "status"],
    )
    op.create_index(
        "ix_outcome_contracts_status_created",
        "outcome_contracts", ["status", "created_at"],
    )
    op.create_index(
        "ix_outcome_contracts_status",
        "outcome_contracts", ["status"],
    )

    # ── outcome_metric_readings ───────────────────────────────────────
    op.create_table(
        "outcome_metric_readings",
        sa.Column("id", guid, primary_key=True),
        sa.Column(
            "contract_id", guid,
            sa.ForeignKey("outcome_contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_name", sa.String(100), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("source", sa.String(30), nullable=False, server_default="manual"),
        sa.Column("evidence_url", sa.String(1000), nullable=True),
        sa.Column(
            "evidence_meta", jsn, nullable=False, server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "recorded_by", sa.String(200), nullable=False, server_default="system",
        ),
        sa.Column(
            "recorded_at", sa.DateTime(), server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        "ix_outcome_readings_contract_metric",
        "outcome_metric_readings", ["contract_id", "metric_name"],
    )
    op.create_index(
        "ix_outcome_readings_contract_recorded",
        "outcome_metric_readings", ["contract_id", "recorded_at"],
    )

    # ── outcome_checkpoints ───────────────────────────────────────────
    op.create_table(
        "outcome_checkpoints",
        sa.Column("id", guid, primary_key=True),
        sa.Column(
            "contract_id", guid,
            sa.ForeignKey("outcome_contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day_offset", sa.Integer(), nullable=False),
        sa.Column(
            "method", sa.String(30), nullable=False, server_default="auto_metric_check",
        ),
        sa.Column("scheduled_for", sa.DateTime(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.Column("verdict", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "metric_results", jsn, nullable=False, server_default=sa.text("'[]'"),
        ),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("refund_decision", sa.String(20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint(
            "contract_id", "day_offset", name="uq_checkpoint_contract_day",
        ),
    )
    op.create_index(
        "ix_outcome_checkpoints_scheduled",
        "outcome_checkpoints", ["scheduled_for"],
    )
    op.create_index(
        "ix_outcome_checkpoints_verdict",
        "outcome_checkpoints", ["verdict"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outcome_checkpoints_verdict", table_name="outcome_checkpoints",
    )
    op.drop_index(
        "ix_outcome_checkpoints_scheduled", table_name="outcome_checkpoints",
    )
    op.drop_table("outcome_checkpoints")

    op.drop_index(
        "ix_outcome_readings_contract_recorded", table_name="outcome_metric_readings",
    )
    op.drop_index(
        "ix_outcome_readings_contract_metric", table_name="outcome_metric_readings",
    )
    op.drop_table("outcome_metric_readings")

    op.drop_index(
        "ix_outcome_contracts_status", table_name="outcome_contracts",
    )
    op.drop_index(
        "ix_outcome_contracts_status_created", table_name="outcome_contracts",
    )
    op.drop_index(
        "ix_outcome_contracts_workspace_status", table_name="outcome_contracts",
    )
    op.drop_table("outcome_contracts")
