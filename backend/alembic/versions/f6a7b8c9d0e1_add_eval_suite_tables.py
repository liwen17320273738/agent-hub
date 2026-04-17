"""add eval suite tables

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-17 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def _guid_type():
    """Mirror app.compat.GUID — UUID on PG, String(36) elsewhere."""
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

    op.create_table(
        "eval_datasets",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True, index=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", JSON(), nullable=True),
        sa.Column("target_role", sa.String(100), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "eval_cases",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("dataset_id", GUID(), sa.ForeignKey("eval_datasets.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("context", JSON(), nullable=True),
        sa.Column("role", sa.String(100), nullable=False, server_default=""),
        sa.Column("scorer", sa.String(50), nullable=False, server_default="contains"),
        sa.Column("expected", JSON(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "eval_runs",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("dataset_id", GUID(), sa.ForeignKey("eval_datasets.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("label", sa.String(200), nullable=False, server_default=""),
        sa.Column("agent_role_override", sa.String(100), nullable=False, server_default=""),
        sa.Column("model_override", sa.String(100), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("total_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("metadata_extra", JSON(), nullable=True),
    )

    op.create_table(
        "eval_results",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("run_id", GUID(), sa.ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("case_id", GUID(), sa.ForeignKey("eval_cases.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("case_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("role", sa.String(100), nullable=False, server_default=""),
        sa.Column("seed_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("output", sa.Text(), nullable=False, server_default=""),
        sa.Column("observations", JSON(), nullable=True),
        sa.Column("scorer", sa.String(50), nullable=False, server_default=""),
        sa.Column("scorer_detail", JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("eval_results")
    op.drop_table("eval_runs")
    op.drop_table("eval_cases")
    op.drop_table("eval_datasets")
