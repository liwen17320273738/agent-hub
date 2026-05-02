"""add knowledge_collections table + collection_id to task_memories

Creates a ``knowledge_collections`` table for tracking ingested data sources
(web scrapes, document uploads, API feeds) at the collection level, and adds
an optional ``collection_id`` FK on ``task_memories`` so memory searches can
be scoped to a named data source.

Revision ID: a2b3c4d5e6f7
Revises: f7b8c9d0e1f2
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "a2b3c4d5e6f7"
down_revision = "00000000000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # --- 1. Create knowledge_collections table ---
    if is_pg:
        op.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_collections (
                id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name          VARCHAR(200) NOT NULL,
                description   TEXT NOT NULL DEFAULT '',
                workspace_id  UUID REFERENCES workspaces(id) ON DELETE CASCADE,
                org_id        UUID REFERENCES orgs(id) ON DELETE CASCADE,
                source_type   VARCHAR(20) NOT NULL DEFAULT 'manual',
                source_uri    VARCHAR(1000) NOT NULL DEFAULT '',
                source_config JSONB NOT NULL DEFAULT '{}',
                access_scope  VARCHAR(20) NOT NULL DEFAULT 'workspace',
                item_count    INTEGER NOT NULL DEFAULT 0,
                is_active     BOOLEAN NOT NULL DEFAULT TRUE,
                created_by    VARCHAR(200) NOT NULL DEFAULT 'system',
                created_at    TIMESTAMP NOT NULL DEFAULT now(),
                updated_at    TIMESTAMP NOT NULL DEFAULT now()
            )
        """)
        op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_collections_name ON knowledge_collections(name)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_collections_workspace_id ON knowledge_collections(workspace_id)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_collections_org_id ON knowledge_collections(org_id)")
    else:
        op.create_table(
            "knowledge_collections",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(200), nullable=False, index=True),
            sa.Column("description", sa.Text(), server_default=""),
            sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True),
            sa.Column("org_id", sa.String(36), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=True),
            sa.Column("source_type", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("source_uri", sa.String(1000), server_default=""),
            sa.Column("source_config", sa.JSON(), server_default="{}"),
            sa.Column("access_scope", sa.String(20), nullable=False, server_default="workspace"),
            sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
            sa.Column("created_by", sa.String(200), server_default="system"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )

    # --- 2. Add collection_id to task_memories ---
    if is_pg:
        op.execute("ALTER TABLE task_memories ADD COLUMN IF NOT EXISTS collection_id UUID REFERENCES knowledge_collections(id) ON DELETE SET NULL")
        op.execute("CREATE INDEX IF NOT EXISTS ix_task_memories_collection_id ON task_memories(collection_id)")
    else:
        with op.batch_alter_table("task_memories") as batch:
            batch.add_column(sa.Column("collection_id", sa.String(36), sa.ForeignKey("knowledge_collections.id", ondelete="SET NULL"), nullable=True))
            batch.create_index("ix_task_memories_collection_id", ["collection_id"])


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute("DROP INDEX IF EXISTS ix_task_memories_collection_id")
        op.execute("ALTER TABLE task_memories DROP COLUMN IF EXISTS collection_id")
        op.execute("DROP TABLE IF EXISTS knowledge_collections")
    else:
        with op.batch_alter_table("task_memories") as batch:
            batch.drop_index("ix_task_memories_collection_id")
            batch.drop_column("collection_id")
        op.drop_table("knowledge_collections")
