"""Resolve runtime agent id: seed, role alias, or DB-backed custom profile."""
from __future__ import annotations

import pytest

from app.api.agents import _resolve_runtime_agent_id, _resolve_seed_id
from app.models.agent import AgentDefinition


def test_resolve_seed_still_builtin():
    assert _resolve_seed_id("Agent-developer") == "Agent-developer"
    assert _resolve_seed_id("developer") == "Agent-developer"


@pytest.mark.asyncio
async def test_resolve_runtime_custom_profile(db):
    assert _resolve_seed_id("wayne-ceo") is None

    db.add(
        AgentDefinition(
            id="wayne-ceo",
            name="Wayne CEO",
            title="CEO",
            is_active=True,
        )
    )
    await db.flush()

    rid = await _resolve_runtime_agent_id(db, "wayne-ceo")
    assert rid == "wayne-ceo"


@pytest.mark.asyncio
async def test_resolve_runtime_inactive_custom_not_found(db):
    db.add(
        AgentDefinition(
            id="fork-inactive",
            name="X",
            title="Y",
            is_active=False,
        )
    )
    await db.flush()

    assert await _resolve_runtime_agent_id(db, "fork-inactive") is None
