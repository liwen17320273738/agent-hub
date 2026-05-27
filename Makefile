# Agent Hub — Unified Development Environment
#
# Architecture:
#   - Backend (port 8000): FastAPI — auth, LLM proxy, pipeline, agents, skills, memory
#   - Frontend (port 5200): Vue 3 + Vite
#   - PostgreSQL (port 5432): Primary database
#   - Redis (port 6379): Cache + SSE pub/sub + working memory
#   - Nginx (port 80): Reverse proxy (Docker only)

.PHONY: help check config install dev dev-daemon start stop clean test test-relay lint format-backend migrate \
        docker-start docker-stop docker-logs docker-build backup reset-admin verify-login \
        provision deploy-server

PYTHON ?= python3
# Directory containing this Makefile (repo root even when `make -C` is used).
REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

help:
	@echo "Agent Hub Development Commands:"
	@echo ""
	@echo "  make check           - Check if all required tools are installed"
	@echo "  make config          - Generate local config files from examples"
	@echo "  make install         - Install all dependencies (frontend + backend)"
	@echo "  make migrate         - alembic upgrade head (merged env like make dev)"
	@echo "  make dev             - Start all services in development mode"
	@echo "  make reset-admin    - Set DB user password to ADMIN_PASSWORD (fix login mismatch)"
	@echo "  make verify-login   - POST /auth/login with merged .env (same as make dev); must print PASS"
	@echo "  make dev-daemon      - Start all services in background (daemon mode)"
	@echo "  make stop            - Stop all running services"
	@echo "  make clean           - Clean up processes and temporary files"
	@echo "  make test            - Run all tests"
	@echo "  make test-relay      - Backend relay gateway integration tests only"
	@echo "  make lint            - Lint all code (backend: ruff check only)"
	@echo "  make format-backend  - Backend: ruff format (optional; touches many files)"
	@echo ""
	@echo "Docker Commands:"
	@echo "  make docker-build    - Build Docker images (internal PG/Redis)"
	@echo "  make docker-start    - Start Docker services (internal PG/Redis)"
	@echo "  make docker-stop     - Stop Docker services"
	@echo "  make docker-logs     - View Docker logs"
	@echo ""
	@echo "Production:"
	@echo "  make provision       - One-command deploy on a fresh VPS"
	@echo "  make deploy-server   - Deploy with external PostgreSQL + Docker Redis"
	@echo ""
	@echo "Maintenance:"
	@echo "  make backup          - Backup PostgreSQL database"

# ── Check Dependencies ──────────────────────────────────────────────────────

check:
	@$(PYTHON) ./scripts/check.py

# ── Generate Config ──────────────────────────────────────────────────────────

config:
	@$(PYTHON) ./scripts/configure.py

# ── Install ──────────────────────────────────────────────────────────────────

install:
	@echo "Installing backend dependencies..."
	@cd backend && pip install -e ../packages/agent-hub-pipeline && pip install -r requirements.txt
	@echo "Installing frontend dependencies..."
	@pnpm install
	@echo "✓ All dependencies installed"

# ── Development Mode ─────────────────────────────────────────────────────────

dev:
	@./scripts/serve.sh --dev

dev-daemon:
	@./scripts/start-daemon.sh

start:
	@./scripts/serve.sh --prod

# Use backend/.venv Python if available; fall back to system python3.
VENV_PYTHON := $(if $(shell test -x backend/.venv/bin/python3 && echo 1),backend/.venv/bin/python3,$(PYTHON))

# Same env merge as scripts/serve.sh: backend/.env then repo-root .env (latter wins on duplicates).
# Ensures ADMIN_* / DATABASE_URL match the running API before syncing password in DB.
reset-admin:
	@set -a; \
	[ -f "$(REPO_ROOT)/backend/.env" ] && . "$(REPO_ROOT)/backend/.env"; \
	[ -f "$(REPO_ROOT)/.env" ] && . "$(REPO_ROOT)/.env"; \
	set +a; \
	cd "$(REPO_ROOT)/backend" && $(VENV_PYTHON) -m scripts.reset_admin_password

