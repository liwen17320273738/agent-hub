"""add agent.role_card column

Formalises the ``role_card`` JSONB column that ``app/models/agent.py``
already references.  Existing dev DBs were patched manually via
``ALTER TABLE ... IF NOT EXISTS`` so this migration uses the same
idempotent pattern for safety on any already-patched instances.

Revision ID: e6a7b8c9d0e1
Revises: d5f6a7b8c9e0
Create Date: 2026-04-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e6a7b8c9d0e1"
down_revision = "d5f6a7b8c9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Idempotent — dev DBs may have been ALTERed manually.
        op.execute(
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS role_card JSONB "
            "DEFAULT '{}'::jsonb NOT NULL"
        )
    else:
        # SQLite / others: fall back to normal add_column (JSON as text).
        with op.batch_alter_table("agents") as batch:
            batch.add_column(
                sa.Column("role_card", sa.JSON(), nullable=False, server_default="{}")
            )


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("role_card")
