#!/usr/bin/env python3
"""Cross-platform dependency checker for Agent Hub."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


def repo_root_from_script() -> Path:
    """Directory containing Makefile + backend/."""

    return Path(__file__).resolve().parents[1]


def dotenv_overlay(target: dict[str, str], path: Path) -> None:
    if not path.is_file():
        return
    raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in raw:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].strip()
        if "=" not in s:
            continue
        key, val = s.split("=", 1)
        key = key.strip()
        val = val.strip().strip("\"'").split("#", 1)[0].strip()
        if key:
            target[key] = val


def merged_app_env(repo_root: Path) -> dict[str, str]:
    """Match scripts/serve.sh: backend/.env first, repo-root .env wins on duplicates."""

    out = dict(os.environ)
    dotenv_overlay(out, repo_root / "backend" / ".env")
    dotenv_overlay(out, repo_root / ".env")
    return out


# Alembic revision IDs here are lowercase alphanumerics (not strict hex-only).
_REVISION_RE = re.compile(r"\b[a-z0-9]{12}\b")


def _revision_tokens(line: str) -> list[str]:
    return [tok.lower() for tok in _REVISION_RE.findall(line)]


def alembic_head_revisions(stdout: str) -> set[str]:
    ids: set[str] = set()
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith("INFO "):
            continue
        if "(head)" not in line:
            continue
        for tok in _revision_tokens(line):
            ids.add(tok)
    return ids


def alembic_current_revision(stdout: str) -> Optional[str]:
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith("INFO ") or not line:
            continue
        toks = _revision_tokens(line)
        if toks:
            return toks[0]
    return None


def alembic_migration_status(py: str, repo_root: Path) -> tuple[str, str]:
    """

    Returns (status, hint) where status is one of skip, ok, unverified, drift.

    drift makes `make check` fail; unverified prints a warning only.

    """

    env = merged_app_env(repo_root)
    db_url = (env.get("DATABASE_URL") or "").strip()
    if not db_url:
        return "skip", ""

    backend_dir = repo_root / "backend"
    if not (backend_dir / "alembic.ini").is_file():
        return "skip", ""

    run_env = dict(env)
    run_env.setdefault("PYTHONPATH", str(backend_dir))

    heads = subprocess.run(
        [py, "-m", "alembic", "heads"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        env=run_env,
    )
    out_h = heads.stdout + "\n" + heads.stderr
    if heads.returncode != 0:
        hint = out_h.strip()[:400]
        return "unverified", hint

    cur = subprocess.run(
        [py, "-m", "alembic", "current"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        env=run_env,
    )
    out_c = cur.stdout + "\n" + cur.stderr
    if cur.returncode != 0:
        hint = out_c.strip()[:400]
        return "unverified", hint

    heads_ids = alembic_head_revisions(out_h)
    cur_id = alembic_current_revision(out_c)
    if cur_id is None or not heads_ids:
        return "unverified", "could not parse alembic output"

    if cur_id not in heads_ids:
        return (
            "drift",
            f"db at {cur_id}, head(s): {','.join(sorted(heads_ids))}",
        )

    return "ok", cur_id


def run_command(command: list[str]) -> Optional[str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or result.stderr.strip()


def parse_version(text: str) -> Optional[str]:
    text = text.strip()
    if text.startswith("v"):
        text = text[1:]
    return text.split()[0] if text else None


def main() -> int:
    print("==========================================")
    print("  Checking Required Dependencies")
    print("==========================================")
    print()

    failed = False

    py = shutil.which("python3") or shutil.which("python")

    # Node.js
    print("Checking Node.js...")
    if shutil.which("node"):
        ver = run_command(["node", "-v"])
        if ver:
            major = ver.lstrip("v").split(".")[0]
            if major.isdigit() and int(major) >= 18:
                print(f"  ✓ Node.js {ver.lstrip('v')} (>= 18 required)")
            else:
                print(f"  ✗ Node.js {ver} found, but 18+ required")
                failed = True
        else:
            print("  ✗ Unable to determine Node.js version")
            failed = True
    else:
        print("  ✗ Node.js not found")
        print("    Install from: https://nodejs.org/")
        failed = True

    # pnpm
    print("\nChecking pnpm...")
    if shutil.which("pnpm"):
        ver = run_command(["pnpm", "-v"])
        print(f"  ✓ pnpm {ver}" if ver else "  ✓ pnpm (version unknown)")
    else:
        print("  ✗ pnpm not found")
        print("    Install: npm install -g pnpm")
        failed = True

    # Python
    print("\nChecking Python...")
    if py:
        ver = run_command([py, "--version"])
        if ver:
            v = ver.split()[-1]
            parts = v.split(".")
            if len(parts) >= 2 and int(parts[0]) >= 3 and int(parts[1]) >= 9:
                print(f"  ✓ Python {v} (>= 3.9 required)")
            else:
                print(f"  ✗ Python {v} found, but 3.9+ required")
                failed = True
        else:
            print("  ✗ Unable to determine Python version")
            failed = True
    else:
        print("  ✗ Python not found")
        failed = True

    # PostgreSQL
    print("\nChecking PostgreSQL...")
    if shutil.which("psql"):
        ver = run_command(["psql", "--version"])
        print(f"  ✓ PostgreSQL {parse_version(ver.split()[-1]) if ver else '(version unknown)'}")
    else:
        print("  ⚠ psql not found (optional — required for production)")
        print("    Install: brew install postgresql / apt install postgresql")

    # Redis
    print("\nChecking Redis...")
    if shutil.which("redis-cli"):
        ver = run_command(["redis-cli", "--version"])
        print(f"  ✓ Redis {parse_version(ver) if ver else '(version unknown)'}")
    else:
        print("  ⚠ redis-cli not found (optional — required for SSE + cache)")
        print("    Install: brew install redis / apt install redis")

    # Alembic vs merged DATABASE_URL (same merge order as scripts/serve.sh)
    print("\nChecking Alembic migration head (merged DATABASE_URL)...")
    if py:
        repo = repo_root_from_script()
        status, hint = alembic_migration_status(py, repo)
        if status == "skip":
            print("  ⚠ Skipped — DATABASE_URL not set after merging backend/.env and repo .env")
        elif status == "ok":
            print(f"  ✓ Alembic at head ({hint})")
        elif status == "unverified":
            print(
                "  ⚠ Alembic could not be verified "
                "(database down, driver missing, or wrong DATABASE_URL)."
            )
            if hint:
                print(f"    {hint}")
        elif status == "drift":
            print("  ✗ Alembic revision does not match head")
            print(f"    {hint}")
            print("    Fix: repo root → make migrate")
            failed = True
        else:
            print(f"  ⚠ Unexpected Alembic status: {status}")
    else:
        print("  ⚠ Skipped — Python interpreter not available")

    # Docker
    print("\nChecking Docker...")
    if shutil.which("docker"):
        ver = run_command(["docker", "--version"])
        print(f"  ✓ Docker {parse_version(ver.split()[-1].rstrip(',')) if ver else '(version unknown)'}")
    else:
        print("  ⚠ Docker not found (optional — required for production deployment)")

    print()
    if not failed:
        print("==========================================")
        print("  ✓ All required dependencies installed!")
        print("==========================================")
        print()
        print("Next steps:")
        print("  make config   - Generate local config files")
        print("  make install  - Install project dependencies")
        print("  make migrate   - Align DB migrations (merged env)")
        print("  make dev      - Start development server")
        return 0

    print("==========================================")
    print("  ✗ Some dependencies are missing")
    print("==========================================")
    print()
    print("Please install the missing tools and run 'make check' again.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