# Same DATABASE_URL merge as scripts/serve.sh; avoids migrating localhost while the API uses root .env.
migrate:
	@set -a; \
	[ -f "$(REPO_ROOT)/backend/.env" ] && . "$(REPO_ROOT)/backend/.env"; \
	[ -f "$(REPO_ROOT)/.env" ] && . "$(REPO_ROOT)/.env"; \
	set +a; \
	cd "$(REPO_ROOT)/backend" && PYTHONPATH=. $(VENV_PYTHON) -m alembic upgrade head

verify-login:
	@./scripts/verify-dev-login.sh

stop:
	@echo "Stopping all services..."
	@-pkill -f "uvicorn app.main:app" 2>/dev/null || true
	@-pkill -f "vite" 2>/dev/null || true
	@sleep 1
	@echo "✓ All services stopped"

clean: stop
	@echo "Cleaning up..."
	@-rm -rf backend/__pycache__ 2>/dev/null || true
	@-rm -rf backend/.pytest_cache 2>/dev/null || true
	@-rm -rf logs/*.log 2>/dev/null || true
	@echo "✓ Cleanup complete"

# ── Testing ──────────────────────────────────────────────────────────────────

test:
	@cd backend && $(PYTHON) -m pytest tests/ -v

test-unit:
	@cd backend && $(PYTHON) -m pytest tests/unit/ -v

test-relay:
	@cd backend && $(MAKE) test-relay

lint:
	@cd backend && $(PYTHON) -m ruff check . 2>/dev/null || echo "ruff not installed, skipping backend lint"
	@cd frontend && pnpm lint 2>/dev/null || echo "frontend lint skipped"

# Optional: full-tree style normalization — run sparingly (large diffs; use a dedicated PR).
format-backend:
	@cd backend && $(PYTHON) -m ruff format .

# ── Docker ───────────────────────────────────────────────────────────────────

docker-build:
	@docker compose -f docker/docker-compose.yml build

docker-start:
	@docker compose -f docker/docker-compose.yml up -d

docker-stop:
	@docker compose -f docker/docker-compose.yml down

docker-logs:
	@docker compose -f docker/docker-compose.yml logs -f

docker-firecrawl:
	@docker compose -f docker/docker-compose.firecrawl.yml up -d
	@echo "Firecrawl: http://localhost:$${FIRECRAWL_PORT:-3002}"
	@echo "在 .env 中设置 FIRECRAWL_SELF_HOSTED_URL=http://localhost:$${FIRECRAWL_PORT:-3002}"

docker-firecrawl-down:
	@docker compose -f docker/docker-compose.firecrawl.yml down

# ── Production ───────────────────────────────────────────────────────────────

provision:
	@echo ""
	@echo "=========================================="
	@echo "  Running production deployer..."
	@echo "=========================================="
	@echo ""
	@echo "  This will:"
	@echo "    1. Install Docker if missing"
	@echo "    2. Clone/pull agent-hub to /opt/agent-hub"
	@echo "    3. Prompt for .env configuration"
	@echo "    4. Optionally set up HTTPS via Caddy"
	@echo "    5. Build & start all containers"
	@echo ""
	@echo "  Run from your target server (not locally)."
	@echo ""
	@sudo ./scripts/provision.sh

# ── Server Deployment (reuses external PostgreSQL) ────────────────────────

deploy-server:
	@echo ""
	@echo "=========================================="
	@echo "  Deploying Agent Hub (external PG)..."
	@echo "=========================================="
	@echo ""
	@echo "  This will:"
	@echo "    1. Ensure Docker Compose plugin is installed"
	@echo "    2. Verify PostgreSQL connectivity"
	@echo "    3. Clean up test data (optional)"
	@echo "    4. Build Docker images"
	@echo "    5. Start all containers"
	@echo ""
	@./scripts/deploy-server.sh

# ── Maintenance ─────────────────────────────────────────────────────────────

backup:
	@./scripts/backup-db.sh
