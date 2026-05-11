#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SSL_DIR="$PROJECT_DIR/data/ssl"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS] [DOMAIN]

Set up SSL certificates for Agent Hub Nginx.

Options:
  --docker    Use certbot Docker image instead of local certbot
  --self-signed
              Generate a self-signed certificate (for development)
  -h, --help  Show this help message

If DOMAIN is provided, certbot (Let's Encrypt) is used to obtain a real certificate.
If no DOMAIN and no --self-signed flag, a self-signed cert is generated automatically.

Examples:
  $(basename "$0") example.com              # certbot standalone
  $(basename "$0") --docker example.com     # certbot via Docker
  $(basename "$0") --self-signed            # dev self-signed cert
EOF
}

USE_DOCKER=false
SELF_SIGNED=false
DOMAIN=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --docker)      USE_DOCKER=true; shift ;;
        --self-signed) SELF_SIGNED=true; shift ;;
        -h|--help)     usage; exit 0 ;;
        -*)            error "Unknown option: $1" ;;
        *)             DOMAIN="$1"; shift ;;
    esac
done

# Default to self-signed if no domain given
if [[ -z "$DOMAIN" && "$SELF_SIGNED" == "false" ]]; then
    warn "No domain provided, generating self-signed certificate for development."
    SELF_SIGNED=true
fi

# Create SSL directory
mkdir -p "$SSL_DIR"

# ── Self-signed certificate ──────────────────────────────────────────
if [[ "$SELF_SIGNED" == "true" ]]; then
    info "Generating self-signed certificate for development..."
    openssl req -x509 -nodes \
        -newkey rsa:2048 \
        -keyout "$SSL_DIR/privkey.pem" \
        -out "$SSL_DIR/fullchain.pem" \
        -days 365 \
        -subj "/C=US/ST=Dev/L=Dev/O=AgentHub/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

    info "Self-signed certificate created:"
    info "  Certificate: $SSL_DIR/fullchain.pem"
    info "  Private key:  $SSL_DIR/privkey.pem"
    warn "Self-signed certificates will trigger browser warnings. Use a real domain for production."
    exit 0
fi

# ── Let's Encrypt via certbot ────────────────────────────────────────
info "Obtaining Let's Encrypt certificate for domain: $DOMAIN"

if [[ "$USE_DOCKER" == "true" ]]; then
    # Docker mode
    if ! command -v docker &>/dev/null; then
        error "Docker is required for --docker mode but not found."
    fi

    info "Using certbot Docker image..."
    docker run --rm \
        -v "$SSL_DIR:/etc/letsencrypt" \
        -v "$PROJECT_DIR/data/certbot-var:/var/lib/letsencrypt" \
        -v "$PROJECT_DIR/data/certbot-log:/var/log/letsencrypt" \
        -p 80:80 \
        certbot/certbot certonly \
            --standalone \
            --agree-tos \
            --no-eff-email \
            -d "$DOMAIN" \
            --email "admin@$DOMAIN"

    # Copy from letsencrypt structure to expected paths
    cp "$SSL_DIR/live/$DOMAIN/fullchain.pem" "$SSL_DIR/fullchain.pem"
    cp "$SSL_DIR/live/$DOMAIN/privkey.pem" "$SSL_DIR/privkey.pem"
else
    # Standalone mode
    if ! command -v certbot &>/dev/null; then
        error "certbot not found. Install it or use --docker mode.
  Ubuntu/Debian: sudo apt install certbot
  macOS: brew install certbot
  Or run with --docker flag."
    fi

    info "Using local certbot..."
    sudo certbot certonly \
        --standalone \
        --agree-tos \
        --no-eff-email \
        -d "$DOMAIN" \
        --email "admin@$DOMAIN" \
        --config-dir "$SSL_DIR" \
        --work-dir "$PROJECT_DIR/data/certbot-work" \
        --logs-dir "$PROJECT_DIR/data/certbot-log"

    cp "$SSL_DIR/live/$DOMAIN/fullchain.pem" "$SSL_DIR/fullchain.pem"
    cp "$SSL_DIR/live/$DOMAIN/privkey.pem" "$SSL_DIR/privkey.pem"
fi

info "Let's Encrypt certificate created:"
info "  Certificate: $SSL_DIR/fullchain.pem"
info "  Private key:  $SSL_DIR/privkey.pem"

# ── Cron renewal ──────────────────────────────────────────────────────
info "Setting up automatic renewal cron job..."

CRON_CMD="certbot renew --quiet --deploy-hook \"cp $SSL_DIR/live/$DOMAIN/fullchain.pem $SSL_DIR/fullchain.pem && cp $SSL_DIR/live/$DOMAIN/privkey.pem $SSL_DIR/privkey.pem && docker compose -f $PROJECT_DIR/docker-compose.yml restart nginx\""

if [[ "$USE_DOCKER" == "true" ]]; then
    CRON_CMD="docker run --rm -v $SSL_DIR:/etc/letsencrypt -v $PROJECT_DIR/data/certbot-var:/var/lib/letsencrypt -v $PROJECT_DIR/data/certbot-log:/var/log/letsencrypt certbot/certbot renew --quiet --deploy-hook \"cp /etc/letsencrypt/live/$DOMAIN/fullchain.pem /etc/letsencrypt/fullchain.pem && cp /etc/letsencrypt/live/$DOMAIN/privkey.pem /etc/letsencrypt/privkey.pem\""
fi

# Add cron entry if not already present
CRON_LINE="0 0,12 * * * $CRON_CMD"
(crontab -l 2>/dev/null | grep -v "certbot renew.*$DOMAIN"; echo "$CRON_LINE") | crontab -

info "Cron renewal job added (runs at 00:00 and 12:00 daily)."
info "SSL setup complete for $DOMAIN"
