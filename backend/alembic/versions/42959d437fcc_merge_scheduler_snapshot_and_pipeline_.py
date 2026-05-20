"""merge_scheduler_snapshot_and_pipeline_indexes

Revision ID: 42959d437fcc
Revises: g8c9d0e1f2a3, h9a0b1c2d3e4
Create Date: 2026-05-13 17:18:01.284720
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '42959d437fcc'
down_revision: Union[str, None] = ('g8c9d0e1f2a3', 'h9a0b1c2d3e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
