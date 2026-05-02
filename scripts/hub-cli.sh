#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# hub-cli.sh — Agent Hub CLI ↔ IDE sync tool
#
# Bridges the gap between local AI coding agents (Claude Code, Codex, etc.)
# and Agent Hub tasks. Engineers work in their IDE; results sync back.
#
# Depends on:
#   - curl, jq (optional but recommended)
#   - HUB_API_KEY or HUB_API_TOKEN env var
#
# Usage:
#   export HUB_URL="http://localhost:8000"
#   export HUB_API_KEY="your-api-key"
#
#   hub context <task-id>          # Download task context bundle
#   hub status <task-id>           # Show task status
#   hub sync <task-id> <file>      # Upload a file/artifact to task
#   hub list                       # List recent tasks
# ──────────────────────────────────────────────────────────────────────────

set -euo pipefail

HUB_URL="${HUB_URL:-http://localhost:8000}"
HUB_API_KEY="${HUB_API_KEY:-${HUB_API_TOKEN:-}}"

_error() { echo "[❌] $*" >&2; exit 1; }
_info() { echo "[ℹ️] $*" >&2; }

# ── Auth header ──────────────────────────────────────────────────────────
_auth_header() {
  if [[ -n "$HUB_API_KEY" ]]; then
    echo "Authorization: Bearer $HUB_API_KEY"
  fi
}

# ── Commands ─────────────────────────────────────────────────────────────

cmd_context() {
  local task_id="${1:-}"
  [[ -z "$task_id" ]] && _error "Usage: hub context <task-id>"

  local out_dir="${2:-".agent-hub/$task_id"}"
  mkdir -p "$out_dir"

  _info "Fetching task $task_id context..."

  # 1. Get task details
  local task_json
  task_json=$(curl -s -H "$(_auth_header)" "$HUB_URL/api/pipeline/tasks/$task_id" 2>/dev/null || echo "")
  if [[ -z "$task_json" || "$task_json" == *"detail"* ]]; then
    _error "Task not found or API unreachable."
  fi

  local title
  title=$(echo "$task_json" | grep -o '"title":"[^"]*"' | head -1 | sed 's/"title":"//;s/"//')
  local description
  description=$(echo "$task_json" | grep -o '"description":"[^"]*"' | head -1 | sed 's/"description":"//;s/"//')

  # 2. Generate CLAUDE.md
  cat > "$out_dir/CLAUDE.md" << CLAUDE_EOF
# Agent Hub Task Context: $title

## Task
- **ID:** $task_id
- **Title:** $title

## Description
$(echo "$description" | sed 's/\\n/\n/g')

## Working Context
You are working on this task as part of Agent Hub's AI delivery pipeline.
Focus on completing the current stage requirements.
When done, sync results back: \`hub sync $task_id <output-file>\`

## Rules
- Do NOT modify files outside the task worktree
- Commit changes with meaningful messages referencing the task ID
- Run tests before marking any stage as complete
CLAUDE_EOF

  _info "Written: $out_dir/CLAUDE.md"

  # 3. Try to download artifacts bundle
  local zip_url="$HUB_URL/api/pipeline/tasks/$task_id/deliverables"
  curl -sL -H "$(_auth_header)" "$zip_url" -o "$out_dir/artifacts.zip" 2>/dev/null && {
    _info "Downloaded: $out_dir/artifacts.zip ($(wc -c < "$out_dir/artifacts.zip" | tr -d ' ') bytes)"
  } || true

  echo
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo " Context bundle ready: $out_dir/"
  echo " Open $out_dir/CLAUDE.md to see task context"
  echo " Artifacts: $out_dir/artifacts.zip"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

cmd_status() {
  local task_id="${1:-}"
  [[ -z "$task_id" ]] && _error "Usage: hub status <task-id>"

  _info "Fetching status for task $task_id..."

  local task_json
  task_json=$(curl -s -H "$(_auth_header)" "$HUB_URL/api/pipeline/tasks/$task_id" 2>/dev/null || echo "")
  if [[ -z "$task_json" ]]; then
    _error "API unreachable at $HUB_URL"
  fi

  # Pretty print with jq if available
  if command -v jq &>/dev/null; then
    echo "$task_json" | jq '{
      id: .id,
      title: .title,
      status: .status,
      currentStage: .current_stage_id,
      template: .template,
      repoUrl: .repo_url,
      repoRefs: .repo_refs,
      stages: [.stages[] | {id: .stage_id, label: .label, status: .status, qualityScore: .quality_score}]
    }' 2>/dev/null || echo "$task_json"
  else
    echo "$task_json" | python3 -m json.tool 2>/dev/null || echo "$task_json"
  fi
}

cmd_sync() {
  local task_id="${1:-}"
  local file_path="${2:-}"
  [[ -z "$task_id" ]] && _error "Usage: hub sync <task-id> <file-path>"
  [[ -z "$file_path" ]] && _error "Usage: hub sync <task-id> <file-path>"
  [[ ! -f "$file_path" ]] && _error "File not found: $file_path"

  local filename
  filename=$(basename "$file_path")

  _info "Uploading $filename to task $task_id..."

  curl -s -X POST \
    -H "$(_auth_header)" \
    -F "file=@$file_path" \
    -F "artifact_type=attachment" \
    "$HUB_URL/api/pipeline/tasks/$task_id/artifacts" 2>/dev/null || {
    _error "Upload failed"
  }

  _info "Uploaded $filename to task $task_id"
}

cmd_list() {
  local limit="${1:-10}"

  _info "Fetching recent tasks (limit=$limit)..."

  local tasks_json
  tasks_json=$(curl -s -H "$(_auth_header)" "$HUB_URL/api/pipeline/tasks?limit=$limit" 2>/dev/null || echo "")
  if [[ -z "$tasks_json" ]]; then
    _error "API unreachable at $HUB_URL"
  fi

  if command -v jq &>/dev/null; then
    echo "$tasks_json" | jq -r '.tasks // . | .[] | "\(.id[0:8])  \(.status//"?")\t\(.title//"untitled")"' 2>/dev/null || echo "$tasks_json"
  else
    echo "$tasks_json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
tasks = data.get('tasks', data if isinstance(data, list) else [])
for t in tasks:
    tid = (t.get('id') or '')[:8]
    status = t.get('status', '?')
    title = t.get('title', 'untitled')
    print(f'{tid}  {status}\t{title}')
" 2>/dev/null || echo "$tasks_json"
  fi
}

# ── Main ─────────────────────────────────────────────────────────────────

main() {
  local cmd="${1:-}"
  shift || true

  case "$cmd" in
    context) cmd_context "$@" ;;
    status)  cmd_status "$@" ;;
    sync)    cmd_sync "$@" ;;
    list)    cmd_list "$@" ;;
    *)
      echo "Agent Hub CLI Sync Tool"
      echo ""
      echo "Usage:"
      echo "  hub context <task-id> [output-dir]   Download task context bundle"
      echo "  hub status <task-id>                 Show task status with stages"
      echo "  hub sync <task-id> <file>            Upload artifact to task"
      echo "  hub list [limit]                     List recent tasks"
      echo ""
      echo "Environment:"
      echo "  HUB_URL       Agent Hub server URL (default: http://localhost:8000)"
      echo "  HUB_API_KEY   API key for authentication"
      echo ""
      echo "Examples:"
      echo "  HUB_URL=http://localhost:8000 hub context abc123-..."
      echo "  hub status abc123-... | jq .stages"
      echo "  hub sync abc123-... ./output/spec.md"
      ;;
  esac
}

main "$@"
