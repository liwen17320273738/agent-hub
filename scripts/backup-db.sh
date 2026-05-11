#!/bin/bash
# Agent Hub Database Backup Script
#
# Production-ready PostgreSQL backup with tiered retention and optional S3 upload.
#
# Usage:
#   ./scripts/backup-db.sh                  # use defaults
#   BACKUP_DIR=/tmp/bk ./scripts/backup-db.sh  # override backup dir
#
# Cron example (daily at 02:00):
#   0 2 * * * cd /path/to/agent-hub && ./scripts/backup-db.sh >> logs/backup.log 2>&1
#
# Environment variables (or .env file):
#   POSTGRES_USER       - DB user           (default: agenthub)
#   POSTGRES_PASSWORD   - DB password       (default: agenthub)
#   POSTGRES_HOST       - DB host           (default: localhost)
#   POSTGRES_PORT       - DB port           (default: 5432)
#   POSTGRES_DB         - DB name           (default: agenthub)
#   BACKUP_DIR          - local backup dir   (default: ./data/backups)
#   BACKUP_S3_BUCKET    - S3 bucket (optional, enables S3 upload)
#   DOCKER_PG_CONTAINER - Docker container name (optional, use docker exec)

set -euo pipefail

# ── Resolve project root ────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Load .env if present ────────────────────────────────────────────────────
ENV_FILE="$PROJECT_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
  set -a; source "$ENV_FILE"; set +a
fi

# ── Configuration ───────────────────────────────────────────────────────────
POSTGRES_USER="${POSTGRES_USER:-agenthub}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-agenthub}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-agenthub}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/data/backups}"
BACKUP_S3_BUCKET="${BACKUP_S3_BUCKET:-}"
DOCKER_PG_CONTAINER="${DOCKER_PG_CONTAINER:-}"

# Retention policy
RETAIN_DAILY=7
RETAIN_WEEKLY=4
RETAIN_MONTHLY=3

# ── Logging ─────────────────────────────────────────────────────────────────
LOG_FILE="$BACKUP_DIR/backup.log"
mkdir -p "$BACKUP_DIR"

log() {
  local level="$1"; shift
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*"
  echo "$msg"
  echo "$msg" >> "$LOG_FILE"
}

info()  { log "INFO"  "$@"; }
warn()  { log "WARN"  "$@"; }
error() { log "ERROR" "$@"; }

# ── Error handler ───────────────────────────────────────────────────────────
cleanup() {
  local exit_code=$?
  if [ $exit_code -ne 0 ]; then
    error "Backup failed with exit code $exit_code"
  fi
}
trap cleanup EXIT

# ── Detect Docker vs local PostgreSQL ──────────────────────────────────────
# Auto-detect: if host is not localhost/127.0.0.1, always use local pg_dump.
# If host IS localhost and a Docker container is specified (or auto-detected),
# use docker exec instead.

USE_DOCKER=false
if [ -n "$DOCKER_PG_CONTAINER" ]; then
  USE_DOCKER=true
elif [ "$POSTGRES_HOST" = "localhost" ] || [ "$POSTGRES_HOST" = "127.0.0.1" ]; then
  # Auto-detect: check if a postgres container is running
  DOCKER_PG_CONTAINER=$(docker ps --format '{{.Names}}' --filter 'ancestor=postgres' 2>/dev/null | head -1 || true)
  if [ -n "$DOCKER_PG_CONTAINER" ]; then
    # Verify pg_dump exists inside the container
    if docker exec "$DOCKER_PG_CONTAINER" which pg_dump >/dev/null 2>&1; then
      USE_DOCKER=true
      info "Auto-detected Docker PostgreSQL container: $DOCKER_PG_CONTAINER"
    fi
  fi
fi

# ── Pre-flight checks ──────────────────────────────────────────────────────
if [ "$USE_DOCKER" = false ]; then
  if ! command -v pg_dump >/dev/null 2>&1; then
    error "pg_dump not found. Install PostgreSQL client tools or set DOCKER_PG_CONTAINER."
    exit 1
  fi
fi

if [ -n "$BACKUP_S3_BUCKET" ] && ! command -v aws >/dev/null 2>&1; then
  warn "AWS CLI not found. S3 upload will be skipped."
  BACKUP_S3_BUCKET=""
fi

# ── Create backup ──────────────────────────────────────────────────────────
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
FILENAME="agenthub_backup_${TIMESTAMP}.dump"
BACKUP_PATH="$BACKUP_DIR/$FILENAME"

info "Starting backup: $FILENAME"

PG_DUMP_ARGS=(-Fc --no-owner --no-acl)

if [ "$USE_DOCKER" = true ]; then
  info "Using Docker container: $DOCKER_PG_CONTAINER"
  if ! docker exec "$DOCKER_PG_CONTAINER" \
    pg_dump "${PG_DUMP_ARGS[@]}" \
      -U "$POSTGRES_USER" \
      -d "$POSTGRES_DB" \
      > "$BACKUP_PATH" 2>> "$LOG_FILE"; then
    error "pg_dump via Docker failed"
    rm -f "$BACKUP_PATH"
    exit 1
  fi
else
  info "Using local pg_dump (host=$POSTGRES_HOST port=$POSTGRES_PORT)"
  export PGPASSWORD="$POSTGRES_PASSWORD"
  if ! pg_dump "${PG_DUMP_ARGS[@]}" \
    -h "$POSTGRES_HOST" \
    -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    > "$BACKUP_PATH" 2>> "$LOG_FILE"; then
    error "pg_dump failed"
    rm -f "$BACKUP_PATH"
    unset PGPASSWORD
    exit 1
  fi
  unset PGPASSWORD
