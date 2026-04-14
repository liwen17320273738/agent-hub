#!/usr/bin/env python3
"""Cross-platform dependency checker for Agent Hub."""
from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Optional


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
    py = shutil.which("python3") or shutil.which("python")
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
