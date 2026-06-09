"""
Stage Layers — layer helper functions extracted from pipeline_engine.py.

Each function implements one or more maturation layers (self-verify, review,
memory enrichment, parallel reviews, etc.).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional, Dict, Any, List, Tuple

from agent_hub_pipeline import (
    STAGE_MIN_OUTPUT_HINTS,
    verify_worktree_code_quality,
)
from sqlalchemy.ext.asyncio import AsyncSession

from .self_verify import (
    VerifyResult,
    VerifyStatus,
    StageVerification,
    verify_stage_output,
    llm_content_quality_check,
)
from .cross_stage_verify import verify_cross_stage
from .llm_router import chat_completion_with_fallback as llm_chat_with_fallback
from .sse import emit_event, emit_synthetic_output_stream
from .stage_constants import (
    AGENT_PROFILES,
    STAGE_ROLE_PROMPTS,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════
# 1. _top_up_stage_output
# ══════════════════════════════════════════════════════════════════════════

async def _top_up_stage_output(
    *,
    stage_id: str,
    model: str,
    api_url: str,
    system_prompt: str,
    partial_content: str,
    repair_feedback: str = "",
) -> str:
    required = {
        "planning": "## 目标用户\n## 功能范围\n## 用户故事\n## 验收标准\n## 非功能需求\n## 里程碑计划",
        "design": "## 设计原则\n## 设计 Token\n## 核心页面布局\n## 组件清单\n## 交互流程\n## 无障碍",
        "architecture": "## 系统架构\n## 数据模型\n## API 设计\n## 前端架构\n## 实现路线图\n## 风险与降级\n## 文件清单",
        "development": "## 项目结构\n## 核心代码\n## 数据库\n## API 实现\n## 前端实现\n## 配置文件\n## 开发说明",
        "testing": "## 测试范围\n## 测试矩阵\n## 测试用例\n## 边界分析\n## 安全审查\n## 性能预估\n## 结论",
        "reviewing": "## 评估\n## 验收结论\n## 关键证据\n## 风险与建议",
    }.get(stage_id, "缺失章节")

    prompt = (
        "你上一条阶段产出明显过短或被截断了。"
        "不要重复已有内容，请从中断处继续，补齐缺失章节，并返回完整的剩余正文。\n\n"
        f"## 当前阶段\n{stage_id}\n"
        "## 必须使用的精确 Markdown 标题\n"
        f"{required}\n\n"
        f"## 修复要求\n{repair_feedback or '优先补齐缺失章节并确保文档完整，不要停在半句或半张表。'}\n\n"
        "## 已生成内容（不要原样重复）\n"
        f"{partial_content[-3000:]}\n\n"
        "请继续输出缺失内容，直到该阶段文档完整可交付。"
    )
    result = await llm_chat_with_fallback(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        api_url=api_url,
        max_tokens=8192,
    )
    extra = (result.get("content") or "").strip()
    if not extra:
        return partial_content
    if extra in partial_content:
        return partial_content
    return f"{partial_content.rstrip()}\n\n{extra}".strip()

# ══════════════════════════════════════════════════════════════════════════
# 2. review_stage_output
# ══════════════════════════════════════════════════════════════════════════

STAGE_REVIEW_CONFIG: Dict[str, Dict[str, Any]] = {
    "planning": {
        "reviewer_agent": "architect-agent",
        "reviewer_prompt": """## 评审任务：PRD（产品需求文档）

你以【架构师 Agent】的身份独立审阅 CEO Agent 产出的 PRD。

请严格按照以下框架逐项评估，每条发现必须标注来源行或原文引用：

### 1. 需求完整性审查
| # | 检查项 | 结果(PASS/FAIL/N/A) | 具体引用与说明 |
|---|--------|---------------------|--------------|
| 1 | 一句话价值主张是否 ≤30 字 | | |
| 2 | 目标用户是否有画像 | | |
| 3 | 功能范围是否区分 IN/OUT/FUTURE | | |
| 4 | 用户故事是否 ≥5 条且含验收标准 | | |
| 5 | 非功能需求是否含性能指标(TPS/P99 等) | | |
| 6 | 里程碑是否标注 P0/P1/P2 | | |
| 7 | 是否包含风险评估 | | |

### 2. 技术可行性评估
- 技术约束是否合理、可实现？
- 是否有遗漏的关键技术需求（如第三方依赖、部署环境约束）？
- 里程碑时间是否与实现复杂度匹配？

### 3. 质量缺陷清单
列出所有发现的缺陷，每行一条，格式：
> **[级别/P0|P1|P2]** 问题描述 — 建议修改

### 4. 结论（第一行，必须严格按以下格式之一）
- **APPROVE** — PRD 质量合格，可以开始架构设计
- **REJECT** — 需要修改（列出具体问题和修改建议）""",
        "human_gate": False,
    },
    "design": {
        "reviewer_agent": "product-agent",
        "reviewer_prompt": """## 评审任务：UI/UX 设计规范

你以【产品经理 Agent】的身份独立审阅设计 Agent 产出的设计规范。

请严格按照以下框架逐项评估：

