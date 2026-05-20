"""Phase 2: scheduler run columns + pipeline_stages.input_snapshot

Revision ID: h9a0b1c2d3e4
Revises: a3b4c5d6e7f8
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision: str = "h9a0b1c2d3e4"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for stmt in (
            "ALTER TABLE pipeline_tasks ADD COLUMN IF NOT EXISTS "
            "scheduler_run_submission_id VARCHAR(64)",
            "ALTER TABLE pipeline_tasks ADD COLUMN IF NOT EXISTS scheduler_run_kind VARCHAR(32)",
            "ALTER TABLE pipeline_tasks ADD COLUMN IF NOT EXISTS scheduler_run_started_at TIMESTAMP",
            "ALTER TABLE pipeline_tasks ADD COLUMN IF NOT EXISTS scheduler_run_finished_at TIMESTAMP",
            "ALTER TABLE pipeline_tasks ADD COLUMN IF NOT EXISTS scheduler_last_error TEXT",
            "ALTER TABLE pipeline_stages ADD COLUMN IF NOT EXISTS input_snapshot JSON",
        ):
            op.execute(text(stmt))
    else:
        with op.batch_alter_table("pipeline_tasks") as batch:
            batch.add_column(sa.Column("scheduler_run_submission_id", sa.String(64), nullable=True))
            batch.add_column(sa.Column("scheduler_run_kind", sa.String(32), nullable=True))
            batch.add_column(sa.Column("scheduler_run_started_at", sa.DateTime(), nullable=True))
            batch.add_column(sa.Column("scheduler_run_finished_at", sa.DateTime(), nullable=True))
            batch.add_column(sa.Column("scheduler_last_error", sa.Text(), nullable=True))
        with op.batch_alter_table("pipeline_stages") as batch:
            batch.add_column(sa.Column("input_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(text("ALTER TABLE pipeline_stages DROP COLUMN IF EXISTS input_snapshot"))
        op.execute(text("ALTER TABLE pipeline_tasks DROP COLUMN IF EXISTS scheduler_last_error"))
        op.execute(text("ALTER TABLE pipeline_tasks DROP COLUMN IF EXISTS scheduler_run_finished_at"))
        op.execute(text("ALTER TABLE pipeline_tasks DROP COLUMN IF EXISTS scheduler_run_started_at"))
        op.execute(text("ALTER TABLE pipeline_tasks DROP COLUMN IF EXISTS scheduler_run_kind"))
        op.execute(text("ALTER TABLE pipeline_tasks DROP COLUMN IF EXISTS scheduler_run_submission_id"))
    else:
        with op.batch_alter_table("pipeline_stages") as batch:
            batch.drop_column("input_snapshot")
        with op.batch_alter_table("pipeline_tasks") as batch:
            batch.drop_column("scheduler_last_error")
            batch.drop_column("scheduler_run_finished_at")
            batch.drop_column("scheduler_run_started_at")
            batch.drop_column("scheduler_run_kind")
            batch.drop_column("scheduler_run_submission_id")

