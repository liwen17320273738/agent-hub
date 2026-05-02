"""add repo_refs JSONB column to pipeline_tasks

Structured Git reference tracking for PRs, branches, CI status.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE pipeline_tasks "
            "ADD COLUMN IF NOT EXISTS repo_refs JSONB DEFAULT '[]'::jsonb NOT NULL"
        )
    else:
        with op.batch_alter_table("pipeline_tasks") as batch:
            batch.add_column(sa.Column("repo_refs", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("pipeline_tasks") as batch:
        batch.drop_column("repo_refs")
