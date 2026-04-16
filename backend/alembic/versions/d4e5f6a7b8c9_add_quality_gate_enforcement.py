"""add quality gate enforcement fields

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-16 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pipeline_tasks', sa.Column('quality_gate_config', sa.JSON(), nullable=True))
    op.add_column('pipeline_tasks', sa.Column('overall_quality_score', sa.Float(), nullable=True))
    op.add_column('pipeline_stages', sa.Column('gate_status', sa.String(20), nullable=True))
    op.add_column('pipeline_stages', sa.Column('gate_score', sa.Float(), nullable=True))
    op.add_column('pipeline_stages', sa.Column('gate_details', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('pipeline_stages', 'gate_details')
    op.drop_column('pipeline_stages', 'gate_score')
    op.drop_column('pipeline_stages', 'gate_status')
    op.drop_column('pipeline_tasks', 'overall_quality_score')
    op.drop_column('pipeline_tasks', 'quality_gate_config')
