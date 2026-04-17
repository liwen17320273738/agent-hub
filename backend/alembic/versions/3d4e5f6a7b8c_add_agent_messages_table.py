"""add agent_messages table for inter-agent message bus

Revision ID: 3d4e5f6a7b8c
Revises: 2c3d4e5f6a7b
Create Date: 2026-04-17 18:30:00.000000

Persists every agent-bus publish so late subscribers can replay history
and operators can audit cross-agent communication.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "3d4e5f6a7b8c"
down_revision = "2c3d4e5f6a7b"
branch_labels = None
depends_on = None


def _guid_type():
    return (
        postgresql.UUID(as_uuid=True)
        if op.get_bind().dialect.name == "postgresql"
        else sa.String(36)
    )


def _json_type():
    return (
        postgresql.JSONB()
        if op.get_bind().dialect.name == "postgresql"
        else sa.JSON()
    )


def upgrade() -> None:
    op.create_table(
        "agent_messages",
        sa.Column("id", _guid_type(), primary_key=True),
        sa.Column("topic", sa.String(100), nullable=False),
        sa.Column("sender", sa.String(100), nullable=False),
        sa.Column(
            "task_id", _guid_type(),
            sa.ForeignKey("pipeline_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("payload", _json_type(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_agent_messages_topic", "agent_messages", ["topic"])
    op.create_index("ix_agent_messages_sender", "agent_messages", ["sender"])
    op.create_index("ix_agent_messages_task_id", "agent_messages", ["task_id"])
    op.create_index("ix_agent_messages_created_at", "agent_messages", ["created_at"])
    op.create_index(
        "ix_agent_messages_topic_created",
        "agent_messages", ["topic", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_messages_topic_created", table_name="agent_messages")
    op.drop_index("ix_agent_messages_created_at", table_name="agent_messages")
    op.drop_index("ix_agent_messages_task_id", table_name="agent_messages")
    op.drop_index("ix_agent_messages_sender", table_name="agent_messages")
    op.drop_index("ix_agent_messages_topic", table_name="agent_messages")
    op.drop_table("agent_messages")
