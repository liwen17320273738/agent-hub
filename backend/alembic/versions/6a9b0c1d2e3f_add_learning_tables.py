"""Add learning_signals + prompt_overrides tables.

Revision ID: 6a9b0c1d2e3f
Revises: 5f8a9b0c1d2e
Create Date: 2026-04-21 11:00:00.000000

Wave-5 learning loop: capture every stage outcome that the loop should consider
(REJECT / GATE_FAIL / RETRY / APPROVE_AFTER_RETRY / HUMAN_OVERRIDE) and store
LLM-distilled prompt addenda that the pipeline engine injects at runtime.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.compat import GUID, JsonDict


revision = "6a9b0c1d2e3f"
down_revision = "5f8a9b0c1d2e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_signals",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("task_id", sa.String(200), nullable=False, index=True),
        sa.Column("stage_id", sa.String(50), nullable=False, index=True),
        sa.Column("role", sa.String(100), nullable=False, server_default=""),
        sa.Column("signal_type", sa.String(30), nullable=False, index=True),
        sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
        sa.Column("reviewer", sa.String(200), nullable=True),
        sa.Column("reviewer_feedback", sa.Text(), nullable=True),
        sa.Column("output_excerpt", sa.Text(), nullable=True),
        sa.Column("error_excerpt", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("metadata_extra", JsonDict(), nullable=False, server_default="{}"),
        sa.Column("distilled", sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
        sa.Column("distilled_into_id", GUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP"), index=True),
    )
    op.create_index(
        "ix_learning_signals_stage_distilled",
        "learning_signals", ["stage_id", "distilled"],
    )

    op.create_table(
        "prompt_overrides",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("stage_id", sa.String(50), nullable=False, index=True),
        sa.Column("role", sa.String(100), nullable=False, server_default=""),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("addendum", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="proposed", index=True),
        sa.Column("auto_apply", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sample_signal_ids", JsonDict(), nullable=False, server_default="[]"),
        sa.Column("distilled_from_n", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("parent_id", GUID(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("activated_by", sa.String(200), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("impact_uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impact_approves", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impact_rejects", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP"), index=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index(
        "ix_prompt_overrides_stage_status",
        "prompt_overrides", ["stage_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_prompt_overrides_stage_status", table_name="prompt_overrides")
    op.drop_table("prompt_overrides")
    op.drop_index("ix_learning_signals_stage_distilled", table_name="learning_signals")
    op.drop_table("learning_signals")
