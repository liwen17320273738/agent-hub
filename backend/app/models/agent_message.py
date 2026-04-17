"""``agent_messages`` table — persisted async messages on the agent bus.

Mirrors every publish on the Redis ``agenthub:agent:bus`` channel so late
subscribers can replay history and operators can audit who told whom what.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..compat import GUID, JsonDict, utcnow_default


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(String(100), index=True)
    sender: Mapped[str] = mapped_column(String(100), index=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("pipeline_tasks.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    payload: Mapped[dict] = mapped_column(JsonDict(), default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default(), index=True)

    __table_args__ = (
        Index("ix_agent_messages_topic_created", "topic", "created_at"),
    )
