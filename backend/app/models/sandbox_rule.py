"""ORM model for DB-backed sandbox rule overrides.

Rationale
=========
``ROLE_TOOL_WHITELIST`` in ``services/tools/registry.py`` is the
authoritative *baseline* — it ships with the codebase, is reviewed in
PRs, and reflects "what should this role be allowed to do by default".

But operations needs the ability to make exceptions WITHOUT touching
code: granting a temporary capability for a one-off incident, locking
down a tool that's misbehaving, or experimenting with a new policy.
Each row in this table is one such exception:

    (role, tool) → allow=true|false (overrides baseline)

The runtime resolver (``role_allowed_with_overrides``) consults this
table first; if no row exists it falls back to the in-code baseline.
Empty table → behaviour identical to before this feature shipped.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..compat import GUID, utcnow_default


class SandboxRule(Base):
    """One operator-applied exception to the in-code role/tool whitelist.

    A row's effect is binary: ``allowed=True`` grants the role permission
    to call the tool (overriding a code-level deny), ``allowed=False``
    forbids the role from calling the tool (overriding a code-level
    allow). To "revert to default" delete the row.
    """
    __tablename__ = "sandbox_rules"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    role: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tool: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=utcnow_default(), onupdate=datetime.utcnow,
    )

    __table_args__ = (
        UniqueConstraint("role", "tool", name="uq_sandbox_rules_role_tool"),
        Index("ix_sandbox_rules_role_tool", "role", "tool"),
    )
