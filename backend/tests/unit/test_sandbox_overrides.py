"""DB-backed sandbox override regression tests.

What's covered:

  * ``override_decision`` synchronously consults the in-memory cache
    populated by ``preload_overrides`` and kept consistent by
    ``upsert_rule`` / ``delete_rule``.
  * ``role_allowed`` (the central gatekeeper in ``tools/registry.py``)
    honours DB overrides BEFORE falling back to ``COMMON_TOOLS`` and
    ``ROLE_TOOL_WHITELIST``.
  * ``role_tool_summary`` surfaces overrides via the ``overrides``
    field so the UI matrix can paint the "覆盖" badge.

These exercise the full closed loop: baseline → upsert → assert flip
→ delete → assert restored. Each test resets the cache to the DB
state at start so cases don't leak into each other.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import sandbox_overrides
from app.services.tools.registry import role_allowed, role_tool_summary

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_cache(db: AsyncSession):
    """Each test starts with a clean cache, loaded from the (empty) test
    DB. Without this autouse fixture, state from prior tests would leak
    into ``override_decision``.
    """
    sandbox_overrides._CACHE.clear()
    sandbox_overrides._CACHE_LOADED = False
    await sandbox_overrides.preload_overrides(db)
    yield
    sandbox_overrides._CACHE.clear()
    sandbox_overrides._CACHE_LOADED = False


async def test_preload_empty_table_marks_cache_loaded(db: AsyncSession):
    """An empty table is still a successful load — ``override_decision``
    must return None (defer to baseline), not stay in the
    "cache-not-loaded" state."""
    assert sandbox_overrides._CACHE_LOADED is True
    assert sandbox_overrides.override_decision("ceo", "bash") is None


async def test_upsert_then_decision_returns_true(db: AsyncSession):
    await sandbox_overrides.upsert_rule(
        db, role="ceo", tool="bash", allowed=True,
        note="oncall override", updated_by="test",
    )
    await db.commit()
    assert sandbox_overrides.override_decision("ceo", "bash") is True


async def test_upsert_then_decision_returns_false(db: AsyncSession):
    """Force-deny case — admin can lock down a previously-allowed tool."""
    await sandbox_overrides.upsert_rule(
        db, role="developer", tool="git_push", allowed=False,
        note="freeze before release", updated_by="test",
    )
    await db.commit()
    assert sandbox_overrides.override_decision("developer", "git_push") is False


async def test_delete_reverts_to_baseline(db: AsyncSession):
    await sandbox_overrides.upsert_rule(
        db, role="ceo", tool="bash", allowed=True, updated_by="test",
    )
    await db.commit()
    assert sandbox_overrides.override_decision("ceo", "bash") is True

    removed = await sandbox_overrides.delete_rule(db, role="ceo", tool="bash")
    await db.commit()
    assert removed is True
    assert sandbox_overrides.override_decision("ceo", "bash") is None


async def test_delete_missing_rule_returns_false(db: AsyncSession):
    """Deleting a non-existent rule is a no-op (caller will 404)."""
    removed = await sandbox_overrides.delete_rule(db, role="ceo", tool="bash")
    assert removed is False


async def test_role_allowed_honours_db_override(db: AsyncSession):
    """Baseline: ceo can't bash. With override → can. Without → can't again."""
    assert role_allowed("ceo", "bash") is False, (
        "baseline must be deny — if this fires, the in-code "
        "ROLE_TOOL_WHITELIST changed and the test needs updating"
    )

    await sandbox_overrides.upsert_rule(
        db, role="ceo", tool="bash", allowed=True, updated_by="test",
    )
    await db.commit()
    assert role_allowed("ceo", "bash") is True

    await sandbox_overrides.delete_rule(db, role="ceo", tool="bash")
    await db.commit()
    assert role_allowed("ceo", "bash") is False


async def test_role_allowed_force_deny_overrides_baseline_allow(db: AsyncSession):
    """Inverse direction: a baseline-allowed tool can be force-denied."""
    assert role_allowed("developer", "file_write") is True, "baseline drift"

    await sandbox_overrides.upsert_rule(
        db, role="developer", tool="file_write", allowed=False, updated_by="test",
    )
    await db.commit()
    assert role_allowed("developer", "file_write") is False

    await sandbox_overrides.delete_rule(db, role="developer", tool="file_write")
    await db.commit()
    assert role_allowed("developer", "file_write") is True


async def test_role_tool_summary_surfaces_overrides(db: AsyncSession):
    """The matrix UI reads ``overrides`` to paint the purple ring.

    Only *meaningful* overrides are surfaced — i.e. force-allow on a
    tool that the baseline would deny, or force-deny on a tool that
    the baseline would allow. A force-deny on a tool that's already
    denied is a no-op and isn't flagged (avoids visual noise).
    """
    # ceo baseline denies bash → force-allow surfaces in overrides.allow
    await sandbox_overrides.upsert_rule(
        db, role="ceo", tool="bash", allowed=True, updated_by="test",
    )
    # developer baseline ALLOWS file_write → force-deny surfaces
    await sandbox_overrides.upsert_rule(
        db, role="developer", tool="file_write", allowed=False, updated_by="test",
    )
    await db.commit()

    ceo_summary = role_tool_summary("ceo")
    assert "bash" in ceo_summary["overrides"]["allow"], (
        f"expected allow-override on bash, got {ceo_summary['overrides']}"
    )

    dev_summary = role_tool_summary("developer")
    assert "file_write" in dev_summary["overrides"]["deny"], (
        f"expected deny-override on file_write, got {dev_summary['overrides']}"
    )
    # And the effective view should reflect the deny:
    assert "file_write" not in dev_summary["allowed"]


async def test_list_rules_filters_by_role(db: AsyncSession):
    await sandbox_overrides.upsert_rule(
        db, role="ceo", tool="bash", allowed=True, updated_by="test",
    )
    await sandbox_overrides.upsert_rule(
        db, role="developer", tool="git_push", allowed=False, updated_by="test",
    )
    await db.commit()

    all_rules = await sandbox_overrides.list_rules(db)
    assert len(all_rules) == 2

    only_ceo = await sandbox_overrides.list_rules(db, role="ceo")
    assert len(only_ceo) == 1
    assert only_ceo[0]["tool"] == "bash"


async def test_override_decision_no_role_returns_none(db: AsyncSession):
    """Calls without a role configured (back-compat) skip the cache entirely."""
    await sandbox_overrides.upsert_rule(
        db, role="ceo", tool="bash", allowed=True, updated_by="test",
    )
    await db.commit()
    assert sandbox_overrides.override_decision(None, "bash") is None
    assert sandbox_overrides.override_decision("", "bash") is None
