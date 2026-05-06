"""
Planner-Worker Separation — 强模型规划 + 便宜模型执行

核心思路:
- Lead Agent (Planner) 使用强模型做任务分析和规划
- Worker Agents 使用便宜模型执行具体子任务
- 根据任务复杂度动态选择模型，在质量和成本之间取最优平衡

模型分级:
- Tier 1 (Planning): qwen-reasoning-distilled (local) / glm-4-plus (zhipu) — 用于需求分析、架构决策、验收评审
- Tier 2 (Execution): gemma-4-26b (local) / glm-4-flash (zhipu) — 用于代码实现、文档撰写
- Tier 3 (Routine): gemma-4-26b (local) / glm-4-flash (zhipu) — 用于格式化、翻译、简单生成
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Optional, Dict, Any

from ..config import settings

logger = logging.getLogger(__name__)


class ModelTier(str, Enum):
    PLANNING = "planning"    # Tier 1: strong reasoning
    EXECUTION = "execution"  # Tier 2: balanced
    ROUTINE = "routine"      # Tier 3: cost-efficient


_LOCAL_STRONG = settings.local_llm_model_strong or "qwen3.6-35b-a3b-claude-4.6-opus-reasoning-distilled@q6_k"
_LOCAL_BASE = settings.llm_model or "google/gemma-4-26b-a4b"
_LOCAL_MODELS = {_LOCAL_STRONG, _LOCAL_BASE}


def _is_local_model(model_id: str) -> bool:
    """Check if a model ID matches one of the configured local models."""
    return model_id in _LOCAL_MODELS

TIER_MODELS: Dict[ModelTier, list] = {
    ModelTier.PLANNING: [
        {"id": _LOCAL_STRONG, "provider": "local", "cost_per_1k": 0.0},
        {"id": "glm-4-plus", "provider": "zhipu", "cost_per_1k": 0.0071},
        {"id": "deepseek-chat", "provider": "deepseek", "cost_per_1k": 0.00021},
        {"id": "claude-opus-4-20250514", "provider": "anthropic", "cost_per_1k": 0.045},
        {"id": "gpt-4.5", "provider": "openai", "cost_per_1k": 0.1125},
        {"id": "gemini-2.5-pro", "provider": "google", "cost_per_1k": 0.00575},
    ],
    ModelTier.EXECUTION: [
        {"id": _LOCAL_BASE, "provider": "local", "cost_per_1k": 0.0},
        {"id": "glm-4-flash", "provider": "zhipu", "cost_per_1k": 0.0001},
        {"id": "deepseek-chat", "provider": "deepseek", "cost_per_1k": 0.00021},
        {"id": "claude-sonnet-4-20250514", "provider": "anthropic", "cost_per_1k": 0.009},
        {"id": "gpt-4o", "provider": "openai", "cost_per_1k": 0.00625},
    ],
    ModelTier.ROUTINE: [
        {"id": _LOCAL_BASE, "provider": "local", "cost_per_1k": 0.0},
        {"id": "glm-4-flash", "provider": "zhipu", "cost_per_1k": 0.0001},
        {"id": "deepseek-chat", "provider": "deepseek", "cost_per_1k": 0.00021},
        {"id": "gpt-4o-mini", "provider": "openai", "cost_per_1k": 0.000375},
        {"id": "qwen-plus", "provider": "qwen", "cost_per_1k": 0.00112},
    ],
}

ROLE_TIER_MAP: Dict[str, ModelTier] = {
    # Planner roles — need strong reasoning
    "Agent-ceo": ModelTier.PLANNING,
    "Agent-cto": ModelTier.PLANNING,
    "Agent-acceptance": ModelTier.PLANNING,
    "orchestrator": ModelTier.PLANNING,
    "lead-agent": ModelTier.PLANNING,
    "architect": ModelTier.PLANNING,

    # Execution roles — balanced quality/cost
    "Agent-product": ModelTier.EXECUTION,
    "Agent-developer": ModelTier.EXECUTION,
    "Agent-qa": ModelTier.EXECUTION,
    "Agent-designer": ModelTier.EXECUTION,
    "Agent-security": ModelTier.EXECUTION,
    "product-manager": ModelTier.EXECUTION,
    "developer": ModelTier.EXECUTION,
    "qa-lead": ModelTier.EXECUTION,
    "devops": ModelTier.EXECUTION,

    # Routine roles — cost-efficient
    "Agent-marketing": ModelTier.ROUTINE,
    "Agent-finance": ModelTier.ROUTINE,
    "Agent-legal": ModelTier.ROUTINE,
    "Agent-data": ModelTier.ROUTINE,
    "Agent-devops": ModelTier.ROUTINE,
    "openclaw": ModelTier.ROUTINE,
}

STAGE_TIER_OVERRIDE: Dict[str, ModelTier] = {
    "discovery": ModelTier.PLANNING,
    "planning": ModelTier.EXECUTION,
    "design": ModelTier.EXECUTION,
    "architecture": ModelTier.PLANNING,
    "development": ModelTier.EXECUTION,
    "testing": ModelTier.EXECUTION,
    "security-review": ModelTier.PLANNING,   # security must reason hard
    "legal-review": ModelTier.PLANNING,      # legal must reason hard
    "data-modeling": ModelTier.EXECUTION,
    "marketing-launch": ModelTier.ROUTINE,
    "finance-review": ModelTier.EXECUTION,
    "reviewing": ModelTier.PLANNING,
    "acceptance": ModelTier.PLANNING,
    "deployment": ModelTier.EXECUTION,
    "retrospective": ModelTier.ROUTINE,
    "lead-agent": ModelTier.PLANNING,
    "subtask": ModelTier.EXECUTION,
}


def resolve_model(
    role: str,
    stage_id: Optional[str] = None,
    available_providers: Optional[list] = None,
    complexity: Optional[str] = None,
    preferred_model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolve the optimal model for a given role + stage combination.

    Priority:
    1. Agent's preferred_model (if set and provider available)
    2. Complexity override (high → planning tier)
    3. Stage-specific tier
    4. Role-based tier
    5. Fallback to cheapest available
    """
    if preferred_model:
        prov = "local" if _is_local_model(preferred_model) else "unknown"
        return {"model": preferred_model, "provider": prov, "tier": "preferred", "reason": "agent preference"}

    if complexity == "high":
        tier = ModelTier.PLANNING
        reason = "high complexity → planning tier"
    elif stage_id and stage_id in STAGE_TIER_OVERRIDE:
        tier = STAGE_TIER_OVERRIDE[stage_id]
        reason = f"stage override: {stage_id}"
    elif role in ROLE_TIER_MAP:
        tier = ROLE_TIER_MAP[role]
        reason = f"role mapping: {role}"
    else:
        tier = ModelTier.ROUTINE
        reason = "default fallback"

    candidates = TIER_MODELS.get(tier, TIER_MODELS[ModelTier.ROUTINE])

    if available_providers:
        filtered = [m for m in candidates if m["provider"] in available_providers]
        if filtered:
            candidates = filtered

    if not candidates:
        return {"model": "deepseek-chat", "tier": tier.value, "reason": "no candidates, ultimate fallback"}

    selected = candidates[0]
    return {
        "model": selected["id"],
        "provider": selected["provider"],
        "tier": tier.value,
        "reason": reason,
        "cost_per_1k": selected["cost_per_1k"],
    }


