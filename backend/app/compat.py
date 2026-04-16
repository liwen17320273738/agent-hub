"""
Cross-database compatibility layer.

Provides GUID, JsonDict, and Vector types that work with both PostgreSQL and SQLite:
- PostgreSQL: native UUID + JSONB + pgvector for best performance
- SQLite: CHAR(36) + JSON + TEXT(JSON) for local development
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import String, Text, TypeDecorator, func
from sqlalchemy.types import JSON

try:
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB as PG_JSONB
except ImportError:
    PG_UUID = None  # type: ignore
    PG_JSONB = None  # type: ignore

try:
    from pgvector.sqlalchemy import Vector as PGVector
    _HAS_PGVECTOR_LIB = True
except ImportError:
    PGVector = None  # type: ignore
    _HAS_PGVECTOR_LIB = False

# Whether to actually use pgvector in PG. Set at startup via enable_pgvector().
# Defaults to False to avoid CREATE TABLE failures when the PG extension is missing.
_use_pgvector = False


def enable_pgvector(enabled: bool = True):
    """Call at startup after verifying CREATE EXTENSION vector succeeds."""
    global _use_pgvector
    _use_pgvector = enabled and _HAS_PGVECTOR_LIB


class GUID(TypeDecorator):
    """Platform-independent UUID type.

    Uses PostgreSQL's native UUID when available, otherwise stores as CHAR(36).
    """
    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql" and PG_UUID is not None:
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class JsonDict(TypeDecorator):
    """Platform-independent JSON type.

    Uses PostgreSQL's JSONB for performance, otherwise standard JSON.
    """
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql" and PG_JSONB is not None:
            return dialect.type_descriptor(PG_JSONB)
        return dialect.type_descriptor(JSON)

    def process_bind_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        return value


class VectorType(TypeDecorator):
    """Platform-independent vector type for embeddings.

    Uses pgvector on PostgreSQL, otherwise stores as JSON text in SQLite.
    """
    impl = Text
    cache_ok = True

    def __init__(self, dim: int = 1536, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql" and _use_pgvector:
            return dialect.type_descriptor(PGVector(self.dim))
        return dialect.type_descriptor(Text)

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql" and _use_pgvector:
            return value
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return json.loads(value)
        return list(value)


def utcnow_default():
    """Cross-database 'now()' default for server_default."""
    return func.now()
