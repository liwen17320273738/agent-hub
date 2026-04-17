"""add project binding fields (repo_url, project_path) to pipeline_tasks

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-17 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pipeline_tasks", sa.Column("repo_url", sa.String(500), nullable=True))
    op.add_column("pipeline_tasks", sa.Column("project_path", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("pipeline_tasks", "project_path")
    op.drop_column("pipeline_tasks", "repo_url")
