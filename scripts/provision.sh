#!/usr/bin/env bash
#
# provision.sh — One-command Agent Hub production deployment
#
# What it does:
#   1. Checks OS/distro & installs Docker + Docker Compose if missing
#   2. Clones / pulls the latest agent-hub code
#   3. Interactive guided .env setup (or uses existing .env)
#   4. Optionally sets up Caddy reverse proxy with auto HTTPS
#   5. Builds and starts all containers
#   6. Waits for health checks and prints the final URL
#
# Usage:
#   bash <(curl -fsSL https://raw.githubusercontent.com/your-org/agent-hub/main/scripts/provision.sh)
#   # or locally:
#   ./scripts/provision.sh [--domain your-domain.com]
#
# Environment variables (non-interactive mode):
#   DOMAIN=your-domain.com           # domain for HTTPS
#   JWT_SECRET=xxx                   # if not set, prompts
#   ADMIN_EMAIL=admin@example.com
#   ADMIN_PASSWORD=xxx
#   DB_PASSWORD=xxx                  # if not set, auto-generates
#   REDIS_PASSWORD=xxx               # if not set, auto-generates
#   OPENAI_API_KEY=sk-xxx
#   DEEPSEEK_API_KEY=sk-xxx
#
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERR]${NC}   $*"; }

# ── Parse args ────────────────────────────────────────────────────────────────
DOMAIN="${DOMAIN:-}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain) DOMAIN="$2"; shift 2 ;;
        --help|-h) echo "Usage: $0 [--domain your-domain.com]"; exit 0 ;;
        *) err "Unknown option: $1"; exit 1 ;;
    esac
done

# ── Prerequisites: Docker ─────────────────────────────────────────────────────
ensure_docker() {
    if command -v docker &>/dev/null; then
        ok "Docker already installed ($(docker --version))"
    else
        info "Installing Docker..."
        curl -fsSL https://get.docker.com | sh
        sudo usermod -aG docker "$USER"
        ok "Docker installed. You may need to re-login for group changes."
    fi

    if ! command -v docker compose &>/dev/null; then
        warn "docker compose not found, installing plugin..."
        sudo apt-get update && sudo apt-get install -y docker-compose-plugin
    fi
    ok "docker compose available"
}

# ── Clone / Pull code ────────────────────────────────────────────────────────
ensure_code() {
    local target="/opt/agent-hub"
    if [[ -d "$target/.git" ]]; then
        info "Updating existing deployment at $target..."
        cd "$target" && git pull --ff-only
    else
        info "Cloning agent-hub to $target..."
        sudo mkdir -p "$target"
        sudo chown "$USER:$USER" "$target"
        git clone https://github.com/your-org/agent-hub.git "$target"
        cd "$target"
    fi
    ok "Code ready at $target"
    DEPLOY_DIR="$target"
}

# ── Generate secure passwords ────────────────────────────────────────────────
gen_password() {
    python3 -c "import secrets; print(secrets.token_urlsafe(32))"
}

