"""ORM models for the memory system — long-term memories and learned patterns."""
from __future__ import annotations

import uuid
from typing import Optional, List

from sqlalchemy import Column, DateTime, String, Text, Integer, Float

from ..database import Base
from ..compat import GUID, JsonDict, VectorType, utcnow_default


class TaskMemory(Base):
    """Long-term memory: embeddings + content for semantic retrieval."""
    __tablename__ = "task_memories"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    task_id = Column(String(200), index=True, nullable=False)
    stage_id = Column(String(50), nullable=False)
    role = Column(String(100), nullable=False)
    title = Column(String(500), default="")
    content = Column(Text, default="")
    content_hash = Column(String(64), unique=True, nullable=False)
    summary = Column(Text, default="")
    tags = Column(JsonDict(), default=list)
    quality_score = Column(Float, default=0.0)
    token_count = Column(Integer, default=0)
    embedding = Column(VectorType(1536), nullable=True)
    embedding_model = Column(String(100), default="")
    metadata_extra = Column(JsonDict(), default=dict)
    created_at = Column(DateTime, server_default=utcnow_default())


class LearnedPattern(Base):
    """Patterns extracted from successful task completions."""
    __tablename__ = "learned_patterns"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    pattern_type = Column(String(50), nullable=False)
    role = Column(String(100), nullable=False)
    stage_id = Column(String(50), nullable=False)
    description = Column(Text, default="")
    example_task_ids = Column(JsonDict(), default=list)
    frequency = Column(Integer, default=1)
    confidence = Column(Float, default=0.5)
    created_at = Column(DateTime, server_default=utcnow_default())
    updated_at = Column(DateTime, server_default=utcnow_default())
