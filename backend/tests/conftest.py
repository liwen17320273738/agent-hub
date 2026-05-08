"""Shared test fixtures for Agent Hub backend."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault("JWT_SECRET", "test-secret-must-be-at-least-32-characters-long!")
if os.environ.get("AGENTHUB_TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["AGENTHUB_TEST_DATABASE_URL"]
else:
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
if os.environ.get("AGENTHUB_TEST_REDIS_URL"):
    os.environ["REDIS_URL"] = os.environ["AGENTHUB_TEST_REDIS_URL"]
elif os.environ.get("AGENTHUB_USE_REAL_TEST_REDIS") == "1":
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
else:
    # redis.asyncio ConnectionPool binds to one event loop; pytest-asyncio strict
    # mode uses a fresh loop per test → reuse of a real Redis client raises
    # RuntimeError: Event loop is closed. Unreachable URL forces in-memory stub.
    os.environ["REDIS_URL"] = "redis://127.0.0.1:63999/15"
os.environ.setdefault("ADMIN_EMAIL", "test@test.com")
os.environ.setdefault("ADMIN_PASSWORD", "testpassword")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("AGENTHUB_SKIP_ENGINE_DISPOSE", "1")
os.environ.setdefault("AGENTHUB_SQLITE_STATIC_POOL", "1")

from app.database import Base, engine, async_session, get_db  # noqa: E402
from app.main import (  # noqa: E402
    _bootstrap_admin,
    _seed_artifact_types,
    app,
)
from app.security import create_access_token, hash_password  # noqa: E402
from app.models.user import User, Org  # noqa: E402


@asynccontextmanager
async def _pytest_disable_app_lifespan(_):
    yield


app.router.lifespan_context = _pytest_disable_app_lifespan

try:
    from app.services.task_workspace import ensure_global_workspace_dirs
    ensure_global_workspace_dirs()
except Exception:
    pass

try:
    from app.services.stage_hooks import register_builtin_hooks
    register_builtin_hooks()
except Exception:
    pass


async def _pytest_seed_database() -> None:
    """Mirror lifespan DB writes without running FastAPI lifespan (avoids SQLite races)."""
    _minimal = os.environ.get("AGENTHUB_TEST_MINIMAL_LIFESPAN") == "1"

    async with async_session() as s:
        await _bootstrap_admin(s)
        await s.commit()

    if not _minimal:
        async with async_session() as s:
            from app.agents.seed import seed_all
            await seed_all(s)
            await s.commit()

        from app.services.skill_loader import discover_skills, sync_skills_to_db
        discover_skills()
        async with async_session() as s:
            await sync_skills_to_db(s)
            await s.commit()

    async with async_session() as s:
        await _seed_artifact_types(s)
        await s.commit()

    try:
        from app.services.sandbox_overrides import preload_overrides
        async with async_session() as s:
            await preload_overrides(s)
            await s.commit()
    except Exception:
        pass


@pytest_asyncio.fixture(autouse=True)
async def _stop_sandbox_listener_after_test():
    yield
    try:
        from app.services.sandbox_overrides import stop_invalidation_listener
        await stop_invalidation_listener()
    except Exception:
        pass


@pytest_asyncio.fixture(scope="function")
async def db() -> AsyncGenerator[AsyncSession, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _pytest_seed_database()
    async with async_session() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db, monkeypatch) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db():
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    app.dependency_overrides[get_db] = _override_get_db

    async def _noop_gateway_pipeline(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.api.gateway._run_pipeline_background",
        _noop_gateway_pipeline,
    )

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def test_user(db: AsyncSession) -> User:
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
    token = create_access_token({"sub": str(test_user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def sample_task_id(db: AsyncSession, test_user: User) -> str:
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
