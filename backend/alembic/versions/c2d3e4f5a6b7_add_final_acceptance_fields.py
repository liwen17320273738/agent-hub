"""add final acceptance fields to pipeline_tasks

Adds the columns the "最终验收" (final acceptance) flow needs:

  * ``final_acceptance_status`` — one of: NULL, "pending", "accepted", "rejected"
       NULL = never reached the terminus (e.g. legacy task or paused)
       pending = compile_deliverables done, awaiting human verdict
       accepted / rejected = terminal outcome
  * ``final_acceptance_by`` — email of the operator who decided
  * ``final_acceptance_at`` — UTC timestamp of the decision
  * ``final_acceptance_feedback`` — free-text reason on reject; optional notes on accept
  * ``auto_final_accept`` — when True, the engine SKIPS the human terminus and
       transitions straight to ``done`` after compile (back-compat for callers
       that don't want the new gate, e.g. CI / batch flows)

We intentionally use plain VARCHAR/TEXT/BOOLEAN — NO new enum types — so a
later schema correction doesn't need a coordinated drop-create dance.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-04-21 16:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(text(
            "ALTER TABLE pipeline_tasks "
            "ADD COLUMN IF NOT EXISTS final_acceptance_status VARCHAR(20)"
        ))
        op.execute(text(
            "ALTER TABLE pipeline_tasks "
            "ADD COLUMN IF NOT EXISTS final_acceptance_by VARCHAR(200)"
        ))
        op.execute(text(
            "ALTER TABLE pipeline_tasks "
            "ADD COLUMN IF NOT EXISTS final_acceptance_at TIMESTAMP"
        ))
        op.execute(text(
            "ALTER TABLE pipeline_tasks "
            "ADD COLUMN IF NOT EXISTS final_acceptance_feedback TEXT"
        ))
        op.execute(text(
            "ALTER TABLE pipeline_tasks "
            "ADD COLUMN IF NOT EXISTS auto_final_accept BOOLEAN DEFAULT FALSE"
        ))
    else:
        # SQLite (test/dev) — best-effort add_column; no IF NOT EXISTS, so
        # wrap in try/except to keep idempotency for re-runs.
        for col in [
            sa.Column("final_acceptance_status", sa.String(20), nullable=True),
            sa.Column("final_acceptance_by", sa.String(200), nullable=True),
            sa.Column("final_acceptance_at", sa.DateTime(), nullable=True),
            sa.Column("final_acceptance_feedback", sa.Text(), nullable=True),
            sa.Column("auto_final_accept", sa.Boolean(), nullable=True, server_default=sa.text("0")),
        ]:
            try:
                op.add_column("pipeline_tasks", col)
            except Exception:
                pass


def downgrade() -> None:
    for col_name in (
        "auto_final_accept",
        "final_acceptance_feedback",
        "final_acceptance_at",
        "final_acceptance_by",
        "final_acceptance_status",
    ):
        try:
            op.drop_column("pipeline_tasks", col_name)
        except Exception:
            pass
