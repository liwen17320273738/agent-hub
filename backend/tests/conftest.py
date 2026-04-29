"""Shared test fixtures for Agent Hub backend tests."""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault("JWT_SECRET", "test-secret-must-be-at-least-32-characters-long!")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///file::memory:?cache=shared")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("ADMIN_EMAIL", "test@test.com")
os.environ.setdefault("ADMIN_PASSWORD", "testpassword")
os.environ.setdefault("DEBUG", "true")

from app.database import Base, engine, async_session
from app.main import app
from app.security import create_access_token, hash_password
from app.models.user import User, Org


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db() -> AsyncGenerator[AsyncSession, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db) -> AsyncGenerator[AsyncClient, None]:
    """Depends on ``db`` so ``Base.metadata.create_all`` runs before ASGI calls."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def test_user(db: AsyncSession) -> User:
    """Create a real user in the test DB for auth-dependent tests."""
    org = Org(name="Test Org")
    db.add(org)
    await db.flush()

    user = User(
        org_id=org.id,
        email="testuser@test.com",
        password_hash=hash_password("testpass123"),
        display_name="Test User",
        role="admin",
    )
    db.add(user)
    await db.flush()
    await db.commit()
    return user


@pytest_asyncio.fixture
async def auth_headers(test_user: User) -> dict[str, str]:
    """JWT auth headers tied to a real user in the DB."""
    token = create_access_token({"sub": str(test_user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def sample_task_id(db: AsyncSession, test_user: User) -> str:
    """Create a PipelineTask and return its ID as a string."""
    from app.models.pipeline import PipelineTask

    task = PipelineTask(
        title="Sample Task",
        description="A sample task for tests",
        org_id=test_user.org_id,
        created_by=str(test_user.id),
    )
    db.add(task)
    await db.flush()
    await db.commit()
    return str(task.id)
