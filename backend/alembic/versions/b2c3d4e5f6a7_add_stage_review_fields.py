"""add stage review fields

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            text(
                "ALTER TABLE pipeline_stages ADD COLUMN IF NOT EXISTS review_status VARCHAR(20)"
            )
        )
        op.execute(
            text(
                "ALTER TABLE pipeline_stages ADD COLUMN IF NOT EXISTS reviewer_feedback TEXT"
            )
        )
        op.execute(
            text(
                "ALTER TABLE pipeline_stages ADD COLUMN IF NOT EXISTS reviewer_agent VARCHAR(100)"
            )
        )
        op.execute(
            text(
                "ALTER TABLE pipeline_stages ADD COLUMN IF NOT EXISTS review_attempts INTEGER DEFAULT 0"
            )
        )
        op.execute(
            text(
                "ALTER TABLE pipeline_stages ADD COLUMN IF NOT EXISTS approval_id VARCHAR(100)"
            )
        )
    else:
        op.add_column('pipeline_stages', sa.Column('review_status', sa.String(20), nullable=True))
        op.add_column('pipeline_stages', sa.Column('reviewer_feedback', sa.Text(), nullable=True))
        op.add_column('pipeline_stages', sa.Column('reviewer_agent', sa.String(100), nullable=True))
        op.add_column('pipeline_stages', sa.Column('review_attempts', sa.Integer(), server_default='0'))
        op.add_column('pipeline_stages', sa.Column('approval_id', sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column('pipeline_stages', 'approval_id')
    op.drop_column('pipeline_stages', 'review_attempts')
    op.drop_column('pipeline_stages', 'reviewer_agent')
    op.drop_column('pipeline_stages', 'reviewer_feedback')
    op.drop_column('pipeline_stages', 'review_status')
