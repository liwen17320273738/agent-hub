"""add observability tables and pgvector embedding column

Revision ID: a1b2c3d4e5f6
Revises: 6ff59fe0db1e
Create Date: 2026-04-15 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '6ff59fe0db1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres(bind) -> bool:
    return bind.dialect.name == "postgresql"


def _pgvector_available(bind) -> bool:
    """True if the vector extension is installed (or was just created)."""
    try:
        row = bind.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        ).first()
        return row is not None
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = _is_postgres(bind)
    existing_tables = set(sa.inspect(bind).get_table_names())

    # --- Enable pgvector extension (PostgreSQL only) ---
    # Stock Postgres images often lack pgvector; use SAVEPOINT so a failed
    # CREATE does not abort the whole migration transaction.
    pgvector_ok = False
    if is_pg:
        op.execute(text("SAVEPOINT sp_pgvector_try"))
        try:
            op.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception:
            op.execute(text("ROLLBACK TO SAVEPOINT sp_pgvector_try"))
            pgvector_ok = False
        else:
            op.execute(text("RELEASE SAVEPOINT sp_pgvector_try"))
            pgvector_ok = _pgvector_available(bind)

    # --- trace_records ---
    if 'trace_records' not in existing_tables:
        op.create_table(
            'trace_records',
            sa.Column('id', UUID(as_uuid=True) if is_pg else sa.String(36), primary_key=True),
            sa.Column('trace_id', sa.String(50), nullable=False),
            sa.Column('task_id', sa.String(200), nullable=False),
            sa.Column('task_title', sa.String(500), server_default=''),
            sa.Column('status', sa.String(20), server_default='running'),
            sa.Column('started_at', sa.Float, server_default='0'),
            sa.Column('completed_at', sa.Float, server_default='0'),
            sa.Column('duration_ms', sa.Integer, server_default='0'),
            sa.Column('total_prompt_tokens', sa.Integer, server_default='0'),
            sa.Column('total_completion_tokens', sa.Integer, server_default='0'),
            sa.Column('total_tokens', sa.Integer, server_default='0'),
            sa.Column('total_cost_usd', sa.Float, server_default='0'),
            sa.Column('total_llm_calls', sa.Integer, server_default='0'),
            sa.Column('total_retries', sa.Integer, server_default='0'),
            sa.Column('models_used', sa.JSON, server_default='{}'),
            sa.Column('stage_durations', sa.JSON, server_default='{}'),
            sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_trace_records_trace_id', 'trace_records', ['trace_id'], unique=True)
        op.create_index('ix_trace_records_task_id', 'trace_records', ['task_id'])

    # --- span_records ---
    if 'span_records' not in existing_tables:
        op.create_table(
            'span_records',
            sa.Column('id', UUID(as_uuid=True) if is_pg else sa.String(36), primary_key=True),
            sa.Column('span_id', sa.String(50), nullable=False),
            sa.Column('trace_id', sa.String(50), nullable=False),
            sa.Column('parent_span_id', sa.String(50), nullable=True),
            sa.Column('task_id', sa.String(200), nullable=False),
            sa.Column('stage_id', sa.String(50), nullable=False),
            sa.Column('role', sa.String(100), nullable=False),
            sa.Column('model', sa.String(100), server_default=''),
            sa.Column('tier', sa.String(20), server_default=''),
            sa.Column('status', sa.String(20), server_default='running'),
            sa.Column('error', sa.Text, nullable=True),
            sa.Column('started_at', sa.Float, server_default='0'),
            sa.Column('completed_at', sa.Float, server_default='0'),
            sa.Column('duration_ms', sa.Integer, server_default='0'),
            sa.Column('prompt_tokens', sa.Integer, server_default='0'),
            sa.Column('completion_tokens', sa.Integer, server_default='0'),
            sa.Column('total_tokens', sa.Integer, server_default='0'),
            sa.Column('cost_usd', sa.Float, server_default='0'),
            sa.Column('verify_status', sa.String(20), nullable=True),
            sa.Column('verify_checks', sa.JSON, server_default='[]'),
            sa.Column('guardrail_level', sa.String(30), nullable=True),
            sa.Column('approval_id', sa.String(50), nullable=True),
            sa.Column('input_length', sa.Integer, server_default='0'),
            sa.Column('output_length', sa.Integer, server_default='0'),
            sa.Column('retry_count', sa.Integer, server_default='0'),
            sa.Column('metadata_extra', sa.JSON, server_default='{}'),
            sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_span_records_span_id', 'span_records', ['span_id'], unique=True)
        op.create_index('ix_span_records_trace_id', 'span_records', ['trace_id'])
        op.create_index('ix_span_records_task_id', 'span_records', ['task_id'])

    # --- audit_logs ---
    if 'audit_logs' not in existing_tables:
        op.create_table(
            'audit_logs',
            sa.Column('id', UUID(as_uuid=True) if is_pg else sa.String(36), primary_key=True),
            sa.Column('task_id', sa.String(200), nullable=False),
            sa.Column('stage_id', sa.String(50), nullable=False),
            sa.Column('action', sa.String(100), nullable=False),
            sa.Column('actor', sa.String(200), nullable=False),
            sa.Column('risk_level', sa.String(30), server_default='auto_approve'),
            sa.Column('outcome', sa.String(50), nullable=False),
            sa.Column('details', sa.Text, server_default=''),
            sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_audit_logs_task_id', 'audit_logs', ['task_id'])
        op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
        op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])

    # --- approval_records ---
    if 'approval_records' not in existing_tables:
        op.create_table(
            'approval_records',
            sa.Column('id', UUID(as_uuid=True) if is_pg else sa.String(36), primary_key=True),
            sa.Column('approval_id', sa.String(50), nullable=False),
            sa.Column('task_id', sa.String(200), nullable=False),
            sa.Column('stage_id', sa.String(50), nullable=False),
            sa.Column('action', sa.String(100), nullable=False),
            sa.Column('description', sa.Text, server_default=''),
            sa.Column('risk_level', sa.String(30), nullable=False),
            sa.Column('requested_by', sa.String(200), server_default='system'),
            sa.Column('status', sa.String(20), server_default='pending'),
            sa.Column('reviewer', sa.String(200), nullable=True),
            sa.Column('review_comment', sa.Text, nullable=True),
            sa.Column('metadata_extra', sa.JSON, server_default='{}'),
            sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
            sa.Column('resolved_at', sa.DateTime, nullable=True),
        )
        op.create_index('ix_approval_records_approval_id', 'approval_records', ['approval_id'], unique=True)
        op.create_index('ix_approval_records_task_id', 'approval_records', ['task_id'])
        op.create_index('ix_approval_records_status', 'approval_records', ['status'])

    # --- feedback_records ---
    if 'feedback_records' not in existing_tables:
        op.create_table(
            'feedback_records',
            sa.Column('id', UUID(as_uuid=True) if is_pg else sa.String(36), primary_key=True),
            sa.Column('feedback_id', sa.String(50), nullable=False),
            sa.Column('task_id', sa.String(200), nullable=False),
            sa.Column('source', sa.String(50), nullable=False),
            sa.Column('user_id', sa.String(200), server_default=''),
            sa.Column('content', sa.Text, nullable=False),
            sa.Column('feedback_type', sa.String(30), server_default='revision'),
            sa.Column('status', sa.String(20), server_default='pending'),
            sa.Column('resolution', sa.Text, nullable=True),
            sa.Column('iteration_count', sa.Integer, server_default='0'),
            sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
            sa.Column('resolved_at', sa.DateTime, nullable=True),
        )
        op.create_index('ix_feedback_records_feedback_id', 'feedback_records', ['feedback_id'], unique=True)
        op.create_index('ix_feedback_records_task_id', 'feedback_records', ['task_id'])

    # --- Add embedding column to task_memories ---
    if is_pg:
        if pgvector_ok:
            op.execute(
                text("ALTER TABLE task_memories ADD COLUMN IF NOT EXISTS embedding vector(1536)")
            )
        else:
            op.execute(
                text("ALTER TABLE task_memories ADD COLUMN IF NOT EXISTS embedding TEXT")
            )
    else:
        op.add_column('task_memories', sa.Column('embedding', sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column('task_memories', 'embedding')
    op.drop_table('feedback_records')
    op.drop_table('approval_records')
    op.drop_table('audit_logs')
    op.drop_table('span_records')
    op.drop_table('trace_records')

    bind = op.get_bind()
    if _is_postgres(bind):
        # NOTE: vector extension may be shared with other schemas/apps.
        # Only drop if you are certain no other users depend on it.
        # op.execute("DROP EXTENSION IF EXISTS vector")
        pass