### 1. 设计合规性审查
| # | 检查项 | 结果(PASS/FAIL/N/A) | 具体引用与说明 |
|---|--------|---------------------|--------------|
| 1 | 设计是否覆盖 PRD 全部核心用户故事 | | |
| 2 | 至少 3 个关键页面有具体布局 | | |
| 3 | 每个页面是否包含至少 5 种状态(hover/active/disabled/loading/empty/error) | | |
| 4 | 设计 Token 是否表格化（颜色/字号/间距/圆角/阴影） | | |
| 5 | 组件清单是否有变体、尺寸、状态定义 | | |
| 6 | 是否说明了响应式断点行为 | | |
| 7 | 是否说明了无障碍(a11y)考量 | | |

### 2. 交付可行性评估
- 所有数值是否给具体值（非"看情况调整"）？
- 开发 Agent 是否能基于此规范直接编码？
- 是否包含交互流程（主链路用户路径+每步反馈）？

### 3. 质量缺陷清单
每行一条：
> **[级别/P0|P1|P2]** 问题描述 — 建议修改

### 4. 结论（第一行，必须严格按以下格式之一）
- **APPROVE** — 设计规范完整，开发可据此动工
- **REJECT** — 缺关键页面或规范不足（列出具体问题）""",
        "human_gate": False,
    },
    "architecture": {
        "reviewer_agent": "developer-agent",
        "reviewer_prompt": """## 评审任务：技术架构方案

你以【开发 Agent】的身份独立审阅架构师 Agent 产出的技术方案。

请严格按照以下框架逐项评估：

### 1. 架构完整性审查
| # | 检查项 | 结果(PASS/FAIL/N/A) | 具体引用与说明 |
|---|--------|---------------------|--------------|
| 1 | 技术选型有明确理由和备选对比 | | |
| 2 | 系统架构图含前端/后端/数据/缓存/消息 | | |
| 3 | 数据模型有 ER 图和核心表字段 | | |
| 4 | API 路由表含 Method+Path+描述+请求/响应示例 | | |
| 5 | 前端架构含页面树/路由表/状态管理 | | |
| 6 | 实现路线图有工时预估和依赖关系 | | |
| 7 | 风险与降级方案完整 | | |
| 8 | 文件清单明确 | | |

### 2. 可行性评估
- API 设计是否完整、无歧义（每个端点是否明确输入输出）？
- 数据模型是否合理、查询性能可接受？
- 技术选型是否成熟稳定、团队是否掌握？
- 是否有模糊不清的设计决策需要澄清？

### 3. 质量缺陷清单
每行一条：
> **[级别/P0|P1|P2]** 问题描述 — 建议修改

### 4. 结论（第一行，必须严格按以下格式之一）
- **APPROVE** — 技术方案可行，可以开始开发
- **REJECT** — 需要修改（列出具体问题和修改建议）""",
        "human_gate": False,
    },
    "development": {
        "reviewer_agent": "qa-agent",
        "reviewer_prompt": """## 评审任务：代码实现

你以【测试 Agent】的身份独立审阅开发 Agent 产出的代码实现。

请严格按照以下框架逐项评估：

### 1. 代码质量审查
| # | 检查项 | 结果(PASS/FAIL/N/A) | 具体文件与行号 |
|---|--------|---------------------|---------------|
| 1 | 代码覆盖 PRD 全部 P0 用户故事 | | |
| 2 | 主要函数有类型注解 | | |
| 3 | 错误处理覆盖了主要异常路径 | | |
| 4 | 边界情况（空数据、并发、极限值）有处理 | | |
| 5 | 无明显的 SQL 注入/XSS/敏感数据泄露 | | |
| 6 | 无硬编码密钥或敏感信息 | | |
| 7 | 代码结构清晰、职责单一 | | |

### 2. 可测试性评估
- 核心逻辑是否可以单元测试（是否依赖注入/接口抽象）？
- 是否有测试脚手架（test 目录、配置文件）？

### 3. 质量缺陷清单
每行一条，涉及代码必须标注文件路径和大致行号：
> **[级别/P0|P1|P2]** 问题描述 — 文件路径 — 建议修改

### 4. 结论（第一行，必须严格按以下格式之一）
- **APPROVE** — 代码质量可接受，可以进入正式测试
- **REJECT** — 需要修改（列出具体问题和修改建议）""",
        "human_gate": False,
    },
    "testing": {
        "reviewer_agent": "acceptance-agent",
        "reviewer_prompt": """## 评审任务：测试报告

你以【验收官 Agent】的身份独立审阅测试 Agent 的测试报告。

请严格按照以下框架逐项评估：

### 1. 测试充分性审查
| # | 检查项 | 结果(PASS/FAIL/N/A) | 具体引用与说明 |
|---|--------|---------------------|--------------|
| 1 | 测试是否覆盖 PRD 全部用户故事 | | |
| 2 | 核心功能是否有正向+逆向测试用例 | | |
| 3 | 是否有边界测试（空/极限/并发） | | |
| 4 | 是否有安全审查（SQLi/XSS 等） | | |
| 5 | 测试是否真实执行（非 Mock 过场） | | |
| 6 | 通过率是否 ≥ 90% | | |

### 2. 缺陷严重度评估
- 未修复的 P0/P1 缺陷有哪些？
- 这些缺陷是否影响核心用户链路？
- 是否存在"测试通过但核心功能不可用"的风险？

### 3. 质量缺陷清单
每行一条：
> **[级别/P0|P1|P2]** 问题描述 — 建议修改或指明退回阶段

