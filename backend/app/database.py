"""
Database engine — supports both PostgreSQL (production) and SQLite (development).

The engine type is auto-detected from DATABASE_URL:
- postgresql+asyncpg://... → PostgreSQL with connection pooling
- sqlite+aiosqlite:///...  → SQLite for local dev (no Docker needed)
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


def _build_engine():
    url = settings.database_url
    is_sqlite = url.startswith("sqlite")

    kwargs = {"echo": settings.debug}
    if not is_sqlite:
        kwargs.update(pool_size=20, max_overflow=10, pool_pre_ping=True)

    return create_async_engine(url, **kwargs)


engine = _build_engine()

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
async_session_factory = async_session


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:  # type: ignore[misc]
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
