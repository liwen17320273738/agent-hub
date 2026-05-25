"""Ensure a default workspace exists with allow_draft_delivery for E2E smoke tests.

Prints the workspace UUID on stdout (single line).

Usage:
    cd backend && python3 -m scripts.prepare_e2e_workspace
"""
from __future__ import annotations

import asyncio
import os
import uuid

from dotenv import load_dotenv

load_dotenv("../.env")
load_dotenv(".env")
os.environ.setdefault("JWT_SECRET", "e2e-smoke-secret-key-32chars!!")

from sqlalchemy import select, text

from app.database import async_session, engine
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


async def main() -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE workspaces SET allow_draft_delivery = true "
                "WHERE allow_draft_delivery IS NOT TRUE"
            )
        )

    async with async_session() as db:
        row = await db.execute(
            select(Workspace).where(Workspace.is_default.is_(True)).limit(1)
        )
        ws = row.scalar_one_or_none()
        if ws is not None:
            ws.allow_draft_delivery = True
            await db.commit()
            print(str(ws.id))
            return

        row = await db.execute(select(Workspace).limit(1))
        ws = row.scalar_one_or_none()
        if ws is not None:
            ws.is_default = True
            ws.allow_draft_delivery = True
            await db.commit()
            print(str(ws.id))
            return

        user_row = await db.execute(
            select(User).where(User.email == "admin@example.com").limit(1)
        )
        admin = user_row.scalar_one_or_none()
        if admin is None:
            user_row = await db.execute(select(User).limit(1))
            admin = user_row.scalar_one_or_none()
        if admin is None:
            raise SystemExit("No users in database — run make reset-admin first")

        ws = Workspace(
            id=uuid.uuid4(),
            org_id=admin.org_id,
            name="Default",
            description="E2E smoke workspace",
            is_default=True,
            allow_draft_delivery=True,
        )
        db.add(ws)
        await db.flush()
        db.add(
            WorkspaceMember(
                workspace_id=ws.id,
                user_id=admin.id,
                role="admin",
            )
        )
        await db.commit()
        print(str(ws.id))


if __name__ == "__main__":
    asyncio.run(main())
