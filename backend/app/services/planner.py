"""Planner — produce a short, IM-friendly execution plan from a clarified requirement.

Sits BETWEEN the clarifier and the e2e orchestrator:
- Clarifier decided: "yes, the requirement is buildable, here's the refined title/description"
- Planner now turns that into a 4–8 step plan with rough effort/risk/cost,
  formatted for IM display so the user can preview before we burn LLM tokens
  + writes code.

The user then either:
  - approves → gateway calls `run_full_e2e(...)`
  - amends → planner regenerates with their feedback
  - cancels → session cleared

Fail-open: if LLM call fails, returns a generic placeholder plan so the
gateway can still progress (caller decides whether to auto-approve or ask).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from ..config import settings
from .llm_router import chat_completion

logger = logging.getLogger(__name__)


@dataclass
class PlanStep:
    no: int
    title: str
    detail: str = ""
    role: str = ""
    estimate_min: int = 10


@dataclass
class ExecutionPlan:
    title: str
    summary: str = ""
    steps: List[PlanStep] = field(default_factory=list)
    template: str = "full"
    deploy_target: str = "vercel"
    risks: List[str] = field(default_factory=list)
    estimate_min_total: int = 0
    confidence: str = "medium"  # low / medium / high

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["steps"] = [asdict(s) for s in self.steps]
        return d


_SYSTEM = """你是一位 30 年经验的软件项目经理。
你刚收到一份**已经澄清过**的项目需求，现在要把它转成一份**可执行的简短计划**，让需求方在动工前能预览。

输出 JSON（**只输出 JSON，不要 markdown 代码块**）：

{
  "title": "项目一句话标题",
  "summary": "2-3 行高层方案说明（用什么技术、解决什么问题）",
  "steps": [
    {"no": 1, "title": "...", "detail": "...", "role": "product|architect|developer|qa|devops|security|designer|data", "estimate_min": 30},
    ...
  ],
  "template": "full|web_app|api_service|mobile_app|microservice|fullstack_saas|simple|bug_fix|data_pipeline",
  "deploy_target": "vercel|cloudflare|miniprogram|appstore|googleplay|none",
  "risks": ["..."],
  "estimate_min_total": 整数（单位：分钟）,
  "confidence": "low|medium|high"
}

约束：
- steps 必须 4-8 步，按时间顺序
- 每步 estimate_min 现实点（不要 1 分钟也不要 8 小时）
- risks 最多 3 条，最重要的在前
- 不要写废话、客套、重复需求"""


def _strip_json(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _fail_open(title: str, description: str) -> ExecutionPlan:
    return ExecutionPlan(
        title=title or "未命名项目",
        summary=(description or "")[:200] or "（未生成详细方案 — 直接进入流水线）",
        steps=[
            PlanStep(no=1, title="需求规划", detail="产出 PRD", role="product", estimate_min=15),
            PlanStep(no=2, title="架构设计", detail="技术选型 + 数据模型 + API 草案", role="architect", estimate_min=20),
            PlanStep(no=3, title="开发实现", detail="按架构实现核心功能", role="developer", estimate_min=60),
            PlanStep(no=4, title="测试验证", detail="单测 + 端到端", role="qa", estimate_min=20),
            PlanStep(no=5, title="部署上线", detail="构建 + 灰度", role="devops", estimate_min=15),
        ],
        estimate_min_total=130,
        risks=["需求边界可能在落地中再次扩张"],
        confidence="low",
    )


async def make_plan(title: str, description: str) -> ExecutionPlan:
    """Ask the LLM for a short execution plan; fail-open to a generic plan."""
    has_key = any([
        settings.openai_api_key, settings.anthropic_api_key, settings.deepseek_api_key,
        settings.google_api_key, settings.zhipu_api_key, settings.qwen_api_key,
        settings.llm_api_key,
    ])
    if not has_key:
        return _fail_open(title, description)

    user_msg = (
        f"# 已澄清的需求\n## 标题\n{title}\n\n## 描述\n{description}\n\n"
        "请输出该项目的执行计划 JSON。"
    )
    try:
        rsp = await chat_completion(
            model=settings.llm_model or "deepseek-chat",
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
        )
    except Exception as e:
        logger.warning(f"[planner] LLM call failed: {e}")
        return _fail_open(title, description)

    if not rsp or rsp.get("error"):
        logger.warning(f"[planner] LLM returned error: {rsp.get('error') if rsp else 'no response'}")
        return _fail_open(title, description)

    raw = (rsp.get("content") or "").strip()
    try:
        data = json.loads(_strip_json(raw))
    except Exception as e:
        logger.warning(f"[planner] JSON parse failed: {e}; raw={raw[:200]}")
        return _fail_open(title, description)

    try:
        steps_in = data.get("steps") or []
        steps = [
            PlanStep(
                no=int(s.get("no") or i + 1),
                title=str(s.get("title") or "").strip()[:120],
                detail=str(s.get("detail") or "").strip()[:300],
                role=str(s.get("role") or "").strip().lower()[:30],
                estimate_min=max(1, min(int(s.get("estimate_min") or 10), 480)),
            )
            for i, s in enumerate(steps_in)
            if isinstance(s, dict) and s.get("title")
        ][:8]
        if not steps:
            return _fail_open(title, description)
        plan = ExecutionPlan(
            title=str(data.get("title") or title)[:200],
            summary=str(data.get("summary") or "")[:600],
            steps=steps,
            template=str(data.get("template") or "full").strip().lower()[:30],
            deploy_target=str(data.get("deploy_target") or "vercel").strip().lower()[:30],
            risks=[str(r).strip()[:200] for r in (data.get("risks") or []) if r][:3],
            estimate_min_total=int(data.get("estimate_min_total") or sum(s.estimate_min for s in steps)),
            confidence=str(data.get("confidence") or "medium").strip().lower()[:10],
        )
        return plan
    except Exception as e:
        logger.warning(f"[planner] JSON normalization failed: {e}")
        return _fail_open(title, description)


def format_plan_for_im(plan: ExecutionPlan) -> str:
    """Render a plan as IM-friendly text (works for Feishu card lines and QQ text)."""
    lines: List[str] = []
    lines.append(f"📋 项目计划：{plan.title}")
    if plan.summary:
        lines.append("")
        lines.append(plan.summary)
    lines.append("")
    lines.append(f"模板：{plan.template} ｜ 部署：{plan.deploy_target} ｜ 信心：{plan.confidence}")
    if plan.estimate_min_total:
        h = plan.estimate_min_total // 60
        m = plan.estimate_min_total % 60
        eta = f"{h}h{m}m" if h else f"{m}m"
        lines.append(f"预估：约 {eta}（{len(plan.steps)} 步）")
    lines.append("")
    lines.append("步骤：")
    for s in plan.steps:
        role_part = f" [{s.role}]" if s.role else ""
        eta_part = f" ({s.estimate_min}m)" if s.estimate_min else ""
        lines.append(f"{s.no}. {s.title}{role_part}{eta_part}")
        if s.detail:
            lines.append(f"   - {s.detail}")
    if plan.risks:
        lines.append("")
        lines.append("风险：")
        for r in plan.risks:
            lines.append(f"⚠ {r}")
    lines.append("")
    lines.append("回复「开干」或「approve」 → 立即执行")
    lines.append("回复「修改：xxx」 → 调整方案")
    lines.append("回复「取消」 → 放弃此次")
    return "\n".join(lines)
