"""Clean all historical pipeline, artifact, and audit data from the database.

Preserves system records: users, orgs, workspaces, agents, skills, artifact types.
Deletes transactional records: pipeline_tasks, task_artifacts, conversations,
traces/audit logs, share tokens, working memory, scheduled task state.

Usage:
    cd backend
    python3 -m scripts.clean_historical_data
"""
from __future__ import annotations

import asyncio
import os

# Load env same as the app
from dotenv import load_dotenv

load_dotenv("../.env")
load_dotenv(".env")

# Set JWT_SECRET for config loading (won't be used for data cleanup)
os.environ.setdefault("JWT_SECRET", "cleanup-script-temp-secret-key-32chars!")

from sqlalchemy import inspect, text
from app.database import engine


async def get_existing_tables(conn) -> set[str]:
    """Return set of existing table names in the database."""
    tables = set()
    try:
        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
        )
        tables = {row[0] for row in result}
    except Exception:
        # Fallback for SQLite
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )
        tables = {row[0] for row in result}
    return tables


async def clean() -> None:
    print("Connecting to database...")
    async with engine.begin() as conn:
        existing = await get_existing_tables(conn)
        print(f"Found {len(existing)} existing tables.")

        tables_to_clean = [
            "task_artifacts",
            "pipeline_artifacts",
            "pipeline_stages",
            "pipeline_tasks",
            "conversation_messages",
            "conversations",
            "traces",
            "trace_spans",
            "audit_logs",
            "share_tokens",
            "scheduler_task_state",
            "approval_queue",
            "flow_executions",
            "notifications",
            "sse_events",
            "deliverable_packages",
            "credential_events",
            "task_workspace_roots",
            "workflow_runs",
            "plans",
            "reports",
            "agent_runs",
            "model_cache",
            "working_memory",
            "skill_invocations",
            "pipeline_events",
        ]

        for table in tables_to_clean:
            if table not in existing:
                print(f"  SKIPPED {table}: table does not exist")
                continue
            try:
                result = await conn.execute(text(f"DELETE FROM {table}"))
                count = result.rowcount
                print(f"  CLEANED {table}: {count} rows deleted")
            except Exception as e:
                print(f"  ERROR {table}: {e}")

        # Reset sequences if PostgreSQL
        try:
            for seq in [
                "pipeline_tasks_id_seq",
                "task_artifacts_id_seq",
                "conversations_id_seq",
            ]:
                try:
                    await conn.execute(text(f"SELECT setval('{seq}', 1, false)"))
                except Exception:
                    pass
        except Exception:
            pass

    print("\nHistorical data cleanup complete.")


if __name__ == "__main__":
    asyncio.run(clean())
