"""Add sandbox_rules table for DB-backed role/tool whitelist overrides.

Revision ID: 8c9d0e1f2a3b
Revises: 7b8c9d0e1f2a
Create Date: 2026-04-21 12:30:00.000000

Phase-3 sandbox refinement: ops can flip an allow/deny without a code
change. The in-code baseline (``ROLE_TOOL_WHITELIST``) still ships as
the source-of-truth default; this table only stores *overrides*. An
empty table = identical behaviour to pre-migration.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.compat import GUID


revision = "8c9d0e1f2a3b"
down_revision = "7b8c9d0e1f2a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sandbox_rules",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("tool", sa.String(128), nullable=False),
        sa.Column("allowed", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("updated_by", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("role", "tool", name="uq_sandbox_rules_role_tool"),
    )
    op.create_index("ix_sandbox_rules_role", "sandbox_rules", ["role"])
    op.create_index("ix_sandbox_rules_tool", "sandbox_rules", ["tool"])
    op.create_index("ix_sandbox_rules_role_tool", "sandbox_rules", ["role", "tool"])


def downgrade() -> None:
    op.drop_index("ix_sandbox_rules_role_tool", table_name="sandbox_rules")
    op.drop_index("ix_sandbox_rules_tool", table_name="sandbox_rules")
    op.drop_index("ix_sandbox_rules_role", table_name="sandbox_rules")
    op.drop_table("sandbox_rules")
