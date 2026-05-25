"""add workspaces.allow_draft_delivery (delivery contract toggle)

Revision ID: w9x0y1z2a3b4
Revises: v8w9x0y1z2a3
Create Date: 2026-05-22

Adds a workspace-level boolean ``allow_draft_delivery``. When False (default),
the delivery contract hard-gates share-token issuance and final-accept on
real test + real preview + real evidence. When True, the workspace opts in
to "draft delivery" mode and tasks lacking evidence land in
``status="awaiting_evidence"`` with a draft banner instead of being blocked.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "w9x0y1z2a3b4"
down_revision = "v8w9x0y1z2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("""
            ALTER TABLE workspaces
            ADD COLUMN IF NOT EXISTS allow_draft_delivery BOOLEAN
            NOT NULL DEFAULT FALSE
        """)
    else:
        op.add_column(
            "workspaces",
            sa.Column(
                "allow_draft_delivery",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("ALTER TABLE workspaces DROP COLUMN IF EXISTS allow_draft_delivery")
    else:
        with op.batch_alter_table("workspaces") as batch:
            batch.drop_column("allow_draft_delivery")
