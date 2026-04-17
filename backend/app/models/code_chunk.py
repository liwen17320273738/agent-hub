"""Codebase semantic index — chunk-level embeddings for "find by meaning".

One row = one chunk of source code (file + line range) with its vector
embedding. Cosine similarity is computed in Python on read, so this works
even when pgvector isn't available.

Schema:
  code_chunks
    id              uuid PK
    project_id      str  — caller-supplied project namespace (e.g. abs path or repo URL)
    rel_path        str  — file path relative to project root
    language        str  — coarse language tag (py / ts / vue / md / ...)
    start_line      int  — 1-based inclusive
    end_line        int  — 1-based inclusive
    content_hash    str  — sha256 of the chunk text; lets the indexer skip unchanged
    text            text — the actual chunk text (for highlight on retrieval)
    symbols         json — top-level symbols extracted via regex
    embedding       vec  — VectorType(dim) — pgvector when enabled, JSON otherwise
    embedding_model str  — provider model name used (so reindex can detect drift)
    embedding_dim   int  — dimensionality (validates compatibility on search)
    created_at      ts
    updated_at      ts
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Column, DateTime, Index, Integer, String, Text,
)

from ..compat import GUID, JsonDict, VectorType, utcnow_default
from ..database import Base


class CodeChunk(Base):
    __tablename__ = "code_chunks"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    project_id = Column(String(500), nullable=False, index=True)
    rel_path = Column(String(500), nullable=False)
    language = Column(String(20), nullable=False, default="")

    start_line = Column(Integer, nullable=False, default=1)
    end_line = Column(Integer, nullable=False, default=1)

    content_hash = Column(String(64), nullable=False, index=True)
    text = Column(Text, nullable=False)
    symbols = Column(JsonDict(), nullable=False, default=list)

    # Default dim=1536 (OpenAI text-embedding-3-small). The Python search
    # path compares actual lengths so different-dim vectors are simply ignored
    # at retrieval time without crashing.
    embedding = Column(VectorType(1536), nullable=True)
    embedding_model = Column(String(100), nullable=False, default="")
    embedding_dim = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, server_default=utcnow_default(), default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        server_default=utcnow_default(),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        Index("ix_code_chunks_project_path", "project_id", "rel_path"),
    )
