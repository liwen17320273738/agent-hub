"""Tests for planner-worker model resolution."""
from __future__ import annotations

from app.services.planner_worker import (
    resolve_model,
    estimate_stage_cost,
)


def test_developer_gets_execution_tier():
    result = resolve_model("developer", "development")
    assert result["tier"] in ("execution", "preferred")


def test_orchestrator_gets_planning_tier():
    result = resolve_model("orchestrator")
    assert result["tier"] == "planning"


def test_unknown_role_falls_to_routine():
    result = resolve_model("unknown-role")
    assert result["tier"] == "routine"


def test_preferred_model_override():
    result = resolve_model("developer", preferred_model="my-custom-model")
    assert result["model"] == "my-custom-model"
    assert result["tier"] == "preferred"


def test_high_complexity_overrides_tier():
    result = resolve_model("Agent-marketing", complexity="high")
    assert result["tier"] == "planning"


def test_available_providers_filter():
    result = resolve_model(
        "developer", "development", available_providers=["deepseek"]
    )
    assert result.get("provider") == "deepseek" or result["model"] == "deepseek-chat"


def test_estimate_stage_cost():
    est = estimate_stage_cost("development", "developer")
    assert "estimated_cost_usd" in est
    assert est["estimated_cost_usd"] >= 0


def test_lead_agent_role_resolution():
    """lead-agent role should not crash (it was missing from ROLE_TIER_MAP)."""
    result = resolve_model("lead-agent")
    assert "model" in result
