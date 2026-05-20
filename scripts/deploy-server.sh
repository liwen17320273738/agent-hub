#!/usr/bin/env bash
#
# deploy-server.sh — Agent Hub 上线部署脚本（适配已有 PostgreSQL 的服务器）
#
# 使用方式（在服务器上以非 root 用户执行）：
#   bash scripts/deploy-server.sh
#
# 前置条件：
#   1. 服务器上已有 PostgreSQL 16（含 agenthub 用户和数据库）
#   2. Docker 已安装（29.x+）
#   3. .env 文件已按 .env.production.example 配置
#
# 本脚本会自动：
#   1. 安装 Docker Compose 插件
#   2. 清理测试数据
#   3. 构建 Docker 镜像
#   4. 启动所有服务

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── Colors ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERR]${NC}   $*"; }

# ── Prerequisites Checks ──────────────────────────────────────────────────

info "步骤 1/5: 检查环境..."

# Docker
if ! command -v docker &>/dev/null; then
    err "Docker 未安装！请先安装 Docker。"
    exit 1
fi
ok "Docker $(docker --version)"

# Docker Compose plugin
if ! docker compose version &>/dev/null; then
    warn "Docker Compose 插件未安装，正在安装..."
    apt-get update -qq && apt-get install -y -qq docker-compose-plugin
    ok "Docker Compose 插件安装完成"
else
    ok "Docker Compose $(docker compose version)"
fi

# PostgreSQL connectivity
if ! sudo -u postgres psql -d agenthub -c "SELECT 1" &>/dev/null; then
    warn "PostgreSQL 连接检查失败，请确认 agenthub 数据库已创建："
    warn "  sudo -u postgres createdb agenthub"
    warn "  sudo -u postgres psql -c \"CREATE USER agenthub WITH PASSWORD '你的密码';\""
    warn "  sudo -u postgres psql -c \"GRANT ALL PRIVILEGES ON DATABASE agenthub TO agenthub;\""
    exit 1
fi
ok "PostgreSQL 连接正常"

# docker0 bridge IP
DOCKER_BRIDGE_IP=$(ip addr show docker0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d/ -f1)
if [[ -z "$DOCKER_BRIDGE_IP" ]]; then
    err "Docker 网桥 docker0 未找到。请先启动一个容器以创建网桥。"
    exit 1
fi
ok "Docker 网桥 IP: $DOCKER_BRIDGE_IP"

# .env file
if [[ ! -f ".env" ]]; then
    err ".env 文件不存在！请先按照 .env.production.example 配置。"
    err "参考下方说明创建 .env 文件。"
    exit 1
fi
ok ".env 文件存在"

# ── Clean test data ────────────────────────────────────────────────────────

echo ""
info "步骤 2/5: 清理测试数据..."

if [[ -f "scripts/cleanup-test-data.sql" ]]; then
    sudo -u postgres psql -d agenthub -f scripts/cleanup-test-data.sql || {
        warn "清理脚本执行时有警告（可能是空表），继续部署..."
    }
    ok "测试数据清理完成"
else
    warn "cleanup-test-data.sql 未找到，跳过清理"
fi

# ── Build Docker images ────────────────────────────────────────────────────

echo ""
info "步骤 3/5: 构建 Docker 镜像（首次约 5-15 分钟）..."

docker compose -f docker/docker-compose.server.yml build
ok "Docker 镜像构建完成"

# ── Start services ─────────────────────────────────────────────────────────

echo ""
info "步骤 4/5: 启动服务..."

docker compose -f docker/docker-compose.server.yml up -d
ok "所有容器已启动"

# ── Wait for health ────────────────────────────────────────────────────────

echo ""
info "步骤 5/5: 等待服务就绪..."

declare -A SERVICES=(
    ["agent-hub-redis"]="redis"
    ["agent-hub-backend"]="backend"
    ["agent-hub-frontend"]="frontend"
    ["agent-hub-nginx"]="nginx"
)

for container in "${!SERVICES[@]}"; do
    local timeout=120
    local waited=0
    while [[ $waited -lt $timeout ]]; do
        local status
        status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "starting")
        if [[ "$status" == "healthy" ]]; then
            ok "${SERVICES[$container]} ($container) 健康"
            break
        fi
        sleep 3
        waited=$((waited + 3))
    done
    if [[ $waited -ge $timeout ]]; then
        warn "${SERVICES[$container]} ($container) 未在 ${timeout}s 内就绪，请检查日志：docker logs $container"
    fi
done

# ── Final ──────────────────────────────────────────────────────────────────

echo ""
echo "============================================"
echo "   Agent Hub 部署完成！"
echo "============================================"
echo ""
echo "   访问地址: http://47.95.254.24:80"
echo "   管理员登录: ADMIN_EMAIL / ADMIN_PASSWORD"
echo ""
echo "   常用命令："
echo "     docker compose -f docker/docker-compose.server.yml logs -f    # 查看日志"
echo "     docker compose -f docker/docker-compose.server.yml down       # 停止"
echo "     docker compose -f docker/docker-compose.server.yml up -d      # 启动"
echo "     docker compose -f docker/docker-compose.server.yml build      # 重新构建"
echo ""

ok "部署完成！"
