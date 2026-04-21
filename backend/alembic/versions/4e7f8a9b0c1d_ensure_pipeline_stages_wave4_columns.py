"""Ensure pipeline_stages wave-4 columns exist (PostgreSQL batch_alter fix-up)

Revision ID: 4e7f8a9b0c1d
Revises: 3d4e5f6a7b8c
Create Date: 2026-04-20 12:00:00.000000

Earlier 2c3d4e5f6a7b used batch_alter_table; on some PostgreSQL setups the
columns were never created while alembic_version advanced. Idempotent ADD.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "4e7f8a9b0c1d"
down_revision = "3d4e5f6a7b8c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
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


def downgrade() -> None:
    pass
