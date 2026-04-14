# Agent Hub — AI Assistant Instructions

## Repository Overview

Agent Hub is a full-stack AI agent platform.

- **Backend**: `backend/` — FastAPI (Python 3.9+), SQLAlchemy async, PostgreSQL, Redis
- **Frontend**: `src/` — Vue 3, Vite 5, TypeScript, Pinia, Element Plus
- **Skills**: `skills/` — Markdown-first agent skills (`public/` + `custom/`)
- **Docker**: `docker/` — Compose + Nginx for production
- **Scripts**: `scripts/` — Dev tooling (check, configure, serve, daemon)
- **Docs**: `docs/` — Architecture, API, Setup, Configuration

## Key Commands

```bash
make check    # Verify dependencies
make config   # Generate local config files
make install  # Install all dependencies
make dev      # Start all services
make test     # Run tests
make stop     # Stop services
```

## Architecture

- Backend follows gateway pattern: thin API routers → thick services
- Pipeline engine with 6-layer maturation stack
- DAG orchestrator for parallel stage execution
- 3-layer memory: long-term (PG), working (Redis), patterns (PG)
- Multi-provider LLM routing (OpenAI, Anthropic, Gemini, DeepSeek, etc.)

## Style

- Backend: Python 3.9+, async/await, type hints, ruff
- Frontend: TypeScript, Vue 3 Composition API, Pinia
- No comments that narrate what code does
- Services should not import from API layer
