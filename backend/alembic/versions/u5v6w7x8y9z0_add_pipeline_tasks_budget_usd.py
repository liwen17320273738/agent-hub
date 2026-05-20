"""add pipeline_tasks.budget_usd (ORM parity)

Revision ID: u5v6w7x8y9z0
Revises: 42959d437fcc
Create Date: 2026-05-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "u5v6w7x8y9z0"
down_revision = "42959d437fcc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("""
            ALTER TABLE pipeline_tasks
            ADD COLUMN IF NOT EXISTS budget_usd DOUBLE PRECISION
        """)
    else:
        op.add_column(
            "pipeline_tasks",
            sa.Column("budget_usd", sa.Float(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("ALTER TABLE pipeline_tasks DROP COLUMN IF EXISTS budget_usd")
    else:
        with op.batch_alter_table("pipeline_tasks") as batch:
            batch.drop_column("budget_usd")
