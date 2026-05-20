#!/usr/bin/env python3
"""Set an existing user's password_hash to match ADMIN_PASSWORD from env.

Use when the database was bootstrapped with different credentials than your
current ``backend/.env`` (common after copying ``.env`` or restoring a dump).

Usage (from repo root or backend/)::

    cd backend && python3 -m scripts.reset_admin_password

Requires the same effective ``DATABASE_URL``, ``ADMIN_EMAIL``, and ``ADMIN_PASSWORD``
as the running API. Resolution order matches ``Settings``: OS environment overrides
``.env`` files; among files, ``backend/.env`` then ``../.env`` at repo root (later
wins for duplicate keys). Prefer ``make reset-admin`` from the repo root so the
shell loads the same files as ``scripts/serve.sh``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))


async def main() -> int:
    from sqlalchemy import select

    from app.config import settings
    from app.database import async_session_factory
    from app.models.user import User
    from app.security import hash_password

    if not settings.admin_email or not settings.admin_password:
        print(
            "ADMIN_EMAIL and ADMIN_PASSWORD must be set (e.g. in backend/.env).",
            file=sys.stderr,
        )
        return 1

    email = settings.admin_email.lower().strip()
    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            print(
                f"No user with email {email!r}. "
                "Clear the DB for first-run bootstrap, or register a user first.",
                file=sys.stderr,
            )
            return 2

        user.password_hash = hash_password(settings.admin_password)
        await db.commit()

    print(
        f"Updated password for {email} (ADMIN_PASSWORD length {len(settings.admin_password)})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
