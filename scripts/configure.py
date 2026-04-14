#!/usr/bin/env python3
"""Config bootstrap script for Agent Hub — generates local config from examples."""
from __future__ import annotations

import secrets
import shutil
import sys
from pathlib import Path


def copy_if_missing(src: Path, dst: Path, transform=None) -> bool:
    if dst.exists():
        print(f"  ⊘ {dst.name} already exists, skipping")
        return False
    if not src.exists():
        print(f"  ✗ Template not found: {src}")
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if transform:
        content = src.read_text()
        content = transform(content)
        dst.write_text(content)
    else:
        shutil.copyfile(src, dst)
    print(f"  ✓ Created {dst.name}")
    return True


def inject_jwt_secret(content: str) -> str:
    """Generate a random JWT_SECRET for new .env files."""
    secret = secrets.token_urlsafe(48)
    return content.replace("JWT_SECRET=", f"JWT_SECRET={secret}")


def main() -> int:
    root = Path(__file__).resolve().parent.parent

    print("==========================================")
    print("  Generating Configuration Files")
    print("==========================================")
    print()

    copy_if_missing(
        root / "backend" / ".env.example",
        root / "backend" / ".env",
        transform=inject_jwt_secret,
    )
    copy_if_missing(
        root / ".env.example",
        root / ".env",
    )
    copy_if_missing(
        root / "config.example.yaml",
        root / "config.yaml",
    )

    print()
    print("✓ Configuration files generated")
    print()
    print("Next steps:")
    print("  1. Edit backend/.env with your API keys")
    print("  2. Edit config.yaml to configure models and tools")
    print("  3. Run: make install")
    print("  4. Run: make dev")
    return 0


if __name__ == "__main__":
    sys.exit(main())
