"""add quality gate and template fields

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-16 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pipeline_tasks', sa.Column('template', sa.String(50), nullable=True))
    op.add_column('pipeline_stages', sa.Column('verify_status', sa.String(10), nullable=True))
    op.add_column('pipeline_stages', sa.Column('verify_checks', sa.JSON(), nullable=True))
    op.add_column('pipeline_stages', sa.Column('quality_score', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('pipeline_stages', 'quality_score')
    op.drop_column('pipeline_stages', 'verify_checks')
    op.drop_column('pipeline_stages', 'verify_status')
    op.drop_column('pipeline_tasks', 'template')
