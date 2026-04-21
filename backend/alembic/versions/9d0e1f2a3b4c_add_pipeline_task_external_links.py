"""Add external_links JSON column to pipeline_tasks.

Revision ID: 9d0e1f2a3b4c
Revises: 8c9d0e1f2a3b
Create Date: 2026-04-21 13:00:00.000000

Bridges Agent Hub's task model to external issue trackers (Jira /
GitHub) so the AI Legion is no longer "blind" to the queue humans
actually plan in.

Schema
======
``pipeline_tasks.external_links`` — JSON array of objects::

    [{"kind": "jira",   "key": "AI-7",        "project": "AI",
      "url": "https://acme.atlassian.net/browse/AI-7",  "id": "10042"},
     {"kind": "github", "key": "acme/web#42", "project": "acme/web",
      "url": "https://github.com/acme/web/issues/42",   "id": "9001"}]

Each entry mirrors ``ExternalIssueRef.to_dict()`` from
``app.services.connectors.base``. Backfill default is ``[]`` so all
existing rows behave exactly like before this migration.

Why a JSON column (and not a relation table)
============================================
* Read pattern is "get the task, walk its links" — already loaded
  with the task, no extra round trip.
* Cardinality is tiny (typically 1-2 links per task, never > 10).
* The shape is read by external systems via the API anyway — keeping
  it as JSON dodges a separate Pydantic schema for an
  ``ExternalLinks`` table.
* If we ever need to query "all tasks linked to issue X" we'll add
  a GIN index on PostgreSQL; SQLite dev mode just scans.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.compat import JsonDict


revision = "9d0e1f2a3b4c"
down_revision = "8c9d0e1f2a3b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("pipeline_tasks") as batch:
        batch.add_column(
            sa.Column(
                "external_links",
                JsonDict(),
                nullable=False,
                # JSON literal "[]" — server-side default so the
                # constraint holds for every existing row at upgrade
                # time, including ones inserted concurrently with the
                # migration window.
                server_default=sa.text("'[]'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("pipeline_tasks") as batch:
        batch.drop_column("external_links")