### 4. 结论（第一行，必须严格按以下格式之一）
- **APPROVE** — 测试通过，可以进入最终验收
- **REJECT** — 需要修改（列出具体问题，指明退回到哪个阶段）""",
        "human_gate": False,
    },
    "reviewing": {
        # The reviewing stage itself runs the acceptance-agent (see
        # STAGE_ROLE_PROMPTS["reviewing"]); the post-stage peer-review here
        # is a CEO sanity check. human_gate=False so auto pipeline can finish
        # deployment without blocking on manual approval (issuse23).
        "reviewer_agent": "ceo-agent",
        "reviewer_prompt": """## 评审任务：最终验收报告

你以【CEO Agent】的身份做最终上线前 Go/No-Go 决策。

1. **验收报告结论确认** — 验收官是否明确给出了 APPROVED/REJECTED？
2. **证据充分性** — 验收官是否调用了至少一个工具（截图/测试/代码搜索）获取证据？
3. **风险清单** — 即使 APPROVED，遗留风险是否都已记录？
4. **上线准备** — 是否有监控指标、回滚条件、灰度建议？

### 质量缺陷清单
每行一条：
> **[级别/P0|P1|P2]** 问题描述

### 结论（第一行，必须严格按以下格式之一）
- **APPROVE** — 同意验收结论，进入部署/人工最终批准
- **REJECT** — 验收证据不充分，要求验收官补做（列出具体问题）""",
        "human_gate": False,
    },
    "deployment": {
        "reviewer_agent": None,
        "reviewer_prompt": "",
        "human_gate": False,
    },
    "security-review": {
        "reviewer_agent": "architect-agent",
        "reviewer_prompt": """## 评审任务：安全审计报告

你以【架构师 Agent】的身份独立审阅。

| # | 检查项 | 结果(PASS/FAIL/N/A) | 说明 |
|---|--------|---------------------|------|
| 1 | 安全审计覆盖所有关键模块 | | |
| 2 | 修复建议技术上可执行 | | |
| 3 | 是否遗漏架构层纵深防御 | | |

### 质量缺陷清单
每行一条：
> **[级别/P0|P1|P2]** 问题描述

第一行：APPROVE / REJECT。
""",
        "human_gate": False,
    },
    "legal-review": {
        "reviewer_agent": "ceo-agent",
        "reviewer_prompt": """## 评审任务：合规审查报告

你以【CEO Agent】的身份独立审阅。

| # | 检查项 | 结果(PASS/FAIL/N/A) | 说明 |
|---|--------|---------------------|------|
| 1 | 法律风险评级是否合理 | | |
| 2 | 业务上能否接受 CONDITIONAL 限制 | | |
| 3 | 是否需要调整 PRD 范围以满足合规 | | |

### 质量缺陷清单
每行一条：
> **[级别/P0|P1|P2]** 问题描述

第一行：APPROVE / REJECT。
""",
        "human_gate": True,
    },
    "data-modeling": {
        "reviewer_agent": "product-agent",
        "reviewer_prompt": """## 评审任务：数据指标方案

你以【产品经理 Agent】的身份独立审阅。

| # | 检查项 | 结果(PASS/FAIL/N/A) | 说明 |
|---|--------|---------------------|------|
| 1 | 北极星指标是否反映北极星目标 | | |
| 2 | 埋点覆盖 PRD 全部用户故事 | | |
| 3 | 报表能驱动后续迭代决策 | | |

### 质量缺陷清单
每行一条：
> **[级别/P0|P1|P2]** 问题描述

第一行：APPROVE / REJECT。
""",
        "human_gate": False,
    },
    "marketing-launch": {
        "reviewer_agent": "ceo-agent",
        "reviewer_prompt": """## 评审任务：上线营销包

你以【CEO Agent】的身份独立审阅。

| # | 检查项 | 结果(PASS/FAIL/N/A) | 说明 |
|---|--------|---------------------|------|
| 1 | 渠道与预算分配合理 | | |
| 2 | 文案准确传达产品价值 | | |
| 3 | 节奏与 KPI 可执行 | | |

### 质量缺陷清单
每行一条：
> **[级别/P0|P1|P2]** 问题描述

第一行：APPROVE / REJECT。
""",
        "human_gate": False,
    },
    "finance-review": {
        "reviewer_agent": "ceo-agent",
        "reviewer_prompt": """## 评审任务：商业可持续性评估

你以【CEO Agent】的身份独立审阅。

| # | 检查项 | 结果(PASS/FAIL/N/A) | 说明 |
|---|--------|---------------------|------|
| 1 | 成本估算反映真实算力/带宽/LLM 用量 | | |
| 2 | 单位经济健康 | | |
| 3 | 风险点需在 PRD 阶段裁掉 | | |

### 质量缺陷清单
每行一条：
> **[级别/P0|P1|P2]** 问题描述

