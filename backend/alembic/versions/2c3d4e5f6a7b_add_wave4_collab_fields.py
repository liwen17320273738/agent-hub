"""add wave-4 collaboration loop fields to pipeline_stages

Revision ID: 2c3d4e5f6a7b
Revises: 1b2c3d4e5f6a
Create Date: 2026-04-17 18:00:00.000000

Adds five columns to ``pipeline_stages`` enabling failure rollback,
retry budgets, and DAG-side human approval gates:

* last_error    — text, nullable
* retry_count   — int, default 0
* max_retries   — int, default 0
* on_failure    — varchar(20), default ``"halt"``
* human_gate    — boolean, default false

All defaults preserve existing behavior — old rows behave exactly the
same as before this migration.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "2c3d4e5f6a7b"
down_revision = "1b2c3d4e5f6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # batch_alter_table is SQLite-centric; on PostgreSQL use explicit DDL
        # so columns always appear (IF NOT EXISTS for idempotency).
        op.execute(text("ALTER TABLE pipeline_stages ADD COLUMN IF NOT EXISTS last_error TEXT"))
        op.execute(
            text(
                "ALTER TABLE pipeline_stages ADD COLUMN IF NOT EXISTS retry_count "
                "INTEGER NOT NULL DEFAULT 0"
            )
        )
        op.execute(
            text(
                "ALTER TABLE pipeline_stages ADD COLUMN IF NOT EXISTS max_retries "
                "INTEGER NOT NULL DEFAULT 0"
            )
        )
        op.execute(
            text(
                "ALTER TABLE pipeline_stages ADD COLUMN IF NOT EXISTS on_failure "
                "VARCHAR(20) NOT NULL DEFAULT 'halt'"
            )
        )
        op.execute(
            text(
                "ALTER TABLE pipeline_stages ADD COLUMN IF NOT EXISTS human_gate "
                "BOOLEAN NOT NULL DEFAULT false"
            )
        )
    else:
        with op.batch_alter_table("pipeline_stages") as batch:
            batch.add_column(sa.Column("last_error", sa.Text(), nullable=True))
            batch.add_column(
                sa.Column(
                    "retry_count", sa.Integer(), nullable=False, server_default="0",
                )
            )
            batch.add_column(
                sa.Column(
                    "max_retries", sa.Integer(), nullable=False, server_default="0",
                )
            )
            batch.add_column(
                sa.Column(
                    "on_failure", sa.String(20), nullable=False, server_default="halt",
                )
            )
            batch.add_column(
                sa.Column(
                    "human_gate", sa.Boolean(), nullable=False, server_default=sa.false(),
                )
            )


def downgrade() -> None:
    with op.batch_alter_table("pipeline_stages") as batch:
        batch.drop_column("human_gate")
        batch.drop_column("on_failure")
        batch.drop_column("max_retries")
        batch.drop_column("retry_count")
        batch.drop_column("last_error")