# ── Interactive .env setup ────────────────────────────────────────────────────
setup_env() {
    local env_file="$DEPLOY_DIR/.env"

    if [[ -f "$env_file" ]]; then
        warn "Existing .env found at $env_file"
        read -rp "Overwrite? [y/N] " reply
        if [[ ! "$reply" =~ ^[Yy]$ ]]; then
            ok "Keeping existing .env"
            return
        fi
    fi

    echo ""
    echo "============================================"
    echo "   Agent Hub — Production Configuration"
    echo "============================================"
    echo ""
    echo "Fill in the values below. Press Enter to accept [defaults]."
    echo ""

    # ── Security ──
    local jwt_secret="${JWT_SECRET:-$(gen_password)}"
    read -rp "JWT_SECRET [auto-generated]: " input
    jwt_secret="${input:-$jwt_secret}"

    local admin_email="${ADMIN_EMAIL:-}"
    while [[ -z "$admin_email" ]]; do
        read -rp "ADMIN_EMAIL (required): " admin_email
    done

    local admin_password="${ADMIN_PASSWORD:-}"
    while [[ ${#admin_password} -lt 12 ]]; do
        read -rsp "ADMIN_PASSWORD (min 12 chars): " admin_password
        echo ""
        if [[ ${#admin_password} -lt 12 ]]; then
            err "Password must be at least 12 characters"
        fi
    done

    local db_password="${DB_PASSWORD:-$(gen_password)}"
    read -rp "POSTGRES_PASSWORD [auto-generated]: " input
    db_password="${input:-$db_password}"

    local redis_password="${REDIS_PASSWORD:-$(gen_password)}"
    read -rp "REDIS_PASSWORD [auto-generated]: " input
    redis_password="${input:-$redis_password}"

    # ── LLM Provider ──
    local openai_key="${OPENAI_API_KEY:-}"
    read -rp "OPENAI_API_KEY (leave empty to skip): " input
    openai_key="${input:-$openai_key}"

    local deepseek_key="${DEEPSEEK_API_KEY:-}"
    read -rp "DEEPSEEK_API_KEY (leave empty to skip): " input
    deepseek_key="${input:-$deepseek_key}"

    # ── Domain (Caddy auto HTTPS) ──
    if [[ -z "$DOMAIN" ]]; then
        read -rp "Domain name for HTTPS (e.g. hub.your.com, leave empty for HTTP-only): " input
        DOMAIN="${input:-}"
    fi

    # ── Write .env ──
    cat > "$env_file" << EOF
# Agent Hub — Production .env (generated by provision.sh)
JWT_SECRET=$jwt_secret
ADMIN_EMAIL=$admin_email
ADMIN_PASSWORD=$admin_password
POSTGRES_PASSWORD=$db_password
REDIS_PASSWORD=$redis_password
OPENAI_API_KEY=$openai_key
DEEPSEEK_API_KEY=$deepseek_key
LLM_API_URL=https://api.deepseek.com/v1/chat/completions
LLM_API_KEY=$deepseek_key
LLM_MODEL=deepseek-chat
RATE_LIMIT_PER_MINUTE=600
DEBUG=false
ARTIFACT_STORE_V2=true
ARTIFACT_CONTRACT_ENFORCE=true
ARTIFACT_CONTRACT_RULES_STRICT=false
BROWSER_ENABLED=true
CORS_ORIGINS='["http://localhost","https://$DOMAIN"]'
EOF

    # If domain is set, also set up Caddy
    if [[ -n "$DOMAIN" ]]; then
        cat >> "$env_file" << EOF
DOMAIN=$DOMAIN
CADDY_EMAIL=admin@$(echo "$DOMAIN" | sed 's/^[^.]*\.//')
EOF
    fi

    chmod 600 "$env_file"
    ok "Configuration written to $env_file"
}

# ── Setup Caddy reverse proxy (auto HTTPS) ──────────────────────────────────
setup_caddy() {
    if [[ -z "$DOMAIN" ]]; then
        warn "No domain set — skipping Caddy setup."
        warn "Services will be available at http://$(curl -s ifconfig.me):80"
        return
    fi

    local compose_dir="$DEPLOY_DIR/docker"
    local caddyfile="$compose_dir/Caddyfile"

    info "Setting up Caddy with auto HTTPS for $DOMAIN..."

    mkdir -p "$compose_dir/caddy_data"

    cat > "$caddyfile" << 'CADDY'
# Agent Hub — Caddy reverse proxy with auto HTTPS
{
    email {$CADDY_EMAIL}
    storage file:///data/caddy
}

{$DOMAIN} {
    reverse_proxy nginx:80 {
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }

    log {
        output file /data/caddy/access.log
    }

    # Security headers
    header {
        X-Frame-Options "DENY"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "strict-origin-when-cross-origin"
        Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=()"
    }
}

# Redirect HTTP → HTTPS (Caddy does this automatically, but explicit is safer)
http://{$DOMAIN} {
    redir https://{$DOMAIN}{uri}
}
CADDY

    ok "Caddyfile created at $caddyfile"
}

# ── Build & Start ─────────────────────────────────────────────────────────────
start_services() {
    cd "$DEPLOY_DIR"
    local compose_file="docker/docker-compose.yml"

    echo ""
    info "Building Docker images (this may take 5–15 minutes on first run)..."
    docker compose -f "$compose_file" build
    ok "Build complete"

    info "Starting all services..."
    docker compose -f "$compose_file" up -d
    ok "All containers started"

    # ── Wait for health checks ──
    echo ""
    info "Waiting for services to become healthy..."

    local services=("agent-hub-db" "agent-hub-redis" "agent-hub-backend" "agent-hub-frontend" "agent-hub-nginx")
    for svc in "${services[@]}"; do
        local timeout=120
        local waited=0
        while [[ $waited -lt $timeout ]]; do
            local status
            status=$(docker inspect --format='{{.State.Health.Status}}' "$svc" 2>/dev/null || echo "starting")
            if [[ "$status" == "healthy" ]]; then
                ok "$svc is healthy"
                break
            fi
            sleep 3
            waited=$((waited + 3))
        done
        if [[ $waited -ge $timeout ]]; then
            warn "$svc not healthy after ${timeout}s — check logs: docker logs $svc"
        fi
    done

    echo ""
    echo "============================================"
    echo "   Agent Hub is running!"
    echo "============================================"
    echo ""

    local public_ip
    public_ip=$(curl -s ifconfig.me 2>/dev/null || echo "your-server-ip")

    if [[ -n "$DOMAIN" ]]; then
        echo "   URL:     https://$DOMAIN"
    else
        echo "   URL:     http://$public_ip"
        warn "No HTTPS configured. To add later:"
        warn "  $0 --domain your-domain.com"
    fi

    echo ""
    echo "   Login:   $ADMIN_EMAIL"
    echo ""
    echo "   Commands:"
    echo "     docker compose -f docker/docker-compose.yml logs -f    # tail logs"
    echo "     docker compose -f docker/docker-compose.yml down       # stop"
    echo "     docker compose -f docker/docker-compose.yml up -d      # start"
    echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo "╔═══════════════════════════════════════════════╗"
    echo "║       Agent Hub — Production Deployer         ║"
    echo "╚═══════════════════════════════════════════════╝"
    echo ""

    # Check we're running as a normal user with sudo access
    if [[ $EUID -eq 0 ]]; then
        err "Do NOT run this script as root. It uses sudo where needed."
        exit 1
    fi

    ensure_docker
    ensure_code
    setup_env
    setup_caddy
    start_services

    echo ""
    ok "Provisioning complete!"
}

main "$@"
