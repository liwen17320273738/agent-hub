"""ORM model for per-execution-attempt stage run logs."""
from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, String, Text, Integer, Float

from ..database import Base
from ..compat import GUID, utcnow_default


class StageRunLog(Base):
    """Record of a single stage execution attempt.

    Each time a stage runs (including retries), a new row is inserted.
    This enables the Workflow Builder to show per-node IO preview,
    execution history, and "retry from this node" functionality.
    """
    __tablename__ = "stage_run_logs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    task_id = Column(String(200), index=True, nullable=False)
    stage_id = Column(String(50), nullable=False)
    label = Column(String(100), default="")
    role = Column(String(100), default="")

    # Snapshot of inputs sent to the agent
    model = Column(String(100), default="")
    model_tier = Column(String(20), default="")
    input_snapshot = Column(Text, default="")         # system prompt + user message (truncated)
    input_token_count = Column(Integer, default=0)

    # Output produced
    output = Column(Text, default="")
    output_token_count = Column(Integer, default=0)

    # Result
    success = Column(Integer, default=0)               # 0=fail, 1=success
    error_message = Column(Text, default="")
    duration_ms = Column(Integer, default=0)

    # Quality gate
    quality_score = Column(Float, nullable=True)
    gate_status = Column(String(20), default="")

    # Verification
    verify_status = Column(String(10), default="")

    # Trace link
    trace_id = Column(String(100), default="")

    created_at = Column(DateTime, server_default=utcnow_default())
