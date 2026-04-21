#!/usr/bin/env bash
# Convenience launcher for `python -m scripts.swebench`.
# Run from the repo root:
#
#   ./scripts/run-swebench.sh --source hf:princeton-nlp/SWE-bench_Lite --limit 5
#
# All flags are forwarded as-is. See `python -m scripts.swebench --help`.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}/backend"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not on PATH. Install from https://docs.astral.sh/uv/ or run pip install uv." >&2
  exit 127
fi

if [[ "${1:-}" != *"--dry-run"* ]] && [[ -z "${OPENAI_API_KEY:-}${ANTHROPIC_API_KEY:-}${DEEPSEEK_API_KEY:-}${DASHSCOPE_API_KEY:-}" ]]; then
  echo "Warning: no LLM provider API key in env (OPENAI_API_KEY / ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / DASHSCOPE_API_KEY)." >&2
  echo "Continuing — chat_completion will return an error per instance, useful for shape testing only." >&2
fi

PYTHONPATH=. exec uv run \
  --with 'datasets>=2.18.0' \
  --with 'pyarrow>=15.0.0' \
  python -m scripts.swebench "$@"
