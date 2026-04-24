"""Add skill_ratings table for marketplace star ratings.

Revision ID: d5f6a7b8c9e0
Revises: c2d3e4f5a6b7
Create Date: 2026-04-22 10:00:00.000000

One rating per (skill_id, user_id). The list endpoint aggregates to
avg_stars / rating_count on the fly — no denormalized fields on
`skills` to avoid drift.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.compat import GUID


revision = "d5f6a7b8c9e0"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_ratings",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("skill_id", sa.String(100), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("stars", sa.Integer, nullable=False),
        sa.Column("comment", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"], ondelete="CASCADE",
            name="fk_skill_ratings_skill_id",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
            name="fk_skill_ratings_user_id",
        ),
        sa.UniqueConstraint(
            "skill_id", "user_id", name="uq_skill_ratings_skill_user",
        ),
        sa.CheckConstraint("stars >= 1 AND stars <= 5", name="ck_skill_ratings_stars_1_5"),
    )
    op.create_index("ix_skill_ratings_skill_id", "skill_ratings", ["skill_id"])


def downgrade() -> None:
    op.drop_index("ix_skill_ratings_skill_id", table_name="skill_ratings")
    op.drop_table("skill_ratings")
