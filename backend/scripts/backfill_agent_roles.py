"""
One-shot script: backfill pipeline_role for existing agents.
Run once: python3 backend/scripts/backfill_agent_roles.py
"""
import asyncio, asyncpg

ROLE_MAP = {
    "Agent-ceo": "orchestrator",
    "wayne-ce": "orchestrator",
    "Agent-cto": "tech-lead",
    "wayne-ct": "tech-lead",
    "Agent-pm": "product-manager",
    "wayne-pm": "product-manager",
    "Agent-dev": "developer",
    "wayne-dev": "developer",
    "Agent-qa": "qa-lead",
    "wayne-qa": "qa-lead",
    "Agent-designer": "designer",
    "wayne-designer": "designer",
    "Agent-devops": "devops",
    "wayne-devops": "devops",
    "Agent-security": "security",
    "wayne-security": "security",
    "Agent-architect": "architect",
    "wayne-architect": "architect",
    "Agent-reviewer": "acceptance",
    "wayne-reviewer": "acceptance",
    "wayne-security": "security",
    "Agent-security": "security",
    "wayne-data": "data-analyst",
    "Agent-data": "data-analyst",
    "wayne-marketing": "marketing",
    "Agent-marketing": "marketing",
    "Agent-finance": "finance",
    "wayne-finance": "finance",
    "wayne-legal": "legal",
    "Agent-legal": "legal",
    "ui-visual-designer": "designer",
}

async def main():
    conn = await asyncpg.connect("postgresql://agenthub:agenthub@localhost:5432/agenthub")
    updated = 0
    for agent_id, role in ROLE_MAP.items():
        result = await conn.execute(
            "UPDATE agents SET pipeline_role = $1 WHERE id = $2 AND pipeline_role IS NULL",
            role, agent_id
        )
        parts = result.split()
        count = int(parts[1]) if len(parts) > 1 else 0
        updated += count
        if count > 0:
            print(f"  {agent_id} -> {role}")
    await conn.close()
    print(f"\nUpdated {updated} agents")

asyncio.run(main())
