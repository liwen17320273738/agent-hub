"""add pipeline_tasks cost-tracking columns (spent_usd, cost_ledger, budget_ratios, flags)

Revision ID: y1z2a3b4c5d6
Revises: x0y1z2a3b4c5
Create Date: 2026-05-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "y1z2a3b4c5d6"
down_revision = "x0y1z2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("""
            ALTER TABLE pipeline_tasks
            ADD COLUMN IF NOT EXISTS spent_usd DOUBLE PRECISION DEFAULT 0.0,
            ADD COLUMN IF NOT EXISTS cost_ledger JSONB DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS budget_soft_ratio DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS budget_hard_ratio DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS budget_blocked BOOLEAN DEFAULT false,
            ADD COLUMN IF NOT EXISTS budget_overridden BOOLEAN DEFAULT false
        """)
    else:
        for col, col_type in [
            ("spent_usd", sa.Float()),
            ("cost_ledger", sa.JSON()),
            ("budget_soft_ratio", sa.Float()),
            ("budget_hard_ratio", sa.Float()),
            ("budget_blocked", sa.Boolean()),
            ("budget_overridden", sa.Boolean()),
        ]:
            op.add_column("pipeline_tasks", sa.Column(col, col_type, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("""
            ALTER TABLE pipeline_tasks
            DROP COLUMN IF EXISTS spent_usd,
            DROP COLUMN IF EXISTS cost_ledger,
            DROP COLUMN IF EXISTS budget_soft_ratio,
            DROP COLUMN IF EXISTS budget_hard_ratio,
            DROP COLUMN IF EXISTS budget_blocked,
            DROP COLUMN IF EXISTS budget_overridden
        """)
    else:
        for col in [
            "spent_usd", "cost_ledger", "budget_soft_ratio",
            "budget_hard_ratio", "budget_blocked", "budget_overridden",
        ]:
            with op.batch_alter_table("pipeline_tasks") as batch:
                batch.drop_column(col)