第一行：APPROVE / REJECT。
""",
        "human_gate": True,
    },
}
MAX_REVIEW_RETRIES = 2


def _parse_review_verdict(review_content: str) -> bool:
    """Decide APPROVE/REJECT from a reviewer's free-form output.

    Reviewer prompts are inconsistent about where the verdict lives: some put
    it on the first line, others in a "### 结论" section at the very end. A
    naive first-line check therefore false-rejects every section-style review
    (the first line is just a markdown header). We scan from the bottom up and
    return the first line that decisively carries exactly one of the two
    verdict tokens — that is the conclusion. No clear verdict → not approved.
    """
    lines = [ln.strip() for ln in (review_content or "").splitlines() if ln.strip()]
    for ln in reversed(lines):
        upper = ln.upper()
        has_approve = "APPROVE" in upper
        has_reject = "REJECT" in upper
        if has_approve != has_reject:
            return has_approve
    return False


async def review_stage_output(
    db: AsyncSession,
    *,
    task_id: str,
    stage_id: str,
    stage_output: str,
    task_title: str,
    task_description: str,
    previous_outputs: Optional[Dict[str, str]] = None,
    injected_override_id: Optional[str] = None,
    injected_override_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run a peer review on a completed stage's output.
    The reviewer agent evaluates and returns APPROVE or REJECT with feedback.
    """
    review_config = STAGE_REVIEW_CONFIG.get(stage_id)
    if not review_config or not review_config.get("reviewer_agent"):
        return {"reviewed": False, "approved": True, "reason": "No peer review configured"}

    reviewer_key = review_config["reviewer_agent"]
    reviewer_profile = AGENT_PROFILES.get(reviewer_key, {})
    reviewer_name = reviewer_profile.get("name", reviewer_key)
    reviewer_icon = reviewer_profile.get("icon", "🔍")

    await emit_event("stage:peer-reviewing", {
        "taskId": task_id,
        "stageId": stage_id,
        "reviewer": reviewer_name,
        "reviewerIcon": reviewer_icon,
        "label": f"{reviewer_icon} {reviewer_name} 正在审阅「{stage_id}」阶段产出...",
    })

    review_system = review_config["reviewer_prompt"]
    stage_label_map = {
        "planning": "PRD（产品需求文档）",
        "design": "UI/UX 设计规范",
        "architecture": "技术架构方案",
        "development": "代码实现",
        "testing": "测试报告",
        "reviewing": "验收评审",
        "deployment": "部署方案",
        "acceptance": "最终验收",
        "security-review": "安全审计报告",
        "legal-review": "法务/合规审查",
    }
    stage_label = stage_label_map.get(stage_id, stage_id)

    review_user = f"## 待审阅内容：{stage_label}\n\n{stage_output}"
    if previous_outputs:
        context_parts = []
        for sid, out in previous_outputs.items():
            if sid != stage_id and out:
                lbl = stage_label_map.get(sid, sid)
                context_parts.append(f"## 前置阶段 — {lbl}\n{out[:4000]}")
        if context_parts:
            review_user = "\n\n".join(context_parts) + "\n\n" + review_user

    try:
        from ..config import settings as app_settings
        model = app_settings.llm_model or "deepseek-chat"
        api_url = app_settings.llm_api_url or ""

        messages = [
            {"role": "system", "content": review_system},
            {"role": "user", "content": review_user},
        ]

        async def _on_review_fallback(payload: Dict[str, Any]) -> None:
            await emit_event("stage:provider-fallback", {
                "taskId": task_id,
                "stageId": stage_id,
                "agent": reviewer_name,
                "phase": "peer_review",
                **payload,
            })

        llm_result = await llm_chat_with_fallback(
            model=model, messages=messages, api_url=api_url,
            on_fallback=_on_review_fallback,
        )
        if llm_result.get("error"):
            raise RuntimeError(f"LLM error: {llm_result['error']}")

        review_content = llm_result.get("content", "")
    except Exception as e:
        logger.error(f"[pipeline] Peer review for {stage_id} failed: {e}")
        await emit_event("stage:peer-review-error", {
            "taskId": task_id, "stageId": stage_id,
            "reviewer": reviewer_name, "error": str(e),
            "label": f"⚠️ {reviewer_name} 审阅异常（{e}），标记为未通过需人工复查",
        })
        return {
            "reviewed": False,
            "approved": False,
            "auto_approved_on_error": False,
            "reason": f"Review error (not approved): {e}",
        }

    approved = _parse_review_verdict(review_content)

    if approved:
        await emit_event("stage:peer-review-approved", {
            "taskId": task_id, "stageId": stage_id,
            "reviewer": reviewer_name, "reviewerIcon": reviewer_icon,
        })
    else:
        await emit_event("stage:peer-review-rejected", {
            "taskId": task_id, "stageId": stage_id,
            "reviewer": reviewer_name, "reviewerIcon": reviewer_icon,
            "feedback": review_content[:500],
        })

    # ── Learning loop — capture outcome + bump injected override impact ───
    #
    # Critical for A/B shadow correctness: we MUST attribute the outcome
    # to the override that was actually injected at LLM time, not re-roll
    # the traffic split here. The caller passes `injected_override_id`.
    try:
        from .learning_loop import capture_signal, record_override_outcome

        stage_role = STAGE_ROLE_PROMPTS.get(stage_id, {}).get("role", "")

        if injected_override_id:
            await record_override_outcome(
                db, override_id=injected_override_id, approved=approved,
            )

        if not approved:
            await capture_signal(
                db, task_id=task_id, stage_id=stage_id, role=stage_role,
                signal_type="REJECT", severity="warn",
                reviewer=reviewer_key, reviewer_feedback=review_content,
                output_excerpt=stage_output,
            )
        elif injected_override_id:
            # approving a stage that DID use a learned addendum is positive evidence
            await capture_signal(
                db, task_id=task_id, stage_id=stage_id, role=stage_role,
                signal_type="APPROVE_AFTER_RETRY", severity="info",
                reviewer=reviewer_key, reviewer_feedback=review_content,
                metadata={
                    "override_id": injected_override_id,
                    "override_mode": injected_override_mode or "active",
                },
            )
    except Exception as exc:
        logger.debug("[learning] signal capture failed for %s: %s", stage_id, exc)

    return {
        "reviewed": True,
        "approved": approved,
        "reviewer": reviewer_name,
        "reviewer_agent": reviewer_key,
        "feedback": review_content,
        "reason": "Approved by peer" if approved else "Rejected by peer reviewer",
    }

