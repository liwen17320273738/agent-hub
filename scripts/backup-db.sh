#!/bin/bash
# Agent Hub Database Backup Script
# Usage: ./scripts/backup-db.sh [backup_dir]
# Default: ./data/backups/

set -euo pipefail

BACKUP_DIR="${1:-$(dirname "$0")/../data/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

# Load .env if present
ENV_FILE="$(dirname "$0")/../.env"
if [ -f "$ENV_FILE" ]; then
  set -a; source "$ENV_FILE"; set +a
fi

mkdir -p "$BACKUP_DIR"

# ── PostgreSQL backup ──────────────────────────────────────────
PG_HOST="${PG_HOST:-localhost}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${POSTGRES_USER:-agenthub}"
PG_DB="${POSTGRES_DB:-agenthub}"
PG_PASSWORD="${POSTGRES_PASSWORD:-}"

PG_BACKUP="$BACKUP_DIR/agenthub_pg_${TIMESTAMP}.sql.gz"

echo "[backup] PostgreSQL → $PG_BACKUP"
if [ -n "$PG_PASSWORD" ]; then
  PGPASSWORD="$PG_PASSWORD" pg_dump -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
    --no-owner --no-acl | gzip > "$PG_BACKUP"
else
  pg_dump -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
    --no-owner --no-acl | gzip > "$PG_BACKUP"
fi
echo "[backup] PostgreSQL done ($(du -h "$PG_BACKUP" | cut -f1))"

# ── Redis backup (trigger BGSAVE) ─────────────────────────────
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"

if [ -n "$REDIS_PASSWORD" ]; then
  redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" --no-auth-warning BGSAVE >/dev/null 2>&1 || true
else
  redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" BGSAVE >/dev/null 2>&1 || true
fi
echo "[backup] Redis BGSAVE triggered"

# ── Cleanup old backups ───────────────────────────────────────
deleted=$(find "$BACKUP_DIR" -name "agenthub_pg_*" -mtime +$RETENTION_DAYS -delete -print | wc -l)
echo "[backup] Cleaned up $deleted old backups (>{$RETENTION_DAYS}d)"

echo "[backup] ✅ Complete — $(date)"
