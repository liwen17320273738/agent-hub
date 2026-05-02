"""add stage_run_logs table

Per-execution-attempt logs for the Workflow Builder node observability.
Each stage execution (including retries) gets one row.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("""
            CREATE TABLE IF NOT EXISTS stage_run_logs (
                id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                task_id           VARCHAR(200) NOT NULL,
                stage_id          VARCHAR(50) NOT NULL,
                label             VARCHAR(100) NOT NULL DEFAULT '',
                role              VARCHAR(100) NOT NULL DEFAULT '',
                model             VARCHAR(100) NOT NULL DEFAULT '',
                model_tier        VARCHAR(20) NOT NULL DEFAULT '',
                input_snapshot    TEXT NOT NULL DEFAULT '',
                input_token_count INTEGER NOT NULL DEFAULT 0,
                output            TEXT NOT NULL DEFAULT '',
                output_token_count INTEGER NOT NULL DEFAULT 0,
                success           INTEGER NOT NULL DEFAULT 0,
                error_message     TEXT NOT NULL DEFAULT '',
                duration_ms       INTEGER NOT NULL DEFAULT 0,
                quality_score     DOUBLE PRECISION,
                gate_status       VARCHAR(20) NOT NULL DEFAULT '',
                verify_status     VARCHAR(10) NOT NULL DEFAULT '',
                trace_id          VARCHAR(100) NOT NULL DEFAULT '',
                created_at        TIMESTAMP NOT NULL DEFAULT now()
            )
        """)
        op.execute("CREATE INDEX IF NOT EXISTS ix_stage_run_logs_task_id ON stage_run_logs(task_id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_stage_run_logs_task_stage ON stage_run_logs(task_id, stage_id)")
    else:
        op.create_table(
            "stage_run_logs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("task_id", sa.String(200), nullable=False, index=True),
            sa.Column("stage_id", sa.String(50), nullable=False),
            sa.Column("label", sa.String(100), server_default=""),
            sa.Column("role", sa.String(100), server_default=""),
            sa.Column("model", sa.String(100), server_default=""),
            sa.Column("model_tier", sa.String(20), server_default=""),
            sa.Column("input_snapshot", sa.Text(), server_default=""),
            sa.Column("input_token_count", sa.Integer(), server_default="0"),
            sa.Column("output", sa.Text(), server_default=""),
            sa.Column("output_token_count", sa.Integer(), server_default="0"),
            sa.Column("success", sa.Integer(), server_default="0"),
            sa.Column("error_message", sa.Text(), server_default=""),
            sa.Column("duration_ms", sa.Integer(), server_default="0"),
            sa.Column("quality_score", sa.Float(), nullable=True),
            sa.Column("gate_status", sa.String(20), server_default=""),
            sa.Column("verify_status", sa.String(10), server_default=""),
            sa.Column("trace_id", sa.String(100), server_default=""),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("ix_stage_run_logs_task_stage", "stage_run_logs", ["task_id", "stage_id"])


def downgrade() -> None:
    op.drop_table("stage_run_logs")
