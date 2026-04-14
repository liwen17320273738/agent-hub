#!/usr/bin/env bash
#
# start-daemon.sh — Start Agent Hub in background (daemon mode)

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo ""
echo "=========================================="
echo "  Starting Agent Hub in Daemon Mode"
echo "=========================================="
echo ""

# Stop existing services
echo "Stopping existing services..."
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
sleep 1

mkdir -p logs

# Backend
echo "Starting Backend API..."
nohup sh -c "cd $REPO_ROOT/backend && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload" > "$REPO_ROOT/logs/backend.log" 2>&1 &

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

# Frontend
echo "Starting Frontend..."
nohup sh -c "cd $REPO_ROOT && pnpm dev" > "$REPO_ROOT/logs/frontend.log" 2>&1 &

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

echo ""
echo "=========================================="
echo "  Agent Hub is running in daemon mode!"
echo "=========================================="
echo ""
echo "  🌐 Application: http://localhost:5200"
echo "  📡 API:         http://localhost:8000"
echo ""
echo "  📋 Logs:"
echo "    - Backend:  logs/backend.log"
echo "    - Frontend: logs/frontend.log"
echo ""
echo "  🛑 Stop: make stop"
echo ""
