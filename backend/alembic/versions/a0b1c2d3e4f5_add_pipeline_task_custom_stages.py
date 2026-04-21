"""Add custom_stages JSON column to pipeline_tasks.

Revision ID: a0b1c2d3e4f5
Revises: 9d0e1f2a3b4c
Create Date: 2026-04-21 16:00:00.000000

Backs the Workflow Builder's "Run" button:

* When a user designs a custom DAG in the visual builder, the spec
  is POSTed alongside ``template="custom"`` on task creation. The
  ``pipeline_stages`` rows persist enough to render the task page,
  but they don't carry ``depends_on`` (the DAG topology) — that
  lives only on the DAGStage objects.
* On ``/dag-run`` (and on resume / restart), the orchestrator needs
  the full topology to schedule batches. We persist the spec verbatim
  on the parent task as JSON so the worker can rehydrate
  ``DAGStage`` instances without re-asking the client.

Shape mirrors ``BackendStage`` from ``src/services/workflowBuilder.ts``::

    [{
        "stage_id": "planning", "label": "需求规划", "role": "product-manager",
        "depends_on": [], "max_retries": 0, "on_failure": "halt",
        "human_gate": false, "skip_condition": null,
        "model_override": null, "quality_gate_min": null
    }, ...]

Backfills to NULL — ``custom_stages IS NULL`` means "use the named
template", preserving today's behavior for every existing task.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.compat import JsonDict


revision = "a0b1c2d3e4f5"
down_revision = "9d0e1f2a3b4c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("pipeline_tasks") as batch:
        batch.add_column(
            sa.Column("custom_stages", JsonDict(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("pipeline_tasks") as batch:
        batch.drop_column("custom_stages")
