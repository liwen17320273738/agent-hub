"""Requirement clarifier — decide if we have enough info to start an e2e run.

Given the user's accumulated messages, asks an LLM:
  - Is the requirement specific enough to design + build + deploy?
  - If not, what 1-3 short follow-up questions should we ask?
  - What's a clean refined description we can hand to the planner?

Returns a strict JSON shape so the gateway can route deterministically.

Fail-open: if the LLM call errors out OR returns garbage OR no API key
is configured, we treat the requirement as `sufficient=True` and let the
existing pipeline run — never block the user on infra issues.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..config import settings
from .llm_router import chat_completion

logger = logging.getLogger(__name__)


@dataclass
class ClarifierResult:
    sufficient: bool
    questions: List[str] = field(default_factory=list)
    refined_title: str = ""
    refined_description: str = ""
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sufficient": self.sufficient,
            "questions": self.questions,
            "refinedTitle": self.refined_title,
            "refinedDescription": self.refined_description,
            "rationale": self.rationale,
        }


_SYSTEM_PROMPT = """你是软件项目需求的"项目经理预判官"。

输入是用户在 IM 里发的若干条需求消息（可能是初次描述或后续补充）。
你要判断这些消息合起来是否足够让一个"架构师 + 开发 + QA + 部署"的自动化流水线
直接生成一个可上线的项目，**不再需要任何问询**。

判定"充分"的最低门槛（必须同时满足）：
1. **目标形态明确**：是 web 应用 / 小程序 / 后端 API / CLI / 数据脚本 / 其它？
2. **核心功能清晰**：列出至少 1-3 个具体的用户操作或核心场景。
3. **关键边界已知**：是否需要登录？是否要持久化数据？是否需要外部接口？
   （任意一项不需要的，用户可显式说"不需要"也算明确）

如果不充分，至多生成 3 条**最关键、最简短**的反问问题。问题要：
- 一句话、聚焦一个点
- 给出 2-4 个常见选项让用户挑（用 / 分隔）
- 中文，礼貌

输出严格 JSON，不要任何额外文字、不要 markdown：
{
  "sufficient": true | false,
  "questions": ["...", "..."],          // sufficient=true 时为空数组
  "refined_title": "≤30 字的项目标题",
  "refined_description": "整理后的需求描述，包含目标形态/核心功能/关键边界",
  "rationale": "一句话说明为什么充分或不充分"
}
"""


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _extract_json(text: str) -> Dict[str, Any]:
    cleaned = _CODE_FENCE_RE.sub("", (text or "").strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        raise


def _fail_open(messages: List[str], reason: str) -> ClarifierResult:
    """Return a 'sufficient=True' result so the pipeline still runs."""
    description = "\n\n".join(messages) if messages else ""
    title = (messages[0] if messages else "").strip()[:50] or "未命名任务"
    return ClarifierResult(
        sufficient=True,
        refined_title=title,
        refined_description=description,
        rationale=f"clarifier_fail_open: {reason}",
    )


async def assess(messages: List[str]) -> ClarifierResult:
    """Ask the LLM whether `messages` (in order) form a buildable requirement."""
    cleaned = [m.strip() for m in messages if m and m.strip()]
    if not cleaned:
        return ClarifierResult(sufficient=False, questions=["请描述一下你想做的项目"],
                               rationale="empty_input")

    keys = settings.get_provider_keys()
    if not keys:
        logger.info("[clarifier] no API key configured, fail-open")
        return _fail_open(cleaned, "no_api_key")

    user_block_lines = []
    for i, m in enumerate(cleaned, start=1):
        prefix = "初始需求" if i == 1 else f"补充 {i - 1}"
        user_block_lines.append(f"【{prefix}】\n{m}")
    user_block = "\n\n".join(user_block_lines)

    try:
        resp = await chat_completion(
            model=settings.llm_model or "deepseek-chat",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_block},
            ],
            temperature=0.1,
            max_tokens=900,
        )
    except Exception as e:
        logger.warning(f"[clarifier] LLM call failed: {e}")
        return _fail_open(cleaned, "llm_exception")

    if "error" in resp:
        logger.warning(f"[clarifier] LLM returned error: {resp.get('error')}")
        return _fail_open(cleaned, "llm_error")

    content = resp.get("content", "")
    try:
        parsed = _extract_json(content)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"[clarifier] cannot parse JSON ({e}): {content[:200]!r}")
        return _fail_open(cleaned, "parse_error")

    sufficient = bool(parsed.get("sufficient"))
    questions = parsed.get("questions") or []
    if not isinstance(questions, list):
        questions = []
    questions = [str(q).strip() for q in questions if str(q).strip()][:3]

    refined_title = str(parsed.get("refined_title") or "").strip()[:80]
    refined_description = str(parsed.get("refined_description") or "").strip()
    if not refined_description:
        refined_description = "\n\n".join(cleaned)
    if not refined_title:
        refined_title = cleaned[0][:50] or "未命名任务"

    return ClarifierResult(
        sufficient=sufficient,
        questions=[] if sufficient else questions,
        refined_title=refined_title,
        refined_description=refined_description,
        rationale=str(parsed.get("rationale") or ""),
    )


def format_questions_for_im(questions: List[str], hint: str = "") -> str:
    """Render a friendly multi-line message asking the follow-up questions."""
    if not questions:
        return "请补充一下需求细节"
    lines = ["在开工之前，我想先确认几点："]
    for i, q in enumerate(questions, start=1):
        lines.append(f"{i}. {q}")
    if hint:
        lines.append("")
        lines.append(hint)
    else:
        lines.append("")
        lines.append("回复任意一段补充说明即可，回答完我就开始干活。")
    return "\n".join(lines)
