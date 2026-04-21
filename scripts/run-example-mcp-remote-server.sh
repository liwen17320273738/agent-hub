#!/usr/bin/env bash
# 启动官方 MCP example-remote-server（默认监听 http://127.0.0.1:3232/mcp）。
# 用法：在项目根目录执行 ./scripts/run-example-mcp-remote-server.sh
# 可通过环境变量 EXAMPLE_MCP_REMOTE_DIR 指定克隆目录（默认 ~/example-remote-server）。

set -euo pipefail

ROOT="${EXAMPLE_MCP_REMOTE_DIR:-$HOME/example-remote-server}"
REPO="https://github.com/modelcontextprotocol/example-remote-server.git"

if [[ ! -d "$ROOT/.git" ]]; then
  echo "Cloning $REPO -> $ROOT"
  git clone "$REPO" "$ROOT"
fi

cd "$ROOT"
echo "Installing dependencies..."
npm install
echo "Starting dev server (internal auth, port 3232). Ctrl+C to stop."
exec npm run dev:internal
