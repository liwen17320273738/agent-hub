"""Agent-to-agent delegation.

Lets a running agent hand a focused subtask to a specialist agent
(security review, data analysis, legal check, DBA opinion, …) and
get its synthesized answer back.

This is what turns the team from "5-stage pipeline" into a
"squad that can call in specialists on demand".

Design notes:
- Looks up the specialist via a stable `role` key (`architect`,
  `developer`, `qa`, `devops`, `security`, `designer`, `data`,
  `marketing`, `finance`, `legal`, `acceptance`, `product`, `cto`, `ceo`).
- Spins up an isolated `AgentRuntime` with the specialist's tools.
- Uses a fresh DB session so it doesn't fight with the caller's transaction.
- Returns the specialist's final text (truncated for safety).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from ..agents.seed import AGENT_TOOLS
from ..database import async_session_factory
from .agent_runtime import AgentRuntime

logger = logging.getLogger(__name__)

ROLE_TO_SEED_ID: Dict[str, str] = {
    "ceo": "wayne-ceo",
    "cto": "wayne-cto",
    "architect": "wayne-cto",
    "product": "wayne-product",
    "developer": "wayne-developer",
    "frontend": "wayne-developer",
    "backend": "wayne-developer",
    "qa": "wayne-qa",
    "tester": "wayne-qa",
    "designer": "wayne-designer",
    "ui": "wayne-designer",
    "ux": "wayne-designer",
    "devops": "wayne-devops",
    "sre": "wayne-devops",
    "security": "wayne-security",
    "acceptance": "wayne-acceptance",
    "data": "wayne-data",
    "analyst": "wayne-data",
    "marketing": "wayne-marketing",
    "finance": "wayne-finance",
    "legal": "wayne-legal",
}

_SHORT_PROMPTS: Dict[str, str] = {
    "wayne-ceo":         "你是 CEO Agent — 战略与优先级专家。从公司全局视角回答。",
    "wayne-cto":         "你是 CTO / 架构师 — 技术选型与架构权衡专家。给出可落地的技术建议。",
    "wayne-product":     "你是产品专家 — 关注用户价值、功能边界、验收标准。",
    "wayne-developer":   "你是高级全栈工程师 — 给出可直接运行的代码或精准修改建议。",
    "wayne-qa":          "你是测试负责人 — 输出测试用例、风险点、回归矩阵。",
    "wayne-designer":    "你是 UI/UX 设计师 — 输出界面/交互/视觉建议，必要时给出布局描述。",
    "wayne-devops":      "你是 DevOps / SRE — 给出部署、监控、回滚、容量、CI/CD 建议。",
    "wayne-security":    "你是安全专家 — 找出漏洞、给出加固方案，遵循 OWASP / 最小权限。",
    "wayne-acceptance":  "你是验收 Agent — 用 PRD 验收标准核对实现，输出通过/打回。",
    "wayne-data":        "你是数据分析师 — 输出数据模型、指标、SQL、可视化建议。",
    "wayne-marketing":   "你是市场营销 — 输出文案、定位、获客策略。",
    "wayne-finance":     "你是财务顾问 — 输出成本、ROI、定价建议。",
    "wayne-legal":       "你是法务顾问 — 检查合规、隐私、条款风险。",
}

_MAX_RETURN_CHARS = 8000


async def delegate_to_agent(params: Dict[str, Any]) -> str:
    """Tool entry: delegate a subtask to a specialist agent.

    Params:
        role:    one of ROLE_TO_SEED_ID keys (e.g. 'security', 'designer')
        task:    the question or subtask description (string)
        context: optional dict of extra context (will be appended)
        max_steps: optional int, agent loop budget (default 3)
    """
    role = (params.get("role") or "").strip().lower()
    task = (params.get("task") or "").strip()
    if not role or not task:
        return "Error: both 'role' and 'task' are required"

    seed_id = ROLE_TO_SEED_ID.get(role)
    if not seed_id:
        valid = ", ".join(sorted(set(ROLE_TO_SEED_ID.keys())))
        return f"Error: unknown role '{role}'. Valid roles: {valid}"

    tools = list(AGENT_TOOLS.get(seed_id, []))
    tools = [t for t in tools if t != "delegate_to_agent"]
    system_prompt = _SHORT_PROMPTS.get(seed_id, "你是一位资深领域专家。")

    max_steps = int(params.get("max_steps") or 3)
    max_steps = max(1, min(max_steps, 8))

    context = params.get("context") if isinstance(params.get("context"), dict) else None

    runtime = AgentRuntime(
        agent_id=seed_id,
        system_prompt=system_prompt,
        tools=tools,
        max_steps=max_steps,
        temperature=0.5,
    )

    try:
        async with async_session_factory() as db:
            async with db.begin():
                result = await runtime.execute(db, task=task, context=context)
    except Exception as e:
        logger.warning(f"[delegate] runtime failed for role={role}: {e}")
        return f"Error: delegate to {role} failed: {e}"

    if not result.get("ok"):
        return f"Error: delegate {role} returned failure: {result.get('error', 'unknown')}"

    output = (result.get("content") or "").strip()
    if not output:
        return f"[delegate→{role}] (empty response)"
    if len(output) > _MAX_RETURN_CHARS:
        output = output[:_MAX_RETURN_CHARS] + f"\n…[truncated, {len(output) - _MAX_RETURN_CHARS} chars]"
    steps = result.get("steps", 0)
    return f"[delegate→{role} | steps={steps}]\n\n{output}"
