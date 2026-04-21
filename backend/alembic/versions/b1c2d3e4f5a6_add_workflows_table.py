"""Add workflows table.

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-04-21 16:30:00.000000

Server-backed Workflow Builder save slot. The frontend already
autosaves to ``localStorage``; this table adds the cross-device,
shareable, named persistence the UI's "save / load / list" flow
needs (see ``src/views/WorkflowBuilder.vue`` after this migration).

Schema rationale
================
* ``doc`` is a JSON blob containing the verbatim ``WorkflowDoc``
  shape the builder ships to disk (export → import). We deliberately
  do NOT split it into normalized stage rows: that representation is
  owned by the client (``src/services/workflowBuilder.ts``) and any
  server-side schema would just lag.
* ``org_id`` scopes visibility to the user's org, mirroring the
  existing pattern on ``pipeline_tasks``. NULL row = "API key /
  unscoped" — same convention as elsewhere.
* No FK to ``users`` for ``created_by`` — we already store the same
  free-form ``str(user.id)`` (or ``"api"``) on ``pipeline_tasks``,
  so users joining/leaving an org doesn't ripple delete their saves.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.compat import GUID, JsonDict


revision = "b1c2d3e4f5a6"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "org_id",
            GUID(),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("created_by", sa.String(200), nullable=False, server_default="system"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("doc", JsonDict(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("workflows")