# ══════════════════════════════════════════════════════════════════════════
# 3. _run_stage_verification
# ══════════════════════════════════════════════════════════════════════════

async def _run_stage_verification(
    *,
    stage_id: str,
    role: str,
    task_id: str,
    content: str,
    previous_outputs: Dict[str, str],
    task_worktree: Optional[str],
    tier: str,
    resolved_provider: str,
    model: str,
    system_prompt: str,
    cc_written_files: List[str],
    skip_llm_for_dev: bool = False,
) -> tuple[str, StageVerification]:
    """阶段后置验证：自验证 + 并行评审 + 交叉验证 + worktree quality + top-up 修复。"""
    from ..config import settings as app_settings

    verification = verify_stage_output(
        stage_id=stage_id,
        role=role,
        output=content,
        previous_outputs=previous_outputs,
    )

    # Optional LLM content quality filter (async, fast, cheap model)
    llm_check = await llm_content_quality_check(stage_id, content, previous_outputs)
    if llm_check:
        verification.checks.append(llm_check)
        if llm_check.status == VerifyStatus.WARN and verification.overall_status != VerifyStatus.FAIL:
            verification.overall_status = VerifyStatus.WARN

    # Parallel review broadcast (advisory, non-blocking)
    if stage_id in _PARALLEL_REVIEW_CONFIG:
        try:
            parallel_feedback = await _run_parallel_reviews(task_id, stage_id, content)
            if parallel_feedback:
                feedback_lines = [
                    f"### 并行评审意见 — {fb['role']}\n{fb['feedback']}"
                    for fb in parallel_feedback
                ]
                parallel_section = "\n\n".join(feedback_lines)
                content += f"\n\n---\n\n## 并行评审反馈\n\n{parallel_section}"
                await emit_event("stage:parallel-review", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "reviewCount": len(parallel_feedback),
                    "reviewers": [fb["role"] for fb in parallel_feedback],
                })
        except Exception as e:
            logger.warning("[pipeline] parallel review failed for %s: %s", stage_id, e)

    # Cross-Stage Consistency Verification
    if previous_outputs:
        try:
            cross_results = await verify_cross_stage(
                stage_id=stage_id,
                output=content,
                previous_outputs=previous_outputs,
            )
            _critical_cross_stages = {"development", "testing"}
            for cr in cross_results:
                verification.checks.append(cr)
                if cr.status == VerifyStatus.FAIL:
                    target = VerifyStatus.FAIL if stage_id in _critical_cross_stages else VerifyStatus.WARN
                    verification.overall_status = max(
                        verification.overall_status, target,
                        key=lambda s: {"pass": 0, "warn": 1, "fail": 2}[s.value],
                    )
                elif cr.status == VerifyStatus.WARN:
                    verification.overall_status = max(
                        verification.overall_status, VerifyStatus.WARN,
                        key=lambda s: {"pass": 0, "warn": 1, "fail": 2}[s.value],
                    )
            if cross_results:
                await emit_event("stage:cross-verify", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "checkCount": len(cross_results),
                })
        except Exception as e:
            logger.warning("[pipeline] cross-stage verification failed for %s: %s", stage_id, e)

    # For development stage with Claude Code output, override verification
    if stage_id == "development" and skip_llm_for_dev and task_worktree:
        wt_report = verify_worktree_code_quality(task_worktree)
        if wt_report:
            cross_stage_checks = [
                c for c in verification.checks
                if getattr(c, "check_name", "").startswith("cross_stage:")
            ]
            verification = StageVerification(
                stage_id=stage_id,
                role=role,
                overall_status=VerifyStatus(wt_report.overall_status),
                checks=[
                    VerifyResult(
                        check_name=c.check_name,
                        status=VerifyStatus(c.status),
                        message=c.message,
                    )
                    for c in wt_report.checks
                ] + cross_stage_checks,
                auto_proceed=wt_report.auto_proceed,
                suggestions=wt_report.suggestions,
            )
            for csc in cross_stage_checks:
                if csc.status == VerifyStatus.FAIL:
                    verification.overall_status = max(
                        verification.overall_status, VerifyStatus.FAIL,
                        key=lambda s: {"pass": 0, "warn": 1, "fail": 2}[s.value],
                    )
                elif csc.status == VerifyStatus.WARN:
                    verification.overall_status = max(
                        verification.overall_status, VerifyStatus.WARN,
                        key=lambda s: {"pass": 0, "warn": 1, "fail": 2}[s.value],
                    )
            logger.info(
                "[pipeline] development stage quality override: %s (score inferred from %d files, %d cross-stage checks preserved)",
                verification.overall_status.value,
                len(cc_written_files),
                len(cross_stage_checks),
            )

    # Top-up repair for local tier
    if (tier == "local" or resolved_provider == "local") and verification.overall_status == VerifyStatus.FAIL:
        api_url = app_settings.llm_api_url or ""
        if api_url and stage_id in STAGE_MIN_OUTPUT_HINTS:
            repair_feedback = "; ".join(
                c.message for c in verification.checks
                if getattr(c, "status", None) == VerifyStatus.FAIL
            )
            try:
                repaired = await _top_up_stage_output(
                    stage_id=stage_id,
                    model=model,
                    api_url=api_url,
                    system_prompt=system_prompt,
                    partial_content=content,
                    repair_feedback=repair_feedback,
                )
                if repaired != content:
                    content = repaired
                    verification = verify_stage_output(
                        stage_id=stage_id,
                        role=role,
                        output=content,
                        previous_outputs=previous_outputs,
                    )
                    # 修复后重新运行交叉验证
                    if previous_outputs:
                        try:
                            cross_results = await verify_cross_stage(
                                stage_id=stage_id,
                                output=content,
                                previous_outputs=previous_outputs,
                            )
                            _critical_cross_stages_2 = {"development", "testing"}
                            for cr in cross_results:
                                verification.checks.append(cr)
                                if cr.status == VerifyStatus.FAIL:
                                    target2 = VerifyStatus.FAIL if stage_id in _critical_cross_stages_2 else VerifyStatus.WARN
                                    verification.overall_status = max(
                                        verification.overall_status, target2,
                                        key=lambda s: {"pass": 0, "warn": 1, "fail": 2}[s.value],
                                    )
                                elif cr.status == VerifyStatus.WARN:
                                    verification.overall_status = max(
                                        verification.overall_status, VerifyStatus.WARN,
                                        key=lambda s: {"pass": 0, "warn": 1, "fail": 2}[s.value],
                                    )
                        except Exception as top_up_cross_err:
                            logger.warning("[pipeline] top-up cross-stage verify failed for %s: %s", stage_id, top_up_cross_err)
            except Exception as top_up_err:
                logger.warning(
                    "[pipeline] Stage %s repair top-up failed: %s",
                    stage_id, top_up_err,
                )

    return content, verification

