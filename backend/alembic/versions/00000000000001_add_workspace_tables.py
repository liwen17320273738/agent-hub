"""add missing workspaces + workspace_members tables

These tables exist as SQLAlchemy ORM models but were never created
by any migration. The knowledge_collections migration (a2b3c4d5e6f7)
depends on them, so this migration must run before it.

Revision ID: 00000000000001
Revises: f7b8c9d0e1f2
Create Date: 2026-04-30 16:34:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "00000000000001"
down_revision = "f7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                org_id        UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
                name          VARCHAR(255) NOT NULL,
                description   VARCHAR(1000) NOT NULL DEFAULT '',
                is_default    BOOLEAN NOT NULL DEFAULT FALSE,
                created_at    TIMESTAMP NOT NULL DEFAULT now(),
                updated_at    TIMESTAMP NOT NULL DEFAULT now()
            )
        """)
        op.execute("CREATE INDEX IF NOT EXISTS ix_workspaces_org_id ON workspaces(org_id)")

        op.execute("""
            CREATE TABLE IF NOT EXISTS workspace_members (
                id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role          VARCHAR(20) NOT NULL DEFAULT 'member',
                joined_at     TIMESTAMP NOT NULL DEFAULT now(),
                CONSTRAINT uq_ws_member UNIQUE (workspace_id, user_id)
            )
        """)
        op.execute("CREATE INDEX IF NOT EXISTS ix_workspace_members_workspace_id ON workspace_members(workspace_id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_workspace_members_user_id ON workspace_members(user_id)")
    else:
        op.create_table(
            "workspaces",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.String(1000), server_default=""),
            sa.Column("is_default", sa.Boolean(), server_default=sa.text("FALSE")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_table(
            "workspace_members",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", sa.String(20), server_default="member"),
            sa.Column("joined_at", sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint("workspace_id", "user_id", name="uq_ws_member"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("DROP TABLE IF EXISTS workspace_members")
        op.execute("DROP TABLE IF EXISTS workspaces")
    else:
        op.drop_table("workspace_members")
        op.drop_table("workspaces")
