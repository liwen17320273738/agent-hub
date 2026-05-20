#!/bin/sh
# Firecrawl startup script — starts all services without the harness port-check.

echo "==> Starting Firecrawl API..."
node dist/src/index.js &
API_PID=$!

echo "==> Starting queue worker..."
node dist/src/services/queue-worker.js &
WORKER_PID=$!

echo "==> Starting extract worker..."
node dist/src/services/extract-worker.js &
EXTRACT_PID=$!

echo "==> Starting NUQ workers..."
N=0
while [ $N -lt ${NUQ_WORKER_COUNT:-5} ]; do
  NUQ_WORKER_PORT=$(( ${NUQ_WORKER_START_PORT:-3050} + N ))
  NUQ_POD_NAME="nuq-worker-${N}" NUQ_WORKER_PORT=${NUQ_WORKER_PORT} node dist/src/services/worker/nuq-worker.js &
  N=$((N + 1))
done

echo "==> Starting NUQ prefetch worker..."
node dist/src/services/worker/nuq-prefetch-worker.js &

echo "==> Starting NUQ reconciler..."
node dist/src/services/worker/nuq-reconciler-worker.js &

echo "==> All services started. Waiting..."

# Wait for any process to exit
wait -n 2>/dev/null || wait
echo "==> A service exited. Shutting down."