# ══════════════════════════════════════════════════════════════════════════
# 4. _stream_stage_output
# ══════════════════════════════════════════════════════════════════════════

async def _stream_stage_output(
    *,
    task_id: Any,
    stage_id: str,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int = 4096,
    api_url: str = "",
    image_attachments: Optional[List[Tuple[str, str]]] = None,
) -> Dict[str, Any]:
    """Stream LLM output token-by-token through SSE, then return accumulated result.

    Emits ``stage:output-chunk`` for each text delta so the frontend can show
    real-time agent output like Codex / Claude Code.

    Falls back to non-streaming ``chat_completion_with_fallback`` if the
    streaming path fails for any reason.
    """
    from .llm_router import chat_completion_stream, chat_completion_with_fallback as llm_fb

    accumulated: List[str] = []
    pending_flush: List[str] = []
    chunk_count = 0
    stream_ok = False
    last_flush = time.monotonic()
    _BATCH_INTERVAL = 0.15  # flush to SSE every 150ms to avoid flooding

    async def _flush_pending() -> None:
        nonlocal last_flush
        if not pending_flush:
            return
        await emit_event("stage:output-chunk", {
            "taskId": task_id,
            "stageId": stage_id,
            "text": "".join(pending_flush),
            "chunkIndex": chunk_count,
        })
        pending_flush.clear()
        last_flush = time.monotonic()

    try:
        stream = chat_completion_stream(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            api_url=api_url,
            image_attachments=image_attachments,
        )

        # Emit thinking-start event so frontend shows agent is "writing"
        await emit_event("stage:output-start", {
            "taskId": task_id,
            "stageId": stage_id,
            "model": model,
        })

        async for sse_line in stream:
            line = sse_line.strip()
            if not line or not line.startswith("data:"):
                continue

            payload_str = line[5:].strip()
            if payload_str == "[DONE]":
                break

            try:
                payload = json.loads(payload_str)
            except json.JSONDecodeError:
                continue

            if "error" in payload:
                raise RuntimeError(payload["error"])

            text = payload.get("content", "")
            if text:
                accumulated.append(text)
                pending_flush.append(text)
                chunk_count += 1

                # Batch chunks to avoid flooding SSE/Redis
                now = time.monotonic()
                if now - last_flush >= _BATCH_INTERVAL or chunk_count <= 3:
                    await _flush_pending()

        await _flush_pending()
        stream_ok = True

    except Exception as stream_err:
        logger.warning(
            "[pipeline] Stream failed for %s/%s, falling back to non-streaming: %s",
            task_id, stage_id, stream_err,
        )

    content = "".join(accumulated)

    if stream_ok and content.strip():
        await emit_event("stage:output-end", {
            "taskId": task_id,
            "stageId": stage_id,
            "totalChunks": chunk_count,
            "length": len(content),
        })
        return {"content": content, "usage": {}, "streamed": True}

    # Fallback to non-streaming — still emit synthetic chunks so the UI is live
    logger.info("[pipeline] Using non-streaming fallback for %s/%s", task_id, stage_id)
    result = await llm_fb(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        api_url=api_url or "",
        image_attachments=image_attachments,
    )
    fallback_content = result.get("content", "") if isinstance(result, dict) else ""
    if fallback_content:
        await emit_synthetic_output_stream(
            task_id=task_id,
            stage_id=stage_id,
            content=fallback_content,
            model=model,
        )
        result["streamed"] = True
        result["synthetic_stream"] = True
    return result

