"""add pipeline_tasks.priority column

Revision ID: z1a2b3c4d5e6
Revises: y1z2a3b4c5d6
Create Date: 2026-05-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "z1a2b3c4d5e6"
down_revision = "y1z2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("""
            ALTER TABLE pipeline_tasks
            ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 0
        """)
    else:
        op.add_column(
            "pipeline_tasks",
            sa.Column("priority", sa.Integer(), nullable=True, server_default="0"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("ALTER TABLE pipeline_tasks DROP COLUMN IF EXISTS priority")
    else:
        with op.batch_alter_table("pipeline_tasks") as batch:
            batch.drop_column("priority")
