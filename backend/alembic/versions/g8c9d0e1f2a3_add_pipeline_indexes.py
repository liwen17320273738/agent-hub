"""add_pipeline_indexes

Revision ID: g8c9d0e1f2a3
Revises: m3n4o5p6q7r8
Create Date: 2026-05-09 13:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "g8c9d0e1f2a3"
down_revision = "m3n4o5p6q7r8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PipelineTask indexes
    op.create_index(
        "ix_pipeline_tasks_org_status",
        "pipeline_tasks",
        ["org_id", "status"],
    )
    op.create_index(
        "ix_pipeline_tasks_status_created",
        "pipeline_tasks",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_pipeline_tasks_workspace",
        "pipeline_tasks",
        ["workspace_id"],
    )
    op.create_index(
        "ix_pipeline_tasks_created_by",
        "pipeline_tasks",
        ["created_by"],
    )
    # PipelineStage indexes
    op.create_index(
        "ix_pipeline_stages_task_stage",
        "pipeline_stages",
        ["task_id", "stage_id"],
    )
    op.create_index(
        "ix_pipeline_stages_task_status",
        "pipeline_stages",
        ["task_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_stages_task_status", table_name="pipeline_stages")
    op.drop_index("ix_pipeline_stages_task_stage", table_name="pipeline_stages")
    op.drop_index("ix_pipeline_tasks_created_by", table_name="pipeline_tasks")
    op.drop_index("ix_pipeline_tasks_workspace", table_name="pipeline_tasks")
    op.drop_index("ix_pipeline_tasks_status_created", table_name="pipeline_tasks")
    op.drop_index("ix_pipeline_tasks_org_status", table_name="pipeline_tasks")