# ══════════════════════════════════════════════════════════════════════════
# 5. _run_parallel_reviews (includes _run_parallel_reviews)
# ══════════════════════════════════════════════════════════════════════════

_PARALLEL_REVIEW_CONFIG: Dict[str, List[Dict[str, Any]]] = {
    "architecture": [
        {
            "role": "security",
            "task_hint": "审阅架构方案的安全性：JWT 配置、数据加密、网络隔离、最小权限。只列出你发现的安全问题，不要重新设计架构。",
        },
        {
            "role": "developer",
            "task_hint": "从开发实现角度审阅架构方案：API 设计是否完整？数据模型是否可实现？技术栈是否熟悉？列出 3 个最重要的顾虑。",
        },
    ],
    "design": [
        {
            "role": "developer",
            "task_hint": "审阅设计规范的可实现性：组件是否能用现有框架实现？状态覆盖是否完整？响应式方案是否可行？只列出可实现性问题。",
        },
    ],
    "development": [
        {
            "role": "qa",
            "task_hint": "审阅代码的可测试性：核心逻辑是否可单元测试？是否有测试脚手架？Mock 接口是否清晰？只列可测试性问题，不要写测试用例。",
        },
        {
            "role": "security",
            "task_hint": "审阅代码安全性：检查是否有 SQL 注入、XSS、敏感数据泄露、硬编码密钥、权限越界风险。只列出安全问题。",
        },
    ],
}


async def _run_parallel_reviews(
    task_id: str,
    stage_id: str,
    stage_output: str,
) -> List[Dict[str, str]]:
    """Broadcast stage output to parallel reviewers and aggregate feedback.

    Each reviewer runs via delegate_to_agent (agent_delegate.py).  This is
    NOT a blocking gate — feedback is advisory and attached to the stage
    metadata, not used for REJECT.  The peer review in STAGE_REVIEW_CONFIG
    remains the formal gate.

    Returns a list of dicts: [{"role": "security", "feedback": "..."}, ...]
    """
    config = _PARALLEL_REVIEW_CONFIG.get(stage_id, [])
    if not config:
        return []

    from .agent_delegate import delegate_to_agent

    tasks = []
    for reviewer in config:
        task_payload = {
            "role": reviewer["role"],
            "task": f"{reviewer['task_hint']}\n\n## 待审阅内容\n{stage_output[:4000]}",
            "max_steps": 2,
        }
        tasks.append(delegate_to_agent(task_payload))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    feedback: List[Dict[str, str]] = []
    for i, result in enumerate(results):
        role = config[i]["role"]
        if isinstance(result, Exception):
            logger.debug("[parallel_review] %s review failed: %s", role, result)
            continue
        if isinstance(result, str) and ("Error" not in result):
            feedback.append({"role": role, "feedback": result[:2000]})
        elif isinstance(result, str):
            logger.debug("[parallel_review] %s returned error: %s", role, result[:200])
    return feedback


# ══════════════════════════════════════════════════════════════════════════
# 6. _parse_reject_to
# ══════════════════════════════════════════════════════════════════════════

def _parse_reject_to(content: str) -> Optional[str]:
    """Parse REJECT_TO: <stage_id> from acceptance agent output."""
    import re
    match = re.search(r"REJECT(?:ED)?\s+REJECT_TO:\s*(\S+)", content, re.IGNORECASE)
    if match:
        return match.group(1).strip().lower()
    return None


# ══════════════════════════════════════════════════════════════════════════
# 7. _extract_reject_reason
# ══════════════════════════════════════════════════════════════════════════

def _extract_reject_reason(content: str) -> str:
    """Extract reject reason from acceptance output (lines after REJECTED)."""
    lines = content.splitlines()
    reason_lines = []
    collecting = False
    for line in lines:
        if "REJECT" in line.upper():
            collecting = True
            continue
        if collecting:
            if line.strip().startswith("#") and reason_lines:
                break
            reason_lines.append(line)
    return "\n".join(reason_lines).strip()[:4000] or "验收未通过，请修改后重新提交"


# ══════════════════════════════════════════════════════════════════════════
# 8. _build_user_message
# ══════════════════════════════════════════════════════════════════════════

