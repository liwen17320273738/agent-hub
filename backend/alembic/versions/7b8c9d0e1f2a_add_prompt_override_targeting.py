"""Add targeting JSON column to prompt_overrides for shadow segmentation.

Revision ID: 7b8c9d0e1f2a
Revises: 6a9b0c1d2e3f
Create Date: 2026-04-21 12:00:00.000000

Phase-3 learning loop refinement: a single shadow override per stage was
fine when traffic was uniform, but real workloads aren't — a prompt that
helps ``template=full`` may regress ``template=fast``, and a tweak for
``complexity=simple`` may break ``complex`` runs. Until now we couldn't
canary by segment, so the auto-promote/retire logic had to look at
aggregate numbers and either ship a half-good override to everyone or
discard a half-good override that helped one segment.

This column adds a ``targeting`` JSON dict per override::

    {"templates": ["full","fast"], "complexities": ["simple","medium"]}

Empty / missing keys = match-anything (back-compat with all existing
rows). At runtime ``get_active_addendum(stage_id, template=, complexity=)``
filters candidates by targeting, so multiple shadows can coexist as long
as their target segments don't overlap.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.compat import JsonDict


revision = "7b8c9d0e1f2a"
down_revision = "6a9b0c1d2e3f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("prompt_overrides") as batch:
        batch.add_column(
            sa.Column(
                "targeting",
                JsonDict(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("prompt_overrides") as batch:
        batch.drop_column("targeting")
