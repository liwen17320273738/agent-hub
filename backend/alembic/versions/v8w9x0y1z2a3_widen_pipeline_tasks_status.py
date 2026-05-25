"""widen pipeline_tasks.status from VARCHAR(20) to VARCHAR(30)

Reason: "awaiting_final_acceptance" is 26 characters.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "v8w9x0y1z2a3"
down_revision = "u5v6w7x8y9z0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute(
            sa.text("ALTER TABLE pipeline_tasks ALTER COLUMN status TYPE VARCHAR(30)")
        )
    else:
        with op.batch_alter_table("pipeline_tasks") as batch:
            batch.alter_column("status", type_=sa.String(30))


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute(
            sa.text("ALTER TABLE pipeline_tasks ALTER COLUMN status TYPE VARCHAR(20)")
        )
    else:
        with op.batch_alter_table("pipeline_tasks") as batch:
            batch.alter_column("status", type_=sa.String(20))
