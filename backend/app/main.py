"""
Agent Hub — FastAPI Backend

Architecture follows deer-flow gateway pattern:
  - create_app() factory for testability
  - Routers organized by domain with OpenAPI tags
  - Lifespan manages startup/shutdown lifecycle
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import async_session, engine, Base
from .models import *  # noqa: F401,F403  — ensure all models are registered
from .security import hash_password
from .middleware.rate_limit import RateLimitMiddleware

from .api import (
    auth,
    agents,
    models,
    skills,
    llm_proxy,
    conversations,
    pipeline,
    observability,
    gateway,
    events,
    executor,
    memory,
    deploy,
    interaction,
    delivery_docs,
    mcps,
    eval as eval_api,
    plans as plans_api,
    codebase as codebase_api,
    agent_bus as agent_bus_api,
    learning as learning_api,
    sandbox as sandbox_api,
    scheduler as scheduler_api,
    integrations as integrations_api,
    workflows as workflows_api,
    openai_compat,
    share as share_api,
    workspaces as workspaces_api,
    credentials as credentials_api,
    deliverables as deliverables_api,
    task_artifacts as task_artifacts_api,
    worktree as worktree_api,
    translate as translate_api,
    specs as specs_api,
)

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agent-hub")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup checks, DB init, seed data."""
    logger.info("Starting Agent Hub backend...")

    if not settings.jwt_secret or len(settings.jwt_secret) < 32:
        if settings.debug:
            import secrets
            settings.jwt_secret = secrets.token_urlsafe(48)
            logger.warning(
                "JWT_SECRET not set or too short — generated ephemeral secret. "
                "Set JWT_SECRET in .env for persistent sessions."
            )
        else:
            raise RuntimeError(
                "JWT_SECRET must be set to a string of at least 32 characters in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )

    # Reject weak / default admin credentials in production.  Debug mode
    # allows the old "admin@example.com:changeme" for local development.
    _weak_admin_password = (
        not settings.admin_password
        or len(settings.admin_password) < 12
        or settings.admin_password.strip() in (
            "changeme", "admin", "password", "admin123", "123456"
        )
    )
    if not settings.debug and _weak_admin_password:
        raise RuntimeError(
            "生产环境必须设置强管理员密码（至少 12 个字符）。"
            "请在 .env 中配置 ADMIN_PASSWORD。"
        )
    if _weak_admin_password and settings.admin_password:
        logger.warning(
            "ADMIN_PASSWORD 强度不足（%d 字符），仅在调试模式下允许。"
            "生产环境请在 .env 中设置强密码。",
            len(settings.admin_password),
        )

    if "sqlite" in settings.database_url or settings.debug:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables ensured via create_all (dev/SQLite mode).")
    else:
        from sqlalchemy import text
        from .compat import enable_pgvector

        # Probe pgvector availability on EVERY startup (not just first-run).
        # Without this, VectorType columns silently use TEXT mode whenever an
        # existing-tables DB is reattached, even if the extension is installed.
        try:
            async with engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            enable_pgvector(True)
            logger.info("pgvector extension enabled.")
        except Exception as e:
            enable_pgvector(False)
            logger.warning(
                "pgvector not available (%s) — VectorType falls back to JSON-text. "
                "For >100k chunks, install the extension and restart.",
                e,
            )

        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(
                    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'users')"
                ))
                has_tables = result.scalar()
            if not has_tables:
                logger.warning(
                    "PostgreSQL detected but no tables found. "
                    "Running create_all to bootstrap schema..."
                )
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                logger.info("Database tables created via create_all (first-run bootstrap).")
            else:
                logger.info("PostgreSQL tables exist. Skipping create_all.")
        except Exception as e:
            logger.error(f"DB check failed: {e}. Attempting create_all as fallback...")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

    async with async_session() as db:
        await _bootstrap_admin(db)
        await db.commit()

    async with async_session() as db:
        from .agents.seed import seed_all

        await seed_all(db)
        await db.commit()
    logger.info("Seed data loaded.")

    async with async_session() as db:
        await _seed_artifact_types(db)
        await db.commit()

    from .services.skill_loader import discover_skills, sync_skills_to_db
    skills_found = discover_skills()
    logger.info(f"Loaded {len(skills_found)} filesystem skills.")

    async with async_session() as db:
        synced = await sync_skills_to_db(db)
        await db.commit()
    if synced:
        logger.info(f"Synced {synced} filesystem skills to database.")

    # Physical workspace (data/workspace) — must exist before code extraction
    try:
        from .services.task_workspace import ensure_global_workspace_dirs

        _ws_root = ensure_global_workspace_dirs()
        logger.info("Workspace root ready: %s", _ws_root)
    except Exception as exc:
        logger.error("Workspace directory init failed: %s", exc)

    # Register built-in stage hooks (code extractor, test validator, etc.)
    try:
        from .services.stage_hooks import register_builtin_hooks
        register_builtin_hooks()
        logger.info("Stage hooks registered.")
    except Exception as exc:
        logger.warning(f"Failed to register stage hooks: {exc}")

    # Probe LLM providers in background (local models can be slow, don't block startup)
    try:
        from .services.llm_router import probe_all_providers

        async def _background_probe():
            try:
                health = await probe_all_providers()
                healthy = [p for p, ok in health.items() if ok]
                unhealthy = [p for p, ok in health.items() if not ok]
                if healthy:
                    logger.info(f"LLM providers healthy: {', '.join(healthy)}")
                if unhealthy:
                    logger.warning(f"LLM providers unhealthy: {', '.join(unhealthy)}")
                if not healthy:
                    logger.error("No healthy LLM providers! Pipeline will not work.")
            except Exception as exc:
                logger.warning(f"LLM provider probe failed: {exc}")

        import asyncio
        asyncio.create_task(_background_probe())
        logger.info("LLM provider probe started in background...")
    except Exception as exc:
        logger.warning(f"LLM provider probe skipped: {exc}")

    # Eager-load DB-backed sandbox overrides into the in-memory cache so
    # the FIRST tool call doesn't pay the table-scan cost. Failures here
    # are logged and ignored — empty cache simply means "use in-code
    # defaults", which is the same behaviour as before this feature.
    try:
        from .services.sandbox_overrides import (
            preload_overrides,
            start_invalidation_listener,
        )
        async with async_session() as db:
            n_rules = await preload_overrides(db)
        logger.info(f"Sandbox overrides preloaded: {n_rules} rules.")
        # Start the cross-process pubsub listener AFTER preload so the
        # cache has a baseline before peers can mutate it. Idempotent
        # — safe to call again on hot reload.
        await start_invalidation_listener()
    except Exception as exc:
        logger.warning(f"Sandbox preload skipped: {exc}")

    # Opt-in background task that periodically re-crawls GitHub for
    # new SKILL.md files. Controlled by SKILL_CRAWLER_ENABLED=1; see
    # services/skill_crawler_scheduler.py for the full env surface.
    try:
        from .services import skill_crawler_scheduler
        skill_crawler_scheduler.start()
    except Exception as exc:
        logger.warning(f"Skill crawler scheduler not started: {exc}")

    try:
        import asyncio

        from .services.translator import prewarm_from_recent_task_titles

        async def _pregen() -> None:
            try:
                await prewarm_from_recent_task_titles()
            except Exception as e:
                logger.warning("translate pregen background task failed: %s", e)

        asyncio.create_task(_pregen())
    except Exception as exc:
        logger.warning("translate pregen not scheduled: %s", exc)

    yield

    try:
        from .services.sandbox_overrides import stop_invalidation_listener
        await stop_invalidation_listener()
    except Exception:
        pass

    try:
        from .services import skill_crawler_scheduler
        await skill_crawler_scheduler.stop()
    except Exception:
        pass

    await engine.dispose()
    logger.info("Agent Hub backend stopped.")


