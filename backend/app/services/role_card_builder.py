"""Build structured system prompts from Agent role cards.

Step 4: Replaces free-text system_prompt with structured role_card composition.
Agents defined in seed.py now carry persona, mission, workflow_steps,
output_template, success_metrics, and handoff_protocol.

The pipeline_engine calls `build_system_prompt(agent_row, stage_id)` to
compose a deterministic, high-quality prompt from these structured fields.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def build_system_prompt(
    role_card: Dict[str, Any],
    capabilities: Dict[str, Any],
    agent_name: str = "",
    stage_id: str = "",
    extra_context: str = "",
) -> str:
    """Compose a system prompt from structured role card fields.

    Falls back to a minimal prompt if role_card is empty (backward compat).
    """
    if not role_card:
        return ""

    parts: list[str] = []

    persona = role_card.get("persona", "")
    if persona:
        parts.append(f"# 角色\n{persona}")

    seniority = capabilities.get("seniority", "")
    if seniority:
        parts.append(f"经验: {seniority}")

    mission = role_card.get("mission", [])
    if mission:
        lines = "\n".join(f"- {m}" for m in mission)
        parts.append(f"\n## 核心使命\n{lines}")

    standards = capabilities.get("standards", [])
    if standards:
        lines = "\n".join(f"- {s}" for s in standards)
        parts.append(f"\n## 关键规则（必须遵循）\n{lines}")

    workflow = role_card.get("workflow_steps", [])
    if workflow:
        lines = "\n".join(workflow)
        parts.append(f"\n## 工作流程\n{lines}")

    output_template = role_card.get("output_template", "")
    if output_template:
        parts.append(f"\n## 交付物模板\n请严格按照以下模板输出：\n\n{output_template}")

    success_metrics = role_card.get("success_metrics", [])
    if success_metrics:
        lines = "\n".join(f"- {m}" for m in success_metrics)
        parts.append(f"\n## 成功指标（自检清单）\n完成后逐条核对：\n{lines}")

    handoff = role_card.get("handoff_protocol", [])
    if handoff:
        lines = "\n".join(
            f"- 当「{h['when']}」时 → 委托给 {h['to']}，提供: {h.get('context', '')}"
            for h in handoff if isinstance(h, dict)
        )
        parts.append(f"\n## 协作委托\n{lines}")

    boundary = capabilities.get("boundary", {})
    if boundary:
        handles = boundary.get("handles", [])
        delegates = boundary.get("delegates_to", {})
        if handles:
            parts.append(f"\n## 职责边界\n你负责: {', '.join(handles)}")
        if delegates:
            for domain, to_whom in delegates.items():
                parts.append(f"- {domain}: {to_whom}")

    if extra_context:
        parts.append(f"\n{extra_context}")

    return "\n".join(parts)


def build_skill_criteria_check(
    stage_output: str,
    completion_criteria: List[str],
) -> List[Dict[str, Any]]:
    """Check stage output against skill completion criteria.

    Returns a list of {criterion, passed, reason} dicts.
    This is a lightweight text-based check (no LLM needed).
    """
    results = []
    output_lower = stage_output.lower() if stage_output else ""
    output_len = len(stage_output) if stage_output else 0

    for criterion in completion_criteria:
        passed = False
        reason = ""

        if "≥" in criterion or ">=" in criterion:
            passed = output_len > 200
            reason = f"output length={output_len}" if not passed else "ok"
        elif "包含" in criterion:
            keyword = criterion.replace("包含", "").strip()
            keyword_parts = [k.strip() for k in keyword.split("/") if k.strip()]
            if keyword_parts:
                passed = any(kp.lower() in output_lower for kp in keyword_parts)
            else:
                passed = True
            reason = "found" if passed else "keyword not found in output"
        elif "结论" in criterion and ("PASS" in criterion or "APPROVED" in criterion):
            passed = any(kw in stage_output for kw in ["PASS", "NEEDS WORK", "BLOCKED", "APPROVED", "REJECTED"])
            reason = "conclusion found" if passed else "no conclusion keyword"
        else:
            passed = output_len > 100
            reason = "generic check"

        results.append({
            "criterion": criterion,
            "passed": passed,
            "reason": reason,
        })

    return results