def estimate_stage_cost(
    stage_id: str,
    role: str,
    estimated_input_tokens: int = 2000,
    estimated_output_tokens: int = 2000,
    available_providers: Optional[list] = None,
) -> Dict[str, Any]:
    """Estimate the cost of running a pipeline stage."""
    resolution = resolve_model(role, stage_id, available_providers)
    cost_per_1k = resolution.get("cost_per_1k", 0.001)
    total_tokens = estimated_input_tokens + estimated_output_tokens
    estimated_cost = (total_tokens / 1000) * cost_per_1k

    return {
        "stage_id": stage_id,
        "role": role,
        "model": resolution["model"],
        "tier": resolution["tier"],
        "estimated_tokens": total_tokens,
        "estimated_cost_usd": round(estimated_cost, 6),
    }


def estimate_pipeline_cost(
    stages: list,
    available_providers: Optional[list] = None,
) -> Dict[str, Any]:
    """Estimate total pipeline cost across all stages."""
    stage_costs = []
    total_cost = 0.0
    total_tokens = 0

    for stage in stages:
        est = estimate_stage_cost(
            stage.get("id", ""),
            stage.get("role", ""),
            available_providers=available_providers,
        )
        stage_costs.append(est)
        total_cost += est["estimated_cost_usd"]
        total_tokens += est["estimated_tokens"]

    return {
        "stages": stage_costs,
        "total_estimated_cost_usd": round(total_cost, 6),
        "total_estimated_tokens": total_tokens,
        "model_breakdown": _group_by_model(stage_costs),
    }


def _group_by_model(costs: list) -> Dict[str, int]:
    groups: Dict[str, int] = {}
    for c in costs:
        model = c["model"]
        groups[model] = groups.get(model, 0) + 1
    return groups