def _build_user_message(
    title: str,
    description: str,
    stage_id: str,
    previous_outputs: Optional[Dict[str, str]],
) -> str:
    """Build the user message for an LLM call, including previous stage outputs."""
    parts = [f"## 需求标题\n{title}", f"## 需求描述\n{description or '(无详细描述)'}"]

    if previous_outputs:
        stage_label = {
            "planning": "PRD（产品需求文档）",
            "design": "UI/UX 设计规范",
            "architecture": "技术架构方案",
            "development": "开发实现产出",
            "testing": "测试验证报告",
            "reviewing": "审查验收报告",
            "deployment": "部署方案",
            "acceptance": "最终验收报告",
            "security-review": "安全审计报告",
            "legal-review": "法务审查报告",
        }
        # 统一的上下文截断长度：按阶段所需上下文量分级
        # 最终阶段需要完整上下文，核心产出阶段需要足够上下文理解前置输出
        if stage_id in ("reviewing", "deployment"):
            max_prev = 18_000   # 最终阶段：需要完整上下文
        elif stage_id in ("planning", "design", "architecture", "development", "testing"):
            max_prev = 12_000   # 核心交付阶段：前置产出通常较长（PRD/设计/代码）
        else:
            max_prev = 8_000    # 审查/其他阶段：需要上下文但不需要全部细节
        for sid, output in previous_outputs.items():
            if "_review_feedback" in sid or sid.endswith("_review_feedback"):
                continue
            label = stage_label.get(sid, sid)
            if output:
                trimmed = output[:max_prev]
                if len(output) > max_prev:
                    trimmed += "\n...(已截断，完整内容见上游阶段产出)"
                parts.append(f"## {label}\n{trimmed}")

    return "\n\n".join(parts)

# ══════════════════════════════════════════════════════════════════════════
# 9. _ruflo_memory_enrich
# ══════════════════════════════════════════════════════════════════════════

async def _ruflo_memory_enrich(
    task_id: str,
    stage_id: str,
    system_prompt: str,
    stage_content: str = "",
    store_output: bool = False,
    output_text: str = "",
) -> str:
    """Enrich the system prompt with Ruflo memory context.

    Called just before the LLM call to inject cross-session learnings.
    After successful stage completion, call again with ``store_output=True``
    to persist the output for future tasks.

    Returns the (possibly enriched) ``system_prompt``.
    """
    from ..config import settings as _s
    if not _s.ruflo_enabled or not _s.ruflo_pipeline_enrich:
        return system_prompt

    enriched = system_prompt
    try:
        from .mcp_bridge import get_bridge

        bridge = await get_bridge()

        # ── Store stage output for cross-session learning ──
        if store_output and output_text:
            mem_key = f"pipeline:{task_id}:{stage_id}:output"
            await bridge.memory_store(
                key=mem_key,
                value=output_text[:50_000],
                namespace="agent-hub-pipeline",
                metadata={"taskId": str(task_id), "stageId": stage_id},
                timeout=5.0,
            )
            logger.info("[ruflo] Stored memory: %s (%d chars)", mem_key, len(output_text))

        # ── Retrieve relevant prior memories ──
        if _s.ruflo_memory_enrich and stage_content:
            similar = await bridge.memory_search(
                query=stage_content[:500],
                namespace="agent-hub-pipeline",
                limit=5,
            )
            if similar:
                # Filter to relevant memories (different task)
                prior = [
                    s for s in similar
                    if isinstance(s, dict)
                    and s.get("namespace") == "agent-hub-pipeline"
                    and str(s.get("metadata", {}).get("taskId", "")) != str(task_id)
                ]
                if prior:
                    memories_text = "\n\n".join(
                        f"【历史任务参考】\n{s.get('value', '')[:2000]}"
                        for s in prior[:3]
                    )
                    enriched = system_prompt + (
                        f"\n\n<!-- ruflo memory-enrich stage={stage_id} -->\n"
                        f"## 🔄 同类历史任务参考\n"
                        f"以下是从 Ruflo 记忆中检索到的相似阶段产出，"
                        f"请参考其结构和质量水平：\n\n"
                        f"{memories_text}\n"
                    )
                    logger.info(
                        "[ruflo] Injected %d prior memories into %s prompt",
                        len(prior), stage_id,
                    )

        # ── Auto-init swarm if configured ──
        if _s.ruflo_auto_swarm:
            try:
                status = await bridge.swarm_status()
                if status.get("content") and "no_swarm" in str(status):
                    await bridge.swarm_init(topology="hierarchical-mesh", max_agents=15)
                    logger.info("[ruflo] Auto-initialized swarm")
            except Exception:
                pass

    except Exception as e:
        logger.warning("[ruflo] Memory enrichment failed (non-fatal): %s", e)

    return enriched


# ══════════════════════════════════════════════════════════════════════════
# 10. _write_build_log_to_disk
# ══════════════════════════════════════════════════════════════════════════

def _write_build_log_to_disk(project_dir: str, log_text: str) -> str:
    """Write build.log to project_dir. Returns the file path."""
    path = os.path.join(project_dir, "build.log")
    with open(path, "w", encoding="utf-8") as f:
        f.write(log_text)
    return path


# ══════════════════════════════════════════════════════════════════════════
# 12. _on_provider_fallback (formerly a closure inside execute_stage)
# ══════════════════════════════════════════════════════════════════════════

async def _on_provider_fallback(
    task_id: str,
    stage_id: str,
    agent_name: str,
    payload: Dict[str, Any],
) -> None:
    """Surface provider rotation to the UI. Without this the user
    sees the same 'failed' state no matter how many times the
    stage actually retried under the hood."""
    await emit_event("stage:provider-fallback", {
        "taskId": task_id,
        "stageId": stage_id,
        "agent": agent_name,
        **payload,
    })
