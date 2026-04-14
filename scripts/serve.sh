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

cleanup() {
    echo ""
    echo "Shutting down services..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    echo "✓ All services stopped"
}
trap cleanup INT TERM

# ── Backend ──────────────────────────────────────────────────────────────────

echo "Starting Backend API..."
if [ "$MODE" = "--prod" ]; then
    cd backend && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 > "$REPO_ROOT/logs/backend.log" 2>&1 &
else
    cd backend && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload > "$REPO_ROOT/logs/backend.log" 2>&1 &
fi
BACKEND_PID=$!
cd "$REPO_ROOT"

# Wait for backend
for i in $(seq 1 30); do
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
