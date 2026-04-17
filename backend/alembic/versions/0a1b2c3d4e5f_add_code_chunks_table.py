"""add code_chunks table for semantic codebase index

Revision ID: 0a1b2c3d4e5f
Revises: f6a7b8c9d0e1
Create Date: 2026-04-17 16:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0a1b2c3d4e5f"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def _guid_type():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(36)


def _json_type():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def upgrade() -> None:
    GUID = _guid_type
    JSON = _json_type

    # Embedding stored as TEXT (JSON-serialized list[float]) for portability.
    # Workspaces with pgvector enabled at app startup will use the native
    # vector column; here we keep the on-disk type as TEXT so the migration
    # works on plain Postgres / SQLite without the extension.
    op.create_table(
        "code_chunks",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("project_id", sa.String(500), nullable=False, index=True),
        sa.Column("rel_path", sa.String(500), nullable=False),
        sa.Column("language", sa.String(20), nullable=False, server_default=""),
        sa.Column("start_line", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("end_line", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content_hash", sa.String(64), nullable=False, index=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("symbols", JSON(), nullable=True),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=False, server_default=""),
        sa.Column("embedding_dim", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_code_chunks_project_path",
        "code_chunks",
        ["project_id", "rel_path"],
    )


def downgrade() -> None:
    op.drop_index("ix_code_chunks_project_path", table_name="code_chunks")
    op.drop_table("code_chunks")
