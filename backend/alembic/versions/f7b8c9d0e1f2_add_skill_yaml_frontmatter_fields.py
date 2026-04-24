"""add skill YAML frontmatter columns

Formalises the four ``skills`` columns introduced alongside the gstack
SKILL.md pattern — ``trigger_stages``, ``completion_criteria``,
``allowed_tools`` and ``execution_mode``. These were added to
``app/models/skill.py`` before a migration existed; dev DBs were
patched by hand so this migration uses ``IF NOT EXISTS`` on Postgres
to be safe on partially-upgraded databases.

Revision ID: f7b8c9d0e1f2
Revises: e6a7b8c9d0e1
Create Date: 2026-04-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f7b8c9d0e1f2"
down_revision = "e6a7b8c9d0e1"
branch_labels = None
depends_on = None


_PG_COLS = [
    ("trigger_stages",      "JSONB DEFAULT '[]'::jsonb  NOT NULL"),
    ("completion_criteria", "JSONB DEFAULT '[]'::jsonb  NOT NULL"),
    ("allowed_tools",       "JSONB DEFAULT '[]'::jsonb  NOT NULL"),
    ("execution_mode",      "VARCHAR(20) DEFAULT 'inline' NOT NULL"),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for col, ddl in _PG_COLS:
            op.execute(f"ALTER TABLE skills ADD COLUMN IF NOT EXISTS {col} {ddl}")
    else:
        with op.batch_alter_table("skills") as batch:
            batch.add_column(sa.Column("trigger_stages",      sa.JSON(), nullable=False, server_default="[]"))
            batch.add_column(sa.Column("completion_criteria", sa.JSON(), nullable=False, server_default="[]"))
            batch.add_column(sa.Column("allowed_tools",       sa.JSON(), nullable=False, server_default="[]"))
            batch.add_column(sa.Column("execution_mode",      sa.String(20), nullable=False, server_default="inline"))


def downgrade() -> None:
    with op.batch_alter_table("skills") as batch:
        batch.drop_column("execution_mode")
        batch.drop_column("allowed_tools")
        batch.drop_column("completion_criteria")
        batch.drop_column("trigger_stages")
