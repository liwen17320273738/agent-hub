"""add pipeline_tasks.workspace_id (ORM parity before pipeline indexes)

Revision ID: m3n4o5p6q7r8
Revises: 00000000000001
Create Date: 2026-05-14

The ORM and ix_pipeline_tasks_workspace expect this column; it was missing
from older migrations.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "m3n4o5p6q7r8"
down_revision = "00000000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("""
            ALTER TABLE pipeline_tasks
            ADD COLUMN IF NOT EXISTS workspace_id UUID
            REFERENCES workspaces(id) ON DELETE SET NULL
        """)
    else:
        op.add_column(
            "pipeline_tasks",
            sa.Column(
                "workspace_id",
                sa.String(36),
                sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("ALTER TABLE pipeline_tasks DROP COLUMN IF EXISTS workspace_id")
    else:
        with op.batch_alter_table("pipeline_tasks") as batch:
            batch.drop_column("workspace_id")