fi

BACKUP_SIZE=$(du -h "$BACKUP_PATH" | cut -f1)
info "Backup created: $BACKUP_PATH ($BACKUP_SIZE)"

# ── Verify backup integrity ────────────────────────────────────────────────
if [ "$USE_DOCKER" = true ]; then
  if ! docker exec "$DOCKER_PG_CONTAINER" \
    pg_restore --list "$FILENAME" >/dev/null 2>&1; then
    # pg_restore --list inside docker may not find the file; verify locally instead
    if command -v pg_restore >/dev/null 2>&1; then
      if ! pg_restore --list "$BACKUP_PATH" >/dev/null 2>&1; then
        error "Backup verification failed: pg_restore --list returned error"
        rm -f "$BACKUP_PATH"
        exit 1
      fi
    else
      warn "pg_restore not available locally, skipping integrity check"
    fi
  fi
else
  if command -v pg_restore >/dev/null 2>&1; then
    if ! pg_restore --list "$BACKUP_PATH" >/dev/null 2>&1; then
      error "Backup verification failed: pg_restore --list returned error"
      rm -f "$BACKUP_PATH"
      exit 1
    fi
    info "Backup integrity verified"
  else
    warn "pg_restore not available, skipping integrity check"
  fi
fi

# ── Optional S3 upload ─────────────────────────────────────────────────────
if [ -n "$BACKUP_S3_BUCKET" ]; then
  S3_PATH="s3://${BACKUP_S3_BUCKET}/agenthub/backups/$FILENAME"
  info "Uploading to S3: $S3_PATH"
  if aws s3 cp "$BACKUP_PATH" "$S3_PATH" >> "$LOG_FILE" 2>&1; then
    info "S3 upload complete"
  else
    error "S3 upload failed"
  fi
fi

# ── Tiered retention cleanup ───────────────────────────────────────────────
# Strategy: keep 7 daily, 4 weekly (Sunday), 3 monthly (1st of month) backups.
# We tag backups by their timestamp and prune those that don't match any tier.

info "Applying retention policy (daily=$RETAIN_DAILY weekly=$RETAIN_WEEKLY monthly=$RETAIN_MONTHLY)"

# Get all backup files sorted newest-first
mapfile -t ALL_BACKUPS < <(ls -1t "$BACKUP_DIR"/agenthub_backup_*.dump 2>/dev/null || true)

if [ ${#ALL_BACKUPS[@]} -eq 0 ]; then
  info "No backups to evaluate for retention"
else
  KEEP_FILES=()

  # Parse each file's date from filename: agenthub_backup_YYYYMMDD_HHMMSS.dump
  DAILY_COUNT=0
  WEEKLY_COUNT=0
  MONTHLY_COUNT=0

  for f in "${ALL_BACKUPS[@]}"; do
    basename_f="$(basename "$f")"
    # Extract date portion: YYYYMMDD
    DATE_PART=$(echo "$basename_f" | sed -n 's/agenthub_backup_\([0-9]\{8\}\)_.*/\1/p')

    if [ -z "$DATE_PART" ] || [ ${#DATE_PART} -ne 8 ]; then
      # Can't parse date — keep it to be safe
      KEEP_FILES+=("$f")
      continue
    fi

    DAY_OF_MONTH="${DATE_PART:6:2}"
    # Get day of week (1=Mon..7=Sun) — use date command
    DOW=""
    DOW=$(date -j -f '%Y%m%d' "$DATE_PART" '+%u' 2>/dev/null || echo "")
    DOM="${DAY_PART#0}"  # day of month, strip leading zero
    DOM="${DAY_OF_MONTH#0}"

    kept=false

    # Monthly tier: 1st of month
    if [ "$DOM" = "1" ] && [ $MONTHLY_COUNT -lt $RETAIN_MONTHLY ]; then
      MONTHLY_COUNT=$((MONTHLY_COUNT + 1))
      kept=true
    fi

    # Weekly tier: Sunday (DOW=7)
    if [ "$DOW" = "7" ] && [ $WEEKLY_COUNT -lt $RETAIN_WEEKLY ]; then
      WEEKLY_COUNT=$((WEEKLY_COUNT + 1))
      kept=true
    fi

    # Daily tier: everything else (most recent N)
    if [ $DAILY_COUNT -lt $RETAIN_DAILY ]; then
      DAILY_COUNT=$((DAILY_COUNT + 1))
      kept=true
    fi

    if [ "$kept" = true ]; then
      KEEP_FILES+=("$f")
    fi
  done

  # Delete files not in KEEP_FILES
  DELETED=0
  for f in "${ALL_BACKUPS[@]}"; do
    skip=false
    for k in "${KEEP_FILES[@]}"; do
      if [ "$f" = "$k" ]; then
        skip=true
        break
      fi
    done
    if [ "$skip" = false ]; then
      rm -f "$f"
      DELETED=$((DELETED + 1))
      info "Deleted old backup: $(basename "$f")"
    fi
  done

  info "Retention: kept ${#KEEP_FILES[@]}, deleted $DELETED"
fi

# ── Done ────────────────────────────────────────────────────────────────────
info "Backup complete — $FILENAME ($BACKUP_SIZE)"
