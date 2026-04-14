# Agent Hub — Unified Development Environment
#
# Architecture:
#   - Backend (port 8000): FastAPI — auth, LLM proxy, pipeline, agents, skills, memory
#   - Frontend (port 5200): Vue 3 + Vite
#   - PostgreSQL (port 5432): Primary database
#   - Redis (port 6379): Cache + SSE pub/sub + working memory
#   - Nginx (port 80): Reverse proxy (Docker only)

.PHONY: help check config install dev dev-daemon start stop clean test lint \
        docker-start docker-stop docker-logs docker-build

PYTHON ?= python3

help:
	@echo "Agent Hub Development Commands:"
	@echo ""
	@echo "  make check           - Check if all required tools are installed"
	@echo "  make config          - Generate local config files from examples"
	@echo "  make install         - Install all dependencies (frontend + backend)"
	@echo "  make dev             - Start all services in development mode"
	@echo "  make dev-daemon      - Start all services in background (daemon mode)"
	@echo "  make stop            - Stop all running services"
	@echo "  make clean           - Clean up processes and temporary files"
	@echo "  make test            - Run all tests"
	@echo "  make lint            - Lint all code"
	@echo ""
	@echo "Docker Commands:"
	@echo "  make docker-build    - Build Docker images"
	@echo "  make docker-start    - Start Docker services"
	@echo "  make docker-stop     - Stop Docker services"
	@echo "  make docker-logs     - View Docker logs"

# ── Check Dependencies ──────────────────────────────────────────────────────

check:
	@$(PYTHON) ./scripts/check.py

# ── Generate Config ──────────────────────────────────────────────────────────

config:
	@$(PYTHON) ./scripts/configure.py

# ── Install ──────────────────────────────────────────────────────────────────

install:
	@echo "Installing backend dependencies..."
	@cd backend && pip install -r requirements.txt
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

lint:
	@cd backend && $(PYTHON) -m ruff check . 2>/dev/null || echo "ruff not installed, skipping backend lint"
	@cd frontend && pnpm lint 2>/dev/null || echo "frontend lint skipped"

# ── Docker ───────────────────────────────────────────────────────────────────

docker-build:
	@docker compose -f docker/docker-compose.yml build

docker-start:
	@docker compose -f docker/docker-compose.yml up -d

docker-stop:
	@docker compose -f docker/docker-compose.yml down

docker-logs:
	@docker compose -f docker/docker-compose.yml logs -f
