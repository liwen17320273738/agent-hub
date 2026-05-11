# ── Stage 1: Builder ─────────────────────────────────────────────
# Install build dependencies, compile native extensions, then discard.
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js + Ruflo (needed at runtime for MCP Bridge)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g ruflo@latest \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy and install Python dependencies
COPY packages/agent-hub-pipeline /packages/agent-hub-pipeline
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --prefix=/install /packages/agent-hub-pipeline \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ─────────────────────────────────────────────
# Slim image with only runtime dependencies.
FROM python:3.12-slim

RUN groupadd -r appuser && useradd -r -g appuser appuser

# Runtime-only system packages (no build-essential, no libpq-dev headers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Node.js + Ruflo from builder
COPY --from=builder /usr/local/bin/node /usr/local/bin/node
COPY --from=builder /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=builder /usr/local/bin/ruflo /usr/local/bin/ruflo
# Copy node shared libraries
COPY --from=builder /usr/local/include/node /usr/local/include/node

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy only runtime application code (no tests, no pytest.ini)
COPY backend/app/ ./app/
COPY backend/alembic/ ./alembic/
COPY backend/alembic.ini ./alembic.ini
COPY skills/ /app/skills/

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
