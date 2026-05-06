"""ORM models for the memory system — long-term memories, learned patterns, and data collections."""
from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, String, Text, Integer, Float, Boolean, ForeignKey

from ..database import Base
from ..compat import GUID, JsonDict, VectorType, utcnow_default


class KnowledgeCollection(Base):
    """A named, source-tracked group of ingested data items (web pages, documents, etc.).

    Every collection belongs to a workspace and has a source type so the
    ingester layer knows how to refresh it. ``access_scope`` controls which
    ``TaskMemory`` searches can find entries from this collection.
    """
    __tablename__ = "knowledge_collections"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, default="")
    workspace_id = Column(GUID(), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    org_id = Column(GUID(), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=True, index=True)

    # Source tracking — what created this collection
    source_type = Column(String(20), nullable=False, default="manual")  # manual / web_scrape / upload / api
    source_uri = Column(String(1000), default="")         # e.g. the root URL for a web scrape
    source_config = Column(JsonDict(), default=dict)       # e.g. firecrawl crawl params

    # Access control for memory searches:
    #   "workspace" — any task in the workspace can search
    #   "task"      — only the owning task can search
    #   "public"    — any workspace can see (built-in knowledge)
    access_scope = Column(String(20), nullable=False, default="workspace")

    item_count = Column(Integer, default=0)               # how many memory entries belong
    is_active = Column(Boolean, default=True)
    created_by = Column(String(200), default="system")
    created_at = Column(DateTime, server_default=utcnow_default())
    updated_at = Column(DateTime, server_default=utcnow_default())

    # Convenience back-reference — not loaded by default
    # memories = relationship("TaskMemory", ...)


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
    collection_id = Column(GUID(), ForeignKey("knowledge_collections.id", ondelete="SET NULL"), nullable=True, index=True)
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
