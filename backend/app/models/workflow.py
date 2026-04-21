"""Saved Workflow Builder docs.

A ``Workflow`` row is one user-edited DAG saved from the Workflow
Builder UI (``/workflow-builder``). It's the server-backed sibling of
the ``localStorage`` autosave: the same ``WorkflowDoc`` JSON shape that
the frontend already exports to disk, just persisted per-org with a
human name + description.

Why a separate table (and not piggybacking on ``pipeline_tasks``):
    * A workflow is a *template* (no runs, no stages-as-rows). Tasks
      are *executions* of a workflow — different lifecycle, different
      access pattern.
    * Listing "my workflows" should not have to scan every historical
      task with ``custom_stages IS NOT NULL``.
    * Future: we'll likely add versioning / org-shared / starred bits
      on this table without bloating ``pipeline_tasks``.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..compat import GUID, JsonDict, utcnow_default


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    created_by: Mapped[str] = mapped_column(String(200), default="system")

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")

    # Verbatim WorkflowDoc from the builder UI
    # (src/services/workflowBuilder.ts). Kept as an opaque JSON blob —
    # the source of truth for the UI's representation lives client-
    # side, and migrating that schema in two places is a footgun.
    doc: Mapped[dict] = mapped_column(JsonDict(), default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=utcnow_default(), onupdate=datetime.utcnow,
    )
