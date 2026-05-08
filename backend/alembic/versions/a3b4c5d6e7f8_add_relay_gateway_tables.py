"""add relay gateway (customer API keys + org balance)

Revision ID: a3b4c5d6e7f8
Revises: 28b5a2d57b6a
Create Date: 2026-05-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "28b5a2d57b6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orgs",
        sa.Column("relay_balance_usd", sa.Float(), server_default="0", nullable=False),
    )
    op.alter_column("orgs", "relay_balance_usd", server_default=None)

    op.create_table(
        "relay_api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False, server_default=""),
        sa.Column("key_prefix", sa.String(40), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_relay_api_keys_org_id", "relay_api_keys", ["org_id"])
    op.create_index("ix_relay_api_keys_key_prefix", "relay_api_keys", ["key_prefix"])
    op.create_index("ix_relay_api_keys_key_hash", "relay_api_keys", ["key_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_relay_api_keys_key_hash", table_name="relay_api_keys")
    op.drop_index("ix_relay_api_keys_key_prefix", table_name="relay_api_keys")
    op.drop_index("ix_relay_api_keys_org_id", table_name="relay_api_keys")
    op.drop_table("relay_api_keys")
    op.drop_column("orgs", "relay_balance_usd")
