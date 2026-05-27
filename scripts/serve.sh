#!/usr/bin/env bash
#
# serve.sh — Start Agent Hub services (dev or prod mode)
#
# Usage: ./scripts/serve.sh --dev | --prod

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MODE="${1:---dev}"

echo ""
echo "=========================================="
echo "  Starting Agent Hub ($MODE)"
echo "=========================================="
echo ""

mkdir -p logs

# Load env: backend/.env first (defaults / placeholders), then repo-root .env.
# Root must load last so real secrets (e.g. JWT_SECRET) are not overwritten by
# empty keys from backend/.env copied from .env.example.
set -a
[ -f "$REPO_ROOT/backend/.env" ] && . "$REPO_ROOT/backend/.env"
[ -f "$REPO_ROOT/.env" ] && . "$REPO_ROOT/.env"
set +a

# ── Port cleanup ────────────────────────────────────────────────────────────────
# Kill any stale process on target ports so we don't get false-positive health
# checks from a previous session while the new process silently dies on bind.

free_port() {
    local port="$1"
    local pids
    pids=$(lsof -ti ":$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "  ⚠ Port $port is in use (PIDs: $(echo "$pids" | tr '\n' ' '))—stopping stale process..."
        kill $pids 2>/dev/null || true
        sleep 1
        # Force kill if still alive
        lsof -ti ":$port" 2>/dev/null | xargs kill -9 2>/dev/null || true
    fi
}

free_port 8000
free_port 5200

cleanup() {
    echo ""
    echo "Shutting down services..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    echo "✓ All services stopped"
}
trap cleanup INT TERM

# ── Backend ──────────────────────────────────────────────────────────────────

# Use backend/.venv Python if available; fall back to system python3.
PYTHON_BIN="${REPO_ROOT}/backend/.venv/bin/python3"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

echo "Starting Backend API..."
if [ "$MODE" = "--prod" ]; then
    cd backend && "$PYTHON_BIN" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 > "$REPO_ROOT/logs/backend.log" 2>&1 &
elif [ "${BACKEND_NO_RELOAD:-0}" = "1" ]; then
    echo "  ⚠ BACKEND_NO_RELOAD=1 — auto-reload disabled (pipeline-safe)"
    cd backend && "$PYTHON_BIN" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > "$REPO_ROOT/logs/backend.log" 2>&1 &
else
    cd backend && "$PYTHON_BIN" -m uvicorn app.main:app \
        --host 0.0.0.0 --port 8000 \
        --reload \
        --reload-dir app \
        --reload-exclude '*.pyc' \
        --reload-exclude '__pycache__/*' \
        --reload-exclude '.pytest_cache/*' \
        --reload-exclude 'tests/*' \
        > "$REPO_ROOT/logs/backend.log" 2>&1 &
fi
BACKEND_PID=$!
cd "$REPO_ROOT"

# Wait for backend (verify the PID we started is still alive, not a stale process)
for i in $(seq 1 30); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "✗ Backend process died. Check logs/backend.log"
        tail -20 logs/backend.log
        exit 1
    fi
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "✓ Backend started on http://localhost:8000"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "✗ Backend failed to start. Check logs/backend.log"
        tail -20 logs/backend.log
        exit 1
    fi
    sleep 1
done

# ── Frontend ─────────────────────────────────────────────────────────────────

echo "Starting Frontend..."
if [ "$MODE" = "--prod" ]; then
    pnpm build > /dev/null 2>&1
    pnpm preview > "$REPO_ROOT/logs/frontend.log" 2>&1 &
else
    pnpm dev > "$REPO_ROOT/logs/frontend.log" 2>&1 &
fi
FRONTEND_PID=$!

for i in $(seq 1 60); do
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo "✗ Frontend process died. Check logs/frontend.log"
        tail -20 logs/frontend.log
        exit 1
    fi
    if curl -s http://localhost:5200 > /dev/null 2>&1; then
        echo "✓ Frontend started on http://localhost:5200"
        break
    fi
    if [ $i -eq 60 ]; then
        echo "✗ Frontend failed to start. Check logs/frontend.log"
        tail -20 logs/frontend.log
        exit 1
    fi
    sleep 1
done

# ── Ready ────────────────────────────────────────────────────────────────────

echo ""
echo "=========================================="
echo "  Agent Hub is running!"
echo "=========================================="
echo ""
echo "  🌐 Application: http://localhost:5200"
echo "  📡 API:         http://localhost:8000"
echo "  📋 API Docs:    http://localhost:8000/docs"
echo ""
echo "  Press Ctrl+C to stop all services"
echo ""

wait $BACKEND_PID $FRONTEND_PID
