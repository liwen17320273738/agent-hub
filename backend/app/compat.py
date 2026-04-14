"""
Cross-database compatibility layer.

Provides GUID and JsonDict types that work with both PostgreSQL and SQLite:
- PostgreSQL: native UUID + JSONB for best performance
- SQLite: CHAR(36) + JSON for local development
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


def utcnow_default():
    """Cross-database 'now()' default for server_default."""
    return func.now()
