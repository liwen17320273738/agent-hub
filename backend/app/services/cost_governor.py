"""
Cost Governor — per-task budget tracking + automatic model downgrade.

Usage from execute_stage:

    from .cost_governor import pre_check_budget, record_stage_cost

    decision = await pre_check_budget(task_id)
    if decision.action == "block":
        ...halt with approval_id...
    elif decision.action == "downgrade":
        model = decision.fallback_model

    # ...run LLM...

    await record_stage_cost(
        task_id, stage_id=stage_id, role=role,
        model=model, cost_usd=cost, tokens=total_tokens,
    )

Soft limit (default 60% of hard limit) → next stage uses the cheapest model
in the same provider family.
Hard limit → stage is blocked, an approval ticket is created via the existing
guardrails system, and the user must explicitly raise the budget to continue.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..redis_client import get_redis

logger = logging.getLogger(__name__)

_BUDGET_KEY = "cost_governor:task:{task_id}"
_BUDGET_TTL = 86400 * 7  # 7 days

DEFAULT_TASK_BUDGET_USD = 1.00     # per single task hard ceiling
DEFAULT_SOFT_RATIO = 0.60          # downgrade once spent >= 60% of budget
DEFAULT_HARD_BLOCK_RATIO = 1.00    # block at 100%

# When a stage is told to "downgrade", these are the cheap fallbacks (cost-tier
# ROUTINE in planner_worker.py). Order = preference. The governor will pick the
# first whose provider key is configured; resolve_model normally returns the
# expensive winner so we override here only when over budget.
DOWNGRADE_CANDIDATES: List[Dict[str, str]] = [
    {"model": "deepseek-chat",   "provider": "deepseek"},
    {"model": "glm-4-flash",     "provider": "zhipu"},
    {"model": "qwen-turbo",      "provider": "qwen"},
    {"model": "gpt-4o-mini",     "provider": "openai"},
    {"model": "gemini-2.5-flash","provider": "google"},
]


@dataclass
class BudgetDecision:
    action: str  # "ok" | "downgrade" | "block"
    spent_usd: float = 0.0
    budget_usd: float = DEFAULT_TASK_BUDGET_USD
    soft_ratio: float = DEFAULT_SOFT_RATIO
    hard_ratio: float = DEFAULT_HARD_BLOCK_RATIO
    fallback_model: Optional[str] = None
    fallback_provider: Optional[str] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "action": self.action,
            "spent_usd": round(self.spent_usd, 6),
            "budget_usd": round(self.budget_usd, 6),
            "spent_ratio": round(self.spent_usd / self.budget_usd, 4) if self.budget_usd else 0.0,
            "soft_ratio": self.soft_ratio,
            "hard_ratio": self.hard_ratio,
            "fallback_model": self.fallback_model,
            "fallback_provider": self.fallback_provider,
            "reason": self.reason,
        }


def _state_key(task_id: str) -> str:
    return _BUDGET_KEY.format(task_id=task_id)


async def set_task_budget(
    task_id: str,
    budget_usd: float,
    *,
    soft_ratio: float = DEFAULT_SOFT_RATIO,
    hard_ratio: float = DEFAULT_HARD_BLOCK_RATIO,
) -> None:
    """Override the budget for a specific task (called by API/UI)."""
    r = get_redis()
    state = await _load_state(task_id) or {"spent_usd": 0.0, "stages": []}
    state["budget_usd"] = float(budget_usd)
    state["soft_ratio"] = float(soft_ratio)
    state["hard_ratio"] = float(hard_ratio)
    state["overridden"] = True
    await r.set(_state_key(task_id), json.dumps(state), ex=_BUDGET_TTL)


async def raise_budget(task_id: str, additional_usd: float) -> float:
    """Bump the task budget (used by the approve-block-and-continue endpoint)."""
    r = get_redis()
    state = await _load_state(task_id) or {"spent_usd": 0.0, "stages": []}
    new_budget = float(state.get("budget_usd", DEFAULT_TASK_BUDGET_USD)) + float(additional_usd)
    state["budget_usd"] = new_budget
    state["blocked"] = False
    await r.set(_state_key(task_id), json.dumps(state), ex=_BUDGET_TTL)
    return new_budget


async def _load_state(task_id: str) -> Optional[Dict]:
    r = get_redis()
    raw = await r.get(_state_key(task_id))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def get_task_budget(task_id: str) -> Dict[str, object]:
    """Return the current spend snapshot for a task."""
    state = await _load_state(task_id) or {}
    spent = float(state.get("spent_usd", 0.0))
    budget = float(state.get("budget_usd", DEFAULT_TASK_BUDGET_USD))
    return {
        "task_id": task_id,
        "spent_usd": round(spent, 6),
        "budget_usd": round(budget, 6),
        "spent_ratio": round(spent / budget, 4) if budget else 0.0,
        "stages": state.get("stages", []),
        "blocked": bool(state.get("blocked")),
        "overridden": bool(state.get("overridden")),
    }


def _pick_downgrade(available_providers: Optional[List[str]]) -> Optional[Dict[str, str]]:
    if not available_providers:
        return DOWNGRADE_CANDIDATES[0]
    for c in DOWNGRADE_CANDIDATES:
        if c["provider"] in available_providers:
            return c
    return None


async def pre_check_budget(
    task_id: str,
    *,
    available_providers: Optional[List[str]] = None,
) -> BudgetDecision:
    """Decide whether the next LLM call should run, downgrade, or be blocked."""
    state = await _load_state(task_id) or {}
    spent = float(state.get("spent_usd", 0.0))
    budget = float(state.get("budget_usd", DEFAULT_TASK_BUDGET_USD))
    soft_ratio = float(state.get("soft_ratio", DEFAULT_SOFT_RATIO))
    hard_ratio = float(state.get("hard_ratio", DEFAULT_HARD_BLOCK_RATIO))

    if budget <= 0:
        return BudgetDecision(action="ok", spent_usd=spent, budget_usd=budget,
                              soft_ratio=soft_ratio, hard_ratio=hard_ratio,
                              reason="budget disabled")

    spent_ratio = spent / budget
    if spent_ratio >= hard_ratio:
        return BudgetDecision(
            action="block",
            spent_usd=spent, budget_usd=budget,
            soft_ratio=soft_ratio, hard_ratio=hard_ratio,
            reason=f"task spent ${spent:.4f} / ${budget:.2f} (>= {int(hard_ratio*100)}% hard limit)",
        )

    if spent_ratio >= soft_ratio:
        fb = _pick_downgrade(available_providers)
        if fb:
            return BudgetDecision(
                action="downgrade",
                spent_usd=spent, budget_usd=budget,
                soft_ratio=soft_ratio, hard_ratio=hard_ratio,
                fallback_model=fb["model"], fallback_provider=fb["provider"],
                reason=f"task spent ${spent:.4f} / ${budget:.2f} ({int(spent_ratio*100)}%) >= {int(soft_ratio*100)}% soft cap, downgrading to {fb['model']}",
            )

    return BudgetDecision(
        action="ok",
        spent_usd=spent, budget_usd=budget,
        soft_ratio=soft_ratio, hard_ratio=hard_ratio,
    )


async def record_stage_cost(
    task_id: str,
    *,
    stage_id: str,
    role: str,
    model: str,
    cost_usd: float,
    tokens: int,
) -> Dict[str, object]:
    """Append the stage's spend to the task's running ledger."""
    r = get_redis()
    state = await _load_state(task_id) or {
        "spent_usd": 0.0,
        "budget_usd": DEFAULT_TASK_BUDGET_USD,
        "soft_ratio": DEFAULT_SOFT_RATIO,
        "hard_ratio": DEFAULT_HARD_BLOCK_RATIO,
        "stages": [],
    }
    state["spent_usd"] = float(state.get("spent_usd", 0.0)) + float(cost_usd or 0.0)
    stages: List[Dict] = state.get("stages") or []
    stages.append({
        "stage_id": stage_id, "role": role,
        "model": model, "cost_usd": round(float(cost_usd or 0.0), 6),
        "tokens": int(tokens or 0),
    })
    # cap to last 50 entries to avoid unbounded growth on long retry loops
    state["stages"] = stages[-50:]
    await r.set(_state_key(task_id), json.dumps(state), ex=_BUDGET_TTL)
    return {
        "spent_usd": round(state["spent_usd"], 6),
        "budget_usd": round(float(state["budget_usd"]), 6),
    }


async def reset_task_budget(task_id: str) -> None:
    r = get_redis()
    await r.delete(_state_key(task_id))