async def _seed_artifact_types(db):
    from sqlalchemy import select
    from .models.task_artifact import ArtifactTypeRegistry, BUILTIN_ARTIFACT_TYPES

    existing = await db.execute(select(ArtifactTypeRegistry.type_key))
    existing_keys = {r[0] for r in existing.all()}
    added = 0
    for spec in BUILTIN_ARTIFACT_TYPES:
        if spec["type_key"] not in existing_keys:
            db.add(ArtifactTypeRegistry(**spec))
            added += 1
    if added:
        await db.flush()
        logger.info(f"Seeded {added} artifact types.")


async def _bootstrap_admin(db):
    from sqlalchemy import select, func
    from .models.user import Org, User

    count_result = await db.execute(select(func.count()).select_from(User))
    if count_result.scalar() > 0:
        return

    if not settings.admin_email or not settings.admin_password:
        logger.warning(
            "首次启动但 ADMIN_EMAIL / ADMIN_PASSWORD 未设置，"
            "跳过管理员创建。请设置后重启，或通过 API 注册首个用户。"
        )
        return

    org = Org(name="Agent Hub")
    db.add(org)
    await db.flush()

    admin = User(
        org_id=org.id,
        email=settings.admin_email.lower(),
        password_hash=hash_password(settings.admin_password),
        display_name="管理员",
        role="admin",
    )
    db.add(admin)
    await db.flush()
    logger.info(f"Created initial admin: {settings.admin_email}")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    application = FastAPI(
        title="Agent Hub API",
        description="""
## Agent Hub API

AI Agent Hub — 全栈智能体协作平台

### Features

- **Agent Management**: Create and manage AI agents with custom prompts
- **Multi-Provider LLM**: Route to OpenAI, Anthropic, Gemini, DeepSeek, etc.
- **Pipeline Orchestration**: Linear and DAG-based task execution
- **Skill Marketplace**: Browse, install, and execute agent skills
- **Memory System**: Long-term, working, and pattern-based memory
- **Gateway Channels**: Feishu, QQ, OpenClaw integrations
- **Real-time Events**: SSE streaming for pipeline updates
        """,
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=[
            {"name": "auth", "description": "Authentication and user management"},
            {"name": "agents", "description": "Agent CRUD and configuration"},
            {"name": "conversations", "description": "Chat conversations and messages"},
            {"name": "chat", "description": "LLM chat proxy with streaming"},
            {"name": "pipeline", "description": "Pipeline task orchestration"},
            {"name": "skills", "description": "Skill marketplace and execution"},
            {"name": "memory", "description": "Memory search and management"},
            {"name": "executor", "description": "Code execution via Claude CLI"},
            {"name": "events", "description": "Real-time SSE event streaming"},
            {"name": "gateway", "description": "External channel webhooks (Feishu, QQ)"},
            {"name": "models", "description": "LLM model provider management"},
            {"name": "observability", "description": "Traces, audit logs, approvals"},
            {"name": "deploy", "description": "Deploy to Vercel, Cloudflare, WeChat, app stores"},
            {"name": "interaction", "description": "Preview, feedback loop, post-launch monitoring"},
            {"name": "health", "description": "Health check and system status"},
        ],
    )

    # CORS
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting
    application.add_middleware(RateLimitMiddleware)

    # ── Global Exception Handlers ────────────────────────────────────────
    from fastapi.responses import JSONResponse
    from fastapi import Request as _Request

    @application.exception_handler(Exception)
    async def global_exception_handler(_request: _Request, exc: Exception):
        logger.error("[unhandled] %s: %s", type(exc).__name__, str(exc)[:500], exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "服务器内部错误", "error_type": type(exc).__name__},
        )

    @application.exception_handler(HTTPException)
    async def http_exception_handler(_request: _Request, exc: HTTPException):
        logger.warning("[http-error] %s %s: %s", exc.status_code, exc.detail, _request.url.path)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": str(exc.detail)},
            headers=getattr(exc, "headers", None),
        )

    # ── Routers ──────────────────────────────────────────────────────────
    application.include_router(auth.router, prefix="/api")
    application.include_router(agents.router, prefix="/api")
    application.include_router(conversations.router, prefix="/api")
    application.include_router(llm_proxy.router, prefix="/api")
    application.include_router(pipeline.router, prefix="/api")
    application.include_router(skills.router, prefix="/api")
    application.include_router(memory.router, prefix="/api")
    application.include_router(executor.router, prefix="/api")
    application.include_router(events.router, prefix="/api")
    application.include_router(gateway.router, prefix="/api")
    application.include_router(models.router, prefix="/api")
    application.include_router(observability.router)
    application.include_router(deploy.router, prefix="/api")
    application.include_router(interaction.router, prefix="/api")
    application.include_router(delivery_docs.router, prefix="/api")
    application.include_router(mcps.router, prefix="/api")
    application.include_router(eval_api.router, prefix="/api")
    application.include_router(plans_api.router, prefix="/api")
    application.include_router(codebase_api.router, prefix="/api")
    application.include_router(agent_bus_api.router, prefix="/api")
    application.include_router(learning_api.router)
    application.include_router(sandbox_api.router)
    application.include_router(scheduler_api.router)
    application.include_router(integrations_api.router)
    application.include_router(workflows_api.router, prefix="/api")
    application.include_router(share_api.router, prefix="/api")
    application.include_router(workspaces_api.router, prefix="/api")
    application.include_router(credentials_api.router, prefix="/api")
    application.include_router(deliverables_api.router)
    application.include_router(task_artifacts_api.router, prefix="/api")
    application.include_router(worktree_api.router, prefix="/api")
    application.include_router(specs_api.router, prefix="/api")
    application.include_router(translate_api.router)

    # OpenAI-compatible proxy (no /api prefix — matches /v1/chat/completions)
    application.include_router(openai_compat.router)

    # ── Health & Config ──────────────────────────────────────────────────

    @application.get("/health", tags=["health"])
    async def health():
        """Health check endpoint."""
        provider_keys = settings.get_provider_keys()
        db_type = "postgresql" if "postgresql" in settings.database_url else "sqlite"

        from .redis_client import _fallback_mode
        cache_type = "memory-fallback" if _fallback_mode else "redis"

        from .services.llm_router import get_provider_health
        provider_health = get_provider_health()

        from .services.task_workspace import ensure_global_workspace_dirs

        workspace_root = str(ensure_global_workspace_dirs())
        workspace_writable = True
        workspace_error: str | None = None
        try:
            probe = ensure_global_workspace_dirs() / ".probe_write"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except Exception as wexc:
            workspace_writable = False
            workspace_error = str(wexc)

        return {
            "status": "healthy",
            "service": "agent-hub",
            "version": "2.0.0",
            "database": db_type,
            "cache": cache_type,
            "providers_count": len(provider_keys),
            "providers_healthy": [p for p, ok in provider_health.items() if ok],
            "providers_unhealthy": [p for p, ok in provider_health.items() if not ok],
            "deploy_platforms_count": sum(1 for _, v in [
                ("vercel", settings.vercel_token),
                ("cloudflare", settings.cloudflare_api_token),
                ("miniprogram", settings.wechat_mp_appid),
            ] if v),
            "workspace": {
                "root": workspace_root,
                "writable": workspace_writable,
                "error": workspace_error,
            },
        }

    @application.get("/api/config", tags=["health"])
    async def public_config():
        """Public configuration for frontend (no secrets)."""
        keys = settings.get_provider_keys()
        return {
            "providers": list(keys.keys()),
            "default_model": settings.llm_model,
            "features": {
                "pipeline": True,
                "skill_center": True,
                "token_tracking": True,
                "multi_provider": len(keys) > 1,
                "memory_layer": True,
                "dag_orchestrator": True,
                "skill_marketplace": True,
                "self_verify": True,
                "guardrails": True,
                "observability": True,
            },
        }

    return application


# Create app instance for uvicorn
app = create_app()
