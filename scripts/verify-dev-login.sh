#!/usr/bin/env bash
# POST /api/auth/login using the same env merge as scripts/serve.sh (backend/.env then repo-root .env).
# Use this to confirm credentials match the running API. OS environment variables still override
# both files when set (same as pydantic-settings).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a
[ -f "$REPO_ROOT/backend/.env" ] && . "$REPO_ROOT/backend/.env"
[ -f "$REPO_ROOT/.env" ] && . "$REPO_ROOT/.env"
set +a
exec python3 << 'PY'
import json
import os
import sys
import urllib.error
import urllib.request

email = (os.environ.get("ADMIN_EMAIL") or "").strip()
password = os.environ.get("ADMIN_PASSWORD") or ""
if not email or not password:
    print("FAIL: ADMIN_EMAIL / ADMIN_PASSWORD missing after sourcing .env files", file=sys.stderr)
    raise SystemExit(1)
print("effective ADMIN_PASSWORD length:", len(password), file=sys.stderr)
body = json.dumps({"email": email, "password": password}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/auth/login",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
except urllib.error.HTTPError as e:
    print("FAIL:", e.code, e.read().decode()[:300], file=sys.stderr)
    raise SystemExit(1)
except urllib.error.URLError as e:
    print("FAIL: could not reach http://127.0.0.1:8000 — is `make dev` running?", e, file=sys.stderr)
    raise SystemExit(1)
if "access_token" not in data:
    print("FAIL: response:", data, file=sys.stderr)
    raise SystemExit(1)
print("PASS: login OK (access_token length %d)" % len(data["access_token"]))
PY
