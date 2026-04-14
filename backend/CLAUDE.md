# CLAUDE.md — Backend

## Quick Reference

```bash
# Install
pip install -r requirements.txt

# Dev server
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Run tests
python3 -m pytest tests/ -v

# Lint
python3 -m ruff check .

# Format
python3 -m ruff check . --fix && python3 -m ruff format .
```

## Directory Layout

```
backend/
├── app/
│   ├── main.py           # FastAPI entry, router registration, lifespan
│   ├── config.py          # Settings from environment variables
│   ├── database.py        # AsyncSession, engine, Base, get_db
│   ├── security.py        # JWT, bcrypt, auth dependencies
│   ├── redis_client.py    # Redis singleton
│   ├── api/               # Route handlers (thin — delegate to services)
│   ├── services/          # Business logic (thick — all domain logic here)
│   ├── models/            # SQLAlchemy ORM models
│   ├── schemas/           # Pydantic request/response schemas
│   └── middleware/         # ASGI middleware (rate limiting)
├── tests/
│   ├── conftest.py        # Fixtures (in-memory SQLite, test client)
│   ├── unit/              # Pure unit tests
│   └── integration/       # Tests requiring database/Redis
├── alembic/               # Database migrations
├── requirements.txt
└── Dockerfile
```

## Key Principles

1. **API layer is thin**: Routers only parse requests and return responses. All logic in `services/`.
2. **Services are independent**: Services should not import from `api/`. Cross-service calls are allowed.
3. **ORM models are passive**: No business logic in model classes.
4. **Async everywhere**: All database and Redis operations use async/await.
5. **Config from environment**: No hardcoded secrets or URLs. Use `app.config.settings`.

## Database

- **Engine**: PostgreSQL + SQLAlchemy async (asyncpg driver)
- **Migrations**: Alembic (`alembic upgrade head` to apply)
- **Session**: Use `get_db` dependency to get `AsyncSession`

## API Authentication

- JWT tokens (HS256) via `Authorization: Bearer <token>`
- Pipeline endpoints accept `X-Pipeline-Key` header as alternative
- `get_current_user` dependency for protected routes
- `get_pipeline_auth` for pipeline-specific endpoints

## Testing

- **conftest.py** sets up in-memory SQLite with `sqlite+aiosqlite`
- Mocked Redis for isolated tests
- Run specific file: `python3 -m pytest tests/unit/test_llm_router.py -v`
