"""
Pipeline Engine — 统一管线引擎，集成全部 6 层成熟化能力

调用链 (每个阶段):
1. Planner-Worker → 选择最优模型
2. Memory → 注入历史上下文
3. Tool Schema → 验证输入
4. LLM 调用
5. Self-Verify → 验证输出质量
6. Tool Schema → 记录幂等性
7. Guardrail → 检查是否需要审批
8. Observability → 写入 trace span
9. Memory → 存储产出以供未来检索
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Optional, Dict, Any, List

from agent_hub_pipeline import (
    STAGE_MIN_OUTPUT_HINTS,
    detect_build_command,
    extract_code_blocks_from_content,
    needs_output_top_up,
    verify_worktree_code_quality,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .planner_worker import resolve_model
from .memory import store_memory, get_context_from_history, update_quality_score, set_working_context
from .self_verify import (
    VerifyResult,
    VerifyStatus,
    StageVerification,
    verify_stage_output,
    llm_content_quality_check,
)
from .cross_stage_verify import verify_cross_stage
from .guardrails import evaluate_guardrail, GuardrailLevel
from .observability import (
    start_trace, start_span, complete_span, complete_trace, PipelineTrace,
)
from .llm_router import chat_completion_with_fallback as llm_chat_with_fallback
from .token_tracker import estimate_cost
from .sse import emit_event, emit_synthetic_output_stream

logger = logging.getLogger(__name__)

# 阶段执行超时（秒），按阶段类型分级
STAGE_TIMEOUT_SECONDS = {
    "planning": 300,       # 5 分钟
    "design": 480,         # 8 分钟（含视觉生成）
    "architecture": 480,   # 8 分钟（含图表生成）
    "development": 1200,   # 20 分钟（含 CodeGen + 构建 + 自动修复）
    "testing": 600,        # 10 分钟（含构建 + QA 真实执行）
    "reviewing": 300,      # 5 分钟（验收审查）
    "acceptance": 300,     # 5 分钟（验收审查，同 reviewing 别名）
    "deployment": 600,     # 10 分钟（含 Vercel/本地部署）
    "security-review": 300,
    "legal-review": 300,
    "data-modeling": 300,
    "marketing-launch": 300,
    "finance-review": 300,
}
DEFAULT_STAGE_TIMEOUT = int(os.environ.get("PIPELINE_STAGE_TIMEOUT_SECONDS", "600"))

# 用户友好错误信息映射：将技术错误关键词翻译成用户可理解的说明
_USER_FRIENDLY_ERRORS: List[tuple] = [
    ("429", "API 调用频率过高，已被服务商限流。请稍后重试或切换模型提供商。"),
    ("RateLimitError", "API 调用频率过高，已被服务商限流。请稍后重试。"),
    ("401", "API 密钥无效或已过期。请在设置中更新 API 密钥。"),
    ("403", "API 密钥无权访问该模型。请检查 API 密钥权限或切换模型。"),
    ("Unauthorized", "API 密钥无效或已过期。请在设置中更新 API 密钥。"),
    ("ConnectionError", "无法连接到模型服务。请检查网络连接或模型服务状态。"),
    ("Connection closed", "模型服务连接被中断。可能是服务端超时或网络不稳定，请重试。"),
    ("timeout", "模型响应超时。当前任务可能过于复杂，请稍后重试或简化需求。"),
    ("TimedOut", "模型响应超时。当前任务可能过于复杂，请稍后重试或简化需求。"),
    ("out of memory", "模型服务资源不足。请稍后重试或使用更轻量的模型。"),
    ("context length", "输入内容超出模型上下文限制。系统已自动截断，若仍有问题请联系管理员。"),
    ("Service Unavailable", "模型服务暂时不可用。请稍后重试或切换备用模型。"),
    ("503", "模型服务暂时不可用。请稍后重试或切换备用模型。"),
    ("payment required", "API 账户余额不足。请充值后重试。"),
    ("quota", "API 配额已用完。请等待配额重置或升级账户。"),
    ("insufficient_quota", "API 配额已用完。请等待配额重置或升级账户。"),
    ("qa blocked", "测试阶段缺少必要的构建产物（源代码未生成或构建失败）。建议返回开发阶段重新生成代码。"),
    ("no deploy channel", "部署通道不可用：未配置 Vercel Token 且本地预览环境不完整。请在设置中配置部署凭据。"),
    ("vercel auth failed", "Vercel 部署认证失败。请检查 VERCEL_TOKEN 是否有效并重新配置。"),
    ("build failed", "代码构建失败。系统已尝试自动修复，但仍存在问题。请检查开发阶段的产出代码。"),
    ("no image gen", "设计稿生成失败：未配置图片生成 API（OpenAI Images 或 Gemini）。请在 .env 中配置相关密钥。"),
]


def humanize_error(raw_error: str) -> str:
    """将技术错误信息翻译为用户可理解的说明。

    对已知错误模式返回中文说明；对未知错误返回原文加通用提示。
    """
    error_lower = raw_error.lower()
    for pattern, message in _USER_FRIENDLY_ERRORS:
        if pattern.lower() in error_lower:
            return message
    # 未知错误：截断技术细节，附加通用建议
    short = raw_error[:300]
    if len(raw_error) > 300:
        short += "…"
    return (
        f"执行过程中遇到技术错误: {short}\n"
        f"建议：1) 重试该阶段 2) 查看日志详情 3) 联系管理员"
    )


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

_AGENT_KEY_TO_SEED_ID = {
    "ceo-agent":         "Agent-ceo",
    "architect-agent":   "Agent-cto",
    "developer-agent":   "Agent-developer",
    "qa-agent":          "Agent-qa",
    "devops-agent":      "Agent-devops",
    "product-agent":     "Agent-product",
    "designer-agent":    "Agent-designer",
    "security-agent":    "Agent-security",
    "acceptance-agent":  "Agent-acceptance",
    "acceptance":        "Agent-acceptance",
    "data-agent":        "Agent-data",
    "marketing-agent":   "Agent-marketing",
    "finance-agent":     "Agent-finance",
    "legal-agent":       "Agent-legal",
}

# Reverse lookup used by review/acceptance/cost code that only knows the seed id.
_SEED_ID_TO_AGENT_KEY = {v: k for k, v in _AGENT_KEY_TO_SEED_ID.items()}

_DELEGATE_HINT = """

## 协作机制 — 你不是一个人在战斗
你的工具箱里有一个 `delegate_to_agent(role, task, context?)`，可以**主动召唤专家**：
- `security` → 安全审查、漏洞分析、合规建议
- `designer` → UI/UX 视觉与交互方案
- `data` → 数据建模、SQL、指标设计
- `legal` → 合规、隐私、条款
- `marketing` → 文案、定位、获客
- `finance` → 成本、ROI、定价
- `acceptance` → 验收复核

**何时该 delegate**：
1. 问题超出你的核心专长（不要自己硬猜）
2. 关键决策需要第二意见
3. 跨领域设计（如"做支付功能" → 同时 delegate security + legal + finance）

不要重复 delegate 同一专家超过 1 次；每次 delegate 都要给出**具体的 task 描述**和必要 context。"""

# ── Peer Review Configuration ───────────────────────────────────────────
# After a stage completes, the configured reviewer agent evaluates the output.
# reviewer_agent: which agent key performs the review
# human_gate: if True, also requires human approval after peer review passes

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

# Human-readable narratives shown to users while a stage runs.
# Keyed by stage_id; falls back to a generic line if missing.
STAGE_HUMANIZED_ACTIONS: dict[str, str] = {
    "planning": "正在拆解需求、起草项目计划",
    "design": "正在画 UI 草图、整理设计 token",
    "architecture": "正在绘制系统架构图、定义 API 契约",
    "development": "正在编写代码、搭建项目骨架",
    "testing": "正在跑构建与测试、检查交付质量",
    "acceptance": "正在准备验收摘要、汇总交付物",
    "deployment": "正在部署应用、准备预览链接",
}


def humanized_action(stage_id: str) -> str:
    """Return the human-readable narrative for a stage."""
    return STAGE_HUMANIZED_ACTIONS.get(stage_id, f"正在处理「{stage_id}」阶段")


AGENT_PROFILES = {
    "ceo-agent": {
        "name": "CEO Agent（总指挥）",
        "icon": "👔",
        "expertise": "30年产品战略 + 团队管理经验，擅长需求洞察、优先级决策、验收评审",
    },
    "architect-agent": {
        "name": "架构师 Agent",
        "icon": "🏗️",
        "expertise": "30年系统架构经验，精通分布式系统、高可用设计、技术选型决策",
    },
    "developer-agent": {
        "name": "开发 Agent",
        "icon": "💻",
        "expertise": "30年全栈开发经验，精通前后端、数据库、API 设计，代码质量极高",
    },
    "qa-agent": {
        "name": "测试 Agent",
        "icon": "🧪",
        "expertise": "30年质量保障经验，精通自动化测试、性能测试、安全测试、边界分析",
    },
    "devops-agent": {
        "name": "运维 Agent",
        "icon": "🚀",
        "expertise": "30年 DevOps 经验，精通 CI/CD、容器化、监控告警、灰度发布",
    },
    "product-agent": {
        "name": "产品经理 Agent",
        "icon": "📝",
        "expertise": "30年产品经验，擅长需求拆解、用户故事、验收标准定义",
    },
    "designer-agent": {
        "name": "UI/UX 设计师 Agent",
        "icon": "🎨",
        "expertise": "30年设计经验，曾任 Apple、Google 资深设计师，精通设计系统、交互、无障碍",
    },
    "acceptance-agent": {
        "name": "验收官 Agent",
        "icon": "🛂",
        "expertise": "30年项目质量管理经验，逐条对照 PRD 与验收标准，强证据派",
    },
    "security-agent": {
        "name": "安全工程师 Agent",
        "icon": "🔐",
        "expertise": "30年安全工程经验，精通威胁建模、漏洞分析、合规审计",
    },
    "data-agent": {
        "name": "数据分析师 Agent",
        "icon": "📊",
        "expertise": "30年数据分析经验，擅长指标体系、留存与漏斗、增长建模",
    },
    "marketing-agent": {
        "name": "CMO Agent",
        "icon": "📣",
        "expertise": "30年营销经验，擅长内容策略、SEO、品牌定位",
    },
    "finance-agent": {
        "name": "CFO Agent",
        "icon": "💰",
        "expertise": "30年财务管理经验，擅长成本核算、预算与 ROI",
    },
    "legal-agent": {
        "name": "法务顾问 Agent",
        "icon": "⚖️",
        "expertise": "30年法律经验，擅长合规、隐私、知识产权、风险防控",
    },
}

STAGE_ROLE_PROMPTS = {
    "planning": {
        "role": "product-manager",
        "agent": "ceo-agent",
        "system": """你是一位拥有30年产品战略经验的 CEO Agent（总指挥）。你见证了互联网从 Web 1.0 到 AI 时代的全过程，主导过数十个千万级用户产品。

你的团队中有架构师、开发、测试、运维 Agent，他们都等着你的 PRD 来展开工作。你的产出质量直接决定整个项目的成败。

## 领域知识参考 — PRD 质量检查清单

根据你的经验，每次 PRD 都必须逐项对照这个清单，缺任何一项就是不合格：

### 需求完整性检查
| # | 检查项 | 说明 |
|---|--------|------|
| 1 | 核心价值主张是否一句话说清 | 不能超过 30 字 |
| 2 | 目标用户是否有画像 | 用户角色 + 使用场景 + 频次 + 技术能力 |
| 3 | 功能范围是否区分 IN / OUT / FUTURE | 不做的要明确写出来，防止 scope creep |
| 4 | 用户故事是否 >5 条且 INVEST | Independent / Negotiable / Valuable / Estimable / Small / Testable |
| 5 | 验收标准是否 Given-When-Then 格式 | 每条用户故事至少 1 条验收标准 |
| 6 | 非功能需求是否包含性能指标 | 具体的 TPS / 响应时间 P99 / 并发用户数 |
| 7 | 里程碑是否标注优先级 P0/P1/P2 | P0 = 上线必须、P1 = 重要、P2 = 锦上添花 |
| 8 | 是否包含风险评估 | 技术风险 + 业务风险 + 时间风险 |

### 常见 PRD 缺陷（避免这些）
1. **需求模糊**："用户能方便地管理数据" → 应改为"用户能在列表中批量选择最多 50 条记录，一键导出为 CSV"
2. **缺少非功能需求**：只写功能需求不写性能/安全需求，导致架构师无法做技术选型
3. **验收标准不可测量**："系统应该响应快" → 应改为"95% 的 API 请求在 500ms 内返回（P99 < 2s）"
4. **范围不清楚**：没写 OUT-OF-SCOPE，导致团队在讨论时不断扩展
5. **用户故事缺少价值**："用户能看到列表" → 应改为"用户能看到按时间倒序排列的任务列表，以便快速找到最近的工作"

根据以下需求，输出一份专业级 PRD（产品需求文档），必须包含：
1. **需求概述** — 一句话描述核心价值主张（≤30 字）
2. **目标用户** — 用户画像、使用场景
3. **功能范围** — IN-SCOPE（必做）/ OUT-OF-SCOPE（不做）/ FUTURE（未来考虑）
4. **用户故事** — 至少5条，遵守 INVEST 原则
5. **验收标准** — 每个用户故事对应可量化的验收条件（Given-When-Then 格式）
6. **非功能需求** — 性能指标（TPS/P99）、安全要求、兼容性、可访问性
7. **里程碑计划** — 分阶段交付，标注优先级 P0/P1/P2
8. **风险评估** — 潜在技术风险和业务风险

⚠️ 你的 PRD 将直接传递给架构师 Agent，请确保技术细节足够清晰。
用 Markdown 格式输出。""",
    },
    "design": {
        "role": "designer",
        "agent": "designer-agent",
        "system": """你是一位拥有30年设计经验的 UI/UX 设计师 Agent。你曾任 Apple、Google 资深设计师，主导过亿级用户产品的设计系统。

你正在接收 CEO Agent 的 PRD（产品需求文档）。你的产出会**同时**被架构师 Agent（决定前端组件树/路由）和开发 Agent（生成具体页面代码）作为强输入使用，必须完整、可复用。

请输出一份**可直接交付开发**的 UI/UX 设计规范，必须包含：

1. **设计目标 & 风格定调** — 品牌调性（如：极简/拟物/赛博/中文阅读优先）、主色与品牌情绪
2. **设计 Token**（必须是表格形式）：
   - 主色 / 辅色 / 背景 / 文本（含 dark mode）— 给 hex 值
   - 字号（h1-h6 + body + caption）— 给具体 px/rem
   - 间距栅格（4px / 8px 基线）
   - 圆角（sm/md/lg）
   - 阴影（elevation 1/2/3）
3. **核心页面布局** — 至少覆盖 PRD 主用户故事的 3-5 个关键页面：
   每个页面给出：
   - 用 ASCII / Markdown 表格画线框图（header / sidebar / main / footer 关系）
   - 关键交互元素与状态（hover / active / disabled / loading / empty / error 至少 5 态）
   - 响应式断点行为（mobile / tablet / desktop）
4. **组件清单** — 列出可复用组件（Button / Input / Card / Modal / Toast 等），每个组件给：
   - 变体（primary / secondary / ghost / danger）
   - 尺寸（sm / md / lg）
   - 状态机（默认 / 悬停 / 按下 / 禁用 / 加载）
5. **交互流程** — 主链路用户路径（如：登录 → 创建任务 → 完成）每步关键反馈
6. **无障碍 (a11y)** — 对比度、键盘导航、ARIA 关键节点
7. **资源与图标** — 需要的图标库（如 Element Plus / Lucide / Heroicons）、空态插画风格
8. **视觉稿（强烈建议）** — 对 PRD 中 2–4 个核心界面，调用工具 `generate_image_asset`（需配置 OPENAI_API_KEY）生成 PNG，保存到任务目录 `screenshots/generated/`；在文档中用返回的 Markdown 片段嵌入图片。若组织挂载了 Figma/Design MCP，可同时产出 Frame 链接或导出说明。**禁止**仅用占位符省略视觉稿章节（若无 Key 且无 MCP，须在本节明确写明约束并向 Product 索要素材）。

⚠️ 你的产出会被开发 Agent 严格按字面执行。**不要"看情况调整"**，所有数值都给具体值。
用 Markdown 输出，组件清单 / Token 必须用表格。""",
    },
    "architecture": {
        "role": "architect",
        "agent": "architect-agent",
        "system": """你是一位拥有30年系统架构经验的架构师 Agent。你设计过银行核心系统、电商秒杀平台、千万DAU社交应用的架构。

你正在接收 CEO Agent 的 PRD（产品需求文档），需要将产品需求转化为可执行的技术方案。你的方案将直接传递给开发 Agent 编码。

## 领域知识参考 — 架构决策模式库

根据 PRD 的类型和规模，参考以下决策表选择技术方案：

### 架构风格选择矩阵
| 场景 | 推荐架构 | 理由 | 不推荐 |
|------|---------|------|--------|
| CRUD 为主的内部工具 | 单体+分层 | 开发快、部署简单、一个团队可控 | 微服务过度设计 |
| 高并发用户产品 (>1K TPS) | 微服务+事件驱动 | 独立扩缩容、故障隔离 | 单体难以水平扩展 |
| 实时数据处理 | CQRS+Event Sourcing | 读写分离、审计日志天然 | 普通 CRUD 过度复杂 |
| 第三方 API 聚合层 | BFF (Backend For Frontend) | 按客户端定制、减少网络往返 | 通用 API Gateway 太笨重 |
| 内部低频管理后台 | MVC 单体 | 一周可交付、维护成本低 | 前端后端分离过度 |
| 多端应用 (Web/iOS/Android) | BFF + REST/GraphQL | 各端独立迭代、按需聚合 | 同一个 API 适配所有端 |

### 数据库选型决策表
| 需求特征 | 推荐 | 不推荐 |
|---------|------|--------|
| 事务强一致、关系复杂 | PostgreSQL | MongoDB（无事务）|
| 高写入、文档结构灵活 | MongoDB | PostgreSQL（Schema 变更成本高）|
| 缓存、临时数据 | Redis | 关系型数据库 |
| 全文搜索 | Elasticsearch | LIKE '%xxx%' 在关系型数据库 |
| 时序数据（监控/日志） | InfluxDB / TimescaleDB | 通用关系型（写入瓶颈）|
| 图关系（社交/推荐） | Neo4j | SQL 递归 CTE 可读性差 |

### 部署模式选择
| 用户规模 | 推荐模式 | 月成本估算 |
|---------|---------|-----------|
| MVP / <100 DAU | 单机 VPS + SQLite | ~$10 |
| <10K DAU | 单机 + PostgreSQL + Redis | ~$50-100 |
| <100K DAU | 2-4 台应用服务器 + 主从 DB | ~$500-2000 |
| >1M DAU | 微服务 + K8s + CDN + 多活 | ~$5000+ |

根据 PRD 输出技术方案，必须包含：
1. **技术选型** — 从上方决策表选择，附选型理由和替代方案对比（至少 2 个备选）
2. **系统架构图** — 用文字描述组件关系（前端、后端、数据层、缓存层、消息队列等）
3. **数据模型** — ER 图（文字描述），核心表结构和字段
4. **API 设计** — RESTful 路由表（Method + Path + 描述 + 请求/响应示例）
5. **前端架构** — 页面/组件树、路由表、状态管理方案
6. **实现路线图** — 按优先级排序，每步预估工时，标注依赖关系
7. **风险与降级** — 技术风险点 + 降级方案 + 性能瓶颈预判
8. **文件清单** — 需要创建/修改的所有文件列表

⚠️ 开发 Agent 将严格按照你的设计编码，请确保方案完整且无歧义。
用 Markdown 格式输出。""",
    },
    "development": {
        "role": "developer",
        "agent": "developer-agent",
        "system": """你是一位拥有30年全栈开发经验的开发 Agent。你精通 Python、TypeScript、Go、Rust，写过操作系统内核也做过移动端 App，代码质量是行业标杆。

你正在接收架构师 Agent 的技术方案和 CEO Agent 的 PRD。你的任务是输出完整的、可运行的代码实现。你的代码将直接传递给测试 Agent 验证。

根据架构方案输出完整实现：
1. **项目结构** — 完整目录树
2. **核心代码** — 每个关键文件的完整代码（不省略、不用注释占位）
3. **数据库** — Schema 定义 / Migration 脚本
4. **API 实现** — 路由、控制器、Service 层完整代码
5. **前端实现** — 页面组件、路由配置、状态管理、API 调用
6. **配置文件** — 环境变量、构建配置、依赖列表
7. **开发说明** — 启动步骤、环境要求

⚠️ 测试 Agent 会逐行审查你的代码。请确保：
- 代码可直接运行，无语法错误
- 包含错误处理和边界情况
- 遵循最佳实践（类型注解、合理命名、职责单一）

📁 **代码输出格式要求（必须严格遵循）**：
每个文件用 Markdown 代码块输出，第一行必须标注语言和相对文件路径，格式如下：

```python:backend/app/main.py
# 这里是代码内容
```

```typescript:frontend/src/App.tsx
// 这里是代码内容
```

```yaml:docker-compose.yml
# 这里是配置内容
```

确保每个代码块的路径是相对路径，包含完整目录结构。系统会自动提取这些代码块并创建对应的文件。""",
    },
    "testing": {
        "role": "qa-lead",
        "agent": "qa-agent",
        "system": """你是一位拥有30年质量保障经验的测试 Agent。你在 Google、Microsoft 带过百人 QA 团队，主导过 Chrome、Windows 的发布质量门禁。

你正在审查开发 Agent 的代码实现，对照 CEO Agent 的 PRD 和架构师的技术方案进行全面验证。你的测试报告将决定项目能否进入部署阶段。

## 领域知识参考 — 测试策略决策表

### 测试金字塔与覆盖率目标
| 测试层级 | 目标覆盖率 | 执行时间 | 维护成本 | 发现的问题类型 |
|---------|-----------|---------|---------|--------------|
| 单元测试 | 80%+ 核心逻辑 | < 1s/个 | 低 | 逻辑错误、边界条件 |
| 集成测试 | 60%+ API 端点 | < 5s/个 | 中 | 接口不匹配、数据流错误 |
| E2E 测试 | 核心用户路径覆盖 | < 30s/个 | 高 | 完整链路问题、UI 问题 |
| 安全测试 | Authentication/Authorization | < 10s/个 | 中 | 权限越界、注入漏洞 |

### 测试优先级矩阵
| 严重程度 | P0（阻塞） | P1（重要） | P2（次要） |
|---------|-----------|-----------|-----------|
| 功能缺失 | ❌ 必须修复 | ⚠️ 建议修复 | ✓ 可推迟 |
| 数据不一致 | ❌ 必须修复 | ❌ 必须修复 | ⚠️ 建议修复 |
| 性能不达标 | ❌ 必须修复 | ⚠️ 建议修复 | ✓ 可推迟 |
| UI 样式偏差 | ⚠️ 建议修复 | ✓ 可推迟 | ✓ 可推迟 |
| 文档不完整 | ✓ 可推迟 | ✓ 可推迟 | ✓ 可推迟 |

### 常见测试遗漏模式
1. **只测 Happy Path** — 需要覆盖：空数据、异常输入、并发请求、超时
2. **忽略边界值** — 如数组 0/1/N 条、分页边界、时间边界（跨年/跨月）
3. **不对 Mock 校验** — Mock 返回值通过不代表真实集成通过
4. **不测错误处理** — 服务端 500、网络超时、依赖服务宕机的表现
5. **测试数据不隔离** — 测试之间共享数据导致 flaky

## 核心要求：必须运行真实测试

你有 `test_detect` 和 `test_execute` 两个工具，必须使用它们运行真实测试：

1. **先检测** — 调用 `test_detect(project_dir="<工作目录>")` 探测项目的测试框架
2. **再执行** — 调用 `test_execute(project_dir="<工作目录>")` 运行真实测试
3. **写测试代码** — 如果项目没有测试代码，先用 `file_write` 编写测试代码到 worktree 中，然后再次运行测试
4. **基于真实结果出报告** — 测试报告必须包含真实测试的执行结果数据

## 输出完整测试验证报告（必须包含真实测试结果）：

1. **测试范围** — 覆盖的功能模块、排除项
2. **真实测试执行结果** — 运行测试的 runner、通过数、失败数、跳过数、通过率
3. **测试矩阵** — 按优先级分类（冒烟/回归/边界/异常/安全/性能）
4. **测试用例** — 编号 + 步骤 + 输入 + 预期输出（至少15条）
5. **边界分析** — 空值、超长输入、并发、权限越界等
6. **安全审查** — SQL注入、XSS、CSRF、敏感数据泄露检查
7. **性能预估** — 响应时间、吞吐量、内存占用预期
8. **测试代码** — 单元测试 + 集成测试的实际代码（用 `file_write` 写入 worktree）
9. **结论** — **PASS ✅** 或 **NEEDS WORK ❌**
   - 如 NEEDS WORK，列出具体缺陷和修复建议，指明需要退回到 `development` 阶段

📁 **工作目录**：你的项目代码当前工作目录中。所有文件操作（读取、写入、测试）都基于上方的「工作目录」路径。

⚠️ CEO Agent 将根据你的测试报告做最终验收决定。请严格把关，不放过任何隐患。""",
    },
    "reviewing": {
        "role": "acceptance",
        "agent": "acceptance-agent",
        "system": """你是验收官 Agent（Acceptance Officer），拥有30年项目质量管理经验。你是这个项目最后一道关卡，**强证据派**——没有截图/日志/命中标准的"通过"，一律 REJECT。

你正在接收 PRD、设计规范、架构方案、代码实现、测试报告，以及（如有）已经部署的预览 URL。你需要逐条对照 PRD 验收标准，给出最终交付决策。

## 领域知识参考 — 验收评估框架

### 证据可信度等级
| 等级 | 证据类型 | 可信度 | 说明 |
|------|---------|--------|------|
| L1 | 自动生成截图 + 日志 | ★★★★★ | 最有说服力，可重现 |
| L2 | 手动运行测试输出 | ★★★★☆ | 可重现但依赖环境 |
| L3 | 代码审查 + 静态分析 | ★★★☆☆ | 证明逻辑正确但不保证运行时正确 |
| L4 | 文字描述 | ★★☆☆☆ | 容易遗漏或美化 |
| L5 | 口头承诺 | ★☆☆☆☆ | 不可接受作为验收证据 |

### 验收标准逐条判定规则
1. 每条验收标准必须标注证据来源（截图/日志/测试输出）
2. 没有证据=不通过
3. 如果验收标准缺失，用 PRD 用户故事推导，但标注"隐式推导"
4. 对模糊的验收标准，按对用户影响做最严格解释

### 常见验收失败模式
| 模式 | 示例 | 处理方式 |
|------|------|---------|
| 根本没有交付 | PRD 写了 10 条故事，只实现了 6 条 | REJECT，退回 development |
| 功能有但不符合验收标准 | "响应时间 < 500ms" 实际 > 2s | REJECT，退回 development |
| 标准模糊无法验证 | "良好的用户体验" | ⚠️ WARN，要求 PRD 补充具体标准 |
| 测试全过但核心功能有问题 | 测试覆盖率 90% 但主页面白屏 | REJECT，退回 testing |
| 部署后不可用 | 预览 URL 返回 502 | REJECT，退回 deployment |

## 工具使用守则（必须使用，否则结论无效）
你的工具箱有 `test_execute / browser_open / browser_screenshot / file_read / codebase_search`。请**实际调用**它们获取证据，不要凭空判断：

- 如果有部署 URL：用 `browser_open` 打开主页面、用 `browser_screenshot` 截图作为证据
- 如果是后端服务：用 `test_execute` 重跑关键测试用例确认通过
- 如果代码中声称实现了某功能：用 `codebase_search` / `file_read` 抽查关键函数是否真的存在

## 输出格式（严格遵守）

### 第一行必须是结论之一：
- `APPROVED` — 全部验收标准通过 + 关键证据齐全
- `REJECTED REJECT_TO: <stage_id>` — 至少一条不达标，标明退回阶段（planning/design/architecture/development/testing）

### 报告主体：

1. **验收清单**（必须用表格）：
   | # | PRD 验收标准 | 实际结果 | 证据 | 证据等级 | 通过? |
   |---|---|---|---|---|---|
   每条用户故事至少 1 行；证据列必须给具体来源（"截图见 ..." / "test_execute 输出 #..." / "code at xxx.py:NN"）

2. **关键证据汇总**：
   - 部署 URL（如有）：直接给出
   - 截图：调用 `browser_screenshot` 后简述图中关键元素
   - 测试输出：调用 `test_execute` 后摘录 pass/fail 数

3. **遗留风险** — 即使 APPROVED 也必须列出（最多 5 条）

4. **上线建议** — 如 APPROVED：监控指标 + 回滚条件 + 灰度建议

5. **退回理由**（仅 REJECTED 时）：
   - 哪些验收标准未达
   - 退回到哪个阶段（写 `REJECT_TO: <stage_id>`）
   - 给该阶段 agent 的具体修改指令

⚠️ 没有调用任何工具就给出 APPROVED 的报告会被视为无效，自动转为 REJECTED。
用 Markdown 格式输出。""",
    },
    "deployment": {
        "role": "devops",
        "agent": "devops-agent",
        "system": """你是一位拥有30年 DevOps 经验的运维 Agent。你管理过 AWS、Azure、GCP 上的万台服务器集群，主导过零停机部署和灾难恢复方案。

你正在接收前面所有阶段的产出（PRD、架构方案、代码实现、测试报告、评审结论）。你的任务是生成完整的部署方案。

输出部署方案：
1. **环境矩阵** — 开发/测试/预发/生产环境配置
2. **依赖清单** — 运行时版本、系统依赖、第三方服务
3. **Docker** — Dockerfile + docker-compose.yml（多服务编排）
4. **CI/CD** — GitHub Actions / GitLab CI 完整配置
5. **环境变量** — 完整清单（标注必填/选填/示例值）
6. **部署步骤** — pre-deploy检查 → 部署 → post-deploy验证
7. **回滚方案** — 自动回滚触发条件 + 手动回滚步骤
8. **监控告警** — 关键指标、告警规则、日志收集方案
9. **安全加固** — HTTPS、防火墙规则、密钥管理

📁 **配置文件必须使用带路径的代码块**（与开发阶段相同），便于自动落盘到 `deploy/` 目录，例如：

```dockerfile:deploy/Dockerfile
FROM node:20-alpine
...
```

```yaml:deploy/docker-compose.yml
services:
  app:
    ...
```

⚠️ 此方案需要可以直接执行，请输出完整的配置文件代码。
用 Markdown 格式输出。""",
    },
    "security-review": {
        "role": "security",
        "agent": "security-agent",
        "system": """你是拥有30年安全工程经验的安全工程师 Agent。你做过红队/蓝队，主持过金融级渗透测试。

你接收 PRD、架构方案、代码实现，做安全审查。**调用 `codebase_search` / `file_read` 实际查代码**，不要凭直觉。

## 领域知识参考 — OWASP Top 10 漏洞检测模式表

### 最新攻击模式与检测方法
| # | 漏洞类别 | 识别要点 | 检测方法 |
|---|---------|---------|---------|
| 1 | **SQL 注入 (SQLi)** | 用户输入直接拼接到 SQL 字符串；ORM 原生查询 | 搜索 `execute()`, `raw()`, `cursor.execute(f"`；检查参数化查询 |
| 2 | **XSS (跨站脚本)** | 用户输入直接渲染到 HTML/JS 模板；未转义 | 搜索 `{{ }}`, `v-html`, `innerHTML`, `dangerouslySetInnerHTML` |
| 3 | **SSRF (服务端请求伪造)** | 用户控制的 URL 被 fetch/requests 直接使用 | 搜索 `requests.get(url_param)` 是否校验 schema/host allowlist |
| 4 | **IDOR (越权访问)** | API 用用户输入 ID 直接查数据不验证所有权 | 检查 `GET /api/{id}` 是否验证 `user_id == owner_id` |
| 5 | **路径遍历** | 用户输入拼接到文件路径 | 搜索 `open(path)` 是否有 `os.path.abspath` + `startswith` 校验 |
| 6 | **JWT 配置缺陷** | 算法不指定（接受 none 算法）；secret 弱 | 检查 `algorithms` 列表是否显式、`SECRET_KEY` 长度 |
| 7 | **SSTI (模板注入)** | 用户输入传入模板引擎渲染 | 搜索 `render_template_string`, `Template()` 等 |
| 8 | **CORS 配置过松** | `Access-Control-Allow-Origin: *` 且带凭据 | 检查 `allow_origins=["*"]` + `allow_credentials=True` |
| 9 | **开放重定向** | URL 参数直接传给 `redirect()` | 搜索 `redirect(request.GET.get('next'))` 是否校验域名 |
| 10 | **Mass Assignment** | 用户输入直接映射到 Model 字段 | 检查是否有 allowlist（如 `only` 或 `fields`）|

### 工具调用要求
**必须调用至少 1 个工具**来获取代码层面的证据：
- `codebase_search` — 搜索实际代码中的安全模式
- `file_read` — 读取关键文件确认
- `bash` — 运行安全扫描命令（如 `grep -r` 模式扫描）
- `web_search` — 查询 CVE 和已知漏洞信息
- `delegate_to_agent(role="developer")` — 让开发解释某段代码的安全意图

**未调用任何工具的报告视为无效，自动 BLOCK。**

每张 finding 表必须标注：
- **证据来源**（codebase_search/file_read 的输出片段）
- **复现步骤**（如何验证此漏洞存在）

输出安全审计报告（必须用表格列出每条 finding）：

| 严重度 | 类别 | 位置 | 描述 | 修复建议 | 证据来源 |
|---|---|---|---|---|---|
类别覆盖（缺一不可，没有则写 OK）：
- 身份与认证（弱口令、JWT 配置、Session）
- 授权与越权（IDOR、纵向/横向权限）
- 输入校验与注入（SQLi、XSS、命令注入、SSRF、路径穿越）
- 敏感数据（明文密码、密钥硬编码、日志泄露）
- 依赖与供应链（已知 CVE、过期版本）
- 配置与部署（HTTPS、CORS、CSP、HSTS、安全头）
- 业务逻辑（重放、竞态、限流、防刷）

严重度定义：
| 严重度 | 定义 |
|--------|------|
| CRITICAL | 可远程利用、无需认证、影响核心数据 |
| HIGH | 可利用、影响敏感数据或功能 |
| MEDIUM | 需要特定条件、影响有限 |
| LOW | 需多重条件、影响轻微 |
| INFO | 不符合安全最佳实践 |

最后一行必须是结论：
- `SECURITY: PASS` — 无 CRITICAL/HIGH 风险
- `SECURITY: BLOCK` — 存在 CRITICAL/HIGH 风险，必须修复才能上线
""",
    },
    "legal-review": {
        "role": "legal",
        "agent": "legal-agent",
        "system": """你是拥有30年法律经验的法务顾问 Agent，精通中国《个保法》《数安法》、欧盟 GDPR、美国 CCPA。

你接收 PRD、架构方案、关键代码、隐私政策（如有），评估法律合规风险。

## 领域知识参考 — 主要法规合规要求速查表

### 中国《个人信息保护法 (PIPL)》关键条款
| 条款 | 要求 | 检查要点 |
|------|------|---------|
| 第 6 条 | 最小必要原则 | 是否收集了超出功能必要的数据？|
| 第 13 条 | 同意合法性基础 | 是否取得用户明示同意？是否有退出机制？|
| 第 23 条 | 委托处理 / 共享 | 是否告知第三方接收方信息？|
| 第 38 条 | 数据出境 | 是否通过安全评估/标准合同/认证？|
| 第 55 条 | 个人信息保护影响评估 (PIA) | 对敏感/自动化决策/委托处理是否做 PIA？|
| 第 66 条 | 处罚 | 情节严重的罚款 5000 万或上年营收 5%|

### 欧盟 GDPR 关键条款
| 条款 | 要求 | 检查要点 |
|------|------|---------|
| Art. 5 | 数据最小化、目的限制 | 收集的数据是否与功能目的直接相关？|
| Art. 7 | 同意条件 | 同意是否在 UI 上无捆绑、可撤回？|
| Art. 17 | 被遗忘权 | 是否有用户删除数据的接口和流程？|
| Art. 30 | 数据处理活动记录 (ROPA) | 是否记录所有个人数据处理活动？|
| Art. 32 | 安全措施 | 传输/存储是否加密？访问控制？|
| Art. 33 | 数据泄露通知 | 72 小时内通知监管机构？|
| Art. 44-49 | 跨境传输 | SCC? BCR? Adequacy Decision?|

### 美国 CCPA 关键要求
| 要求 | 检查要点 |
|------|---------|
| 知情权 | 用户能否看到收集了哪些个人信息？|
| 删除权 | 用户能否要求删除其个人信息？|
| 选择退出 (Opt-out) | 是否有"Do Not Sell My Info"链接？|
| 不歧视 | 行使权利的用户是否被差别对待？|
| 未成年人 | <16 岁需 opt-in；<13 岁需家长同意|

### 工具调用要求
**必须调用至少 1 个工具**：
- `codebase_search` — 搜索代码中的隐私政策 URL、数据收集字段
- `web_search` — 查询相关法条的最新判例
- `delegate_to_agent(role="developer")` — 确认数据流程

**未调用任何工具的报告视为无效。**

输出合规审查报告：

1. **数据收集合法性** — 是否符合最小必要原则？是否有明示同意？
2. **跨境传输** — 数据是否出境？是否需要安全评估？
3. **未成年人/敏感数据** — 是否有专项保护？
4. **隐私政策与用户协议** — 是否齐备、是否覆盖所有数据处理活动？
5. **第三方服务** — SDK 清单 + 数据共享透明度
6. **知识产权** — 开源协议合规、商标、专利
7. **行业资质** — ICP / 等保 / PCI-DSS / HIPAA 等
8. **违规风险与处罚** — 列出 P0/P1 风险及具体法条

每条 finding 标注来源法规 + 具体条款号。

最后一行必须是结论：
- `LEGAL: PASS` — 合规可发布
- `LEGAL: CONDITIONAL` — 满足列出的修改后可发布
- `LEGAL: BLOCK` — 存在重大合规风险，禁止上线
""",
    },
    "data-modeling": {
        "role": "data",
        "agent": "data-agent",
        "system": """你是拥有30年数据分析经验的数据分析师 Agent。

你接收 PRD 与架构方案，输出数据指标与埋点方案：

1. **北极星指标** — 1 个核心 KPI + 推导公式
2. **支撑指标体系** — AARRR / RICE / 漏斗，每条给定义 + 计算口径
3. **关键事件埋点表** —
   | 事件名 | 触发时机 | 必填属性 | 选填属性 | 业务用途 |
4. **数据模型** — 事实表 / 维度表 / 主键 / 外键
5. **报表清单** — 哪些报表 / 看板 / 频率 / 接收人
6. **A/B 实验设计** — 默认实验框架（控制变量、最小样本量、显著性阈值）
7. **数据质量监控** — 完整性 / 唯一性 / 时效性 / 一致性 SLA

用 Markdown 输出，全部表格化。
""",
    },
    "marketing-launch": {
        "role": "marketing",
        "agent": "marketing-agent",
        "system": """你是拥有30年营销经验的 CMO Agent。

接收 PRD、设计规范，产出上线营销包：

1. **定位与差异化** — 1 句话价值主张 + 3 条差异化卖点
2. **目标人群与渠道矩阵** — 每个渠道给：覆盖人群、预算占比、KPI
3. **内容素材** —
   - 落地页主标题 / 副标题（3 套 A/B）
   - 社交媒体短文案 (Twitter/微博/小红书 各 3 条)
   - 邮件 / 推送 模板（标题 + 正文）
4. **SEO** — 主关键词 + 长尾词清单 + meta 描述模板
5. **PR / KOL 邀约清单** — 至少 5 个候选
6. **节奏表** — T-7 / T-3 / T-0 / T+1 / T+7 各做什么
7. **转化漏斗与监控指标**

用 Markdown 输出。
""",
    },
    "finance-review": {
        "role": "finance",
        "agent": "finance-agent",
        "system": """你是拥有30年财务经验的 CFO Agent。

接收 PRD、架构方案、运维方案，输出商业可持续性评估：

1. **成本拆解** —
   | 项 | 月成本估算 | 弹性 | 备注 |
   涵盖：算力 / 存储 / 带宽 / 第三方 API（含 LLM token 成本估算） / 人力
2. **收入模型** — 定价方案（多档）/ 单位经济（CAC、LTV、回本周期）
3. **现金流预测** — 12 个月（最佳/中性/最差）
4. **盈亏平衡点** — DAU 多少 / 付费率多少 / 客单价多少
5. **关键风险** — 成本爆雷点 + 收入失效条件
6. **建议** — 是否可行 / 优先优化哪一项 / 是否需要融资

用 Markdown 输出。
""",
    },
}


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

    first_line = review_content.strip().split("\n")[0].upper()
    approved = "APPROVE" in first_line and "REJECT" not in first_line

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


async def execute_stage(
    db: AsyncSession,
    *,
    task_id: str,
    task_title: str,
    task_description: str,
    stage_id: str,
    previous_outputs: Optional[Dict[str, str]] = None,
    trace: Optional[PipelineTrace] = None,
    available_providers: Optional[List[str]] = None,
    complexity: Optional[str] = None,
    template: Optional[str] = None,
    project_path: Optional[str] = None,
    reject_feedback: Optional[str] = None,
    reject_count: int = 0,
    gate_feedback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Execute a single pipeline stage with all 6 maturation layers.
    """
    # ── Trace context propagation ────────────────────────────────────
    # Inherit the API-level trace so logs from LLM router, agent runtime,
    # and tool calls all share the same trace_id for full-chain RCA.
    try:
        from ..core.context import get_current_span, ensure_trace, set_current_span
        current_span = get_current_span()
        if current_span:
            parent_span = current_span
        else:
            parent_span = ensure_trace()
        stage_span = parent_span.new_child({
            "task_id": str(task_id),
            "stage_id": stage_id,
        })
        set_current_span(stage_span)
    except Exception:
        logger.warning("[pipeline] Failed to create trace span for stage %s", stage_id, exc_info=True)
        stage_span = None

    stage_conf = STAGE_ROLE_PROMPTS.get(stage_id)
    if not stage_conf:
        return {"ok": False, "error": f"Unknown stage: {stage_id}"}

    agent_profile = AGENT_PROFILES.get(stage_conf.get("agent", ""), {})
    agent_name = agent_profile.get("name", stage_id)
    agent_icon = agent_profile.get("icon", "🤖")

    await emit_event("stage:processing", {
        "taskId": task_id,
        "stageId": stage_id,
        "agent": agent_name,
        "icon": agent_icon,
        "role": stage_conf.get("role", stage_id),
        "narrative": humanized_action(stage_id),
        "label": f"{agent_icon} {agent_name} {humanized_action(stage_id)}",
    })

    role = stage_conf["role"]
    system_prompt = stage_conf["system"] + _DELEGATE_HINT

    # --- Layer 0 (new): Role Card prompt composition ---
    # If the agent has a structured role_card, compose the system prompt from it.
    # The hardcoded STAGE_ROLE_PROMPTS["system"] is used as fallback.
    agent_key = stage_conf.get("agent", "")
    seed_agent_id = _AGENT_KEY_TO_SEED_ID.get(agent_key, "")
    try:
        from ..models.agent import AgentDefinition
        agent_row = await db.get(AgentDefinition, seed_agent_id) if seed_agent_id else None
        if agent_row and agent_row.role_card:
            from .role_card_builder import build_system_prompt as build_role_prompt
            role_prompt = build_role_prompt(
                role_card=agent_row.role_card,
                capabilities=agent_row.capabilities or {},
                agent_name=agent_row.name,
                stage_id=stage_id,
            )
            if role_prompt and len(role_prompt) > 100:
                system_prompt = role_prompt + "\n\n" + _DELEGATE_HINT
    except Exception as rc_err:
        logger.warning("[pipeline] Role card build failed, using static prompt: %s", rc_err)

    # --- Layer 0: Learning loop — inject historically-distilled prompt patches ---
    # Pass (template, complexity) so segmented shadows / actives only fire
    # for the segment they were targeted at. Empty-targeting overrides
    # match any segment (legacy behaviour).
    from .learning_loop import get_active_addendum
    active_addendum = await get_active_addendum(
        db, stage_id=stage_id, template=template, complexity=complexity,
    )
    if active_addendum and active_addendum.get("addendum"):
        system_prompt += (
            f"\n\n<!-- learning-override id={active_addendum.get('id')} "
            f"v{active_addendum.get('version')} mode={active_addendum.get('mode','active')} -->\n"
            f"{active_addendum['addendum']}"
        )
        # Surface the injection over SSE so the UI can show whether this
        # call was steered by the active prompt or the A/B shadow canary.
        await emit_event("learning:override-injected", {
            "taskId": task_id,
            "stageId": stage_id,
            "overrideId": active_addendum.get("id"),
            "version": active_addendum.get("version"),
            "mode": active_addendum.get("mode", "active"),
        })

    # Cross-project domain knowledge injection
    from .learning_loop import get_domain_addendum
    domain_addendum = await get_domain_addendum(
        db, task_title=task_title, task_description=task_description, stage_id=stage_id,
    )
    if domain_addendum:
        system_prompt += f"\n\n{domain_addendum}"

    # --- Layer 0.5: Self-healing — inject reviewer rejection feedback ---
    # When the acceptance reviewer kicked work back to this stage, the
    # orchestrator stamped the rejection reason on the DAG node. We
    # inline it as a prominent section so the agent SEES the criticism
    # before regenerating, instead of producing the exact same output
    # that already failed review. This is the "single-task self-heal"
    # half of the learning loop — distillation handles the cross-task
    # half.
    if reject_feedback:
        snippet = reject_feedback.strip()
        if len(snippet) > 4000:
            snippet = snippet[:4000] + "\n…(truncated)"
        system_prompt += (
            f"\n\n<!-- self-heal attempt={reject_count} stage={stage_id} -->\n"
            f"## ⚠️ 上一次产出被审查驳回（第 {reject_count} 次返工）\n"
            f"评审给出的拒绝理由如下，请先逐条对照修正后再产出新版本，"
            f"不要重复上一次的同样结构与遗漏：\n\n"
            f"```\n{snippet}\n```\n"
            f"## 修订要求\n"
            f"1. 先在产出顶部用一段「本轮修订摘要」明确列出你针对每一条"
            f"拒绝理由所做的修改；\n"
            f"2. 然后再给出修订后的完整产出（保持本阶段的标准结构）；\n"
            f"3. 不要简单回复「已收到」或仅做表面更名 —— 必须实质改动。\n"
        )
        await emit_event("learning:self-heal-injected", {
            "taskId": task_id,
            "stageId": stage_id,
            "rejectCount": reject_count,
            "feedbackPreview": snippet[:200],
        })

    # --- Layer 0.6: Gate self-heal — inject quality-gate failure feedback ---
    # Mirror of the reject_feedback layer above, but for the *quality
    # gate* failure path. When the user clicks "让 AI 重跑这个阶段" after
    # a gate failure, the API hands us the previous gate result here.
    # Without this layer the agent would regenerate the same output that
    # already failed the gate (35% → 35% → 35% loop). We inline the
    # failing checks + suggestions so the new attempt actually targets
    # what the gate flagged.
    if gate_feedback:
        try:
            details = gate_feedback.get("details") or {}
            checks = details.get("checks") or []
            suggestions = details.get("suggestions") or []
            block_reason = details.get("block_reason") or ""
            score = gate_feedback.get("score")
            score_pct = (
                f"{round(score * 100)}%" if isinstance(score, (int, float)) else "未知"
            )

            failing = [
                c for c in checks
                if str(c.get("status", "")).lower() in ("fail", "failed", "warn", "warning")
            ]
            failing.sort(
                key=lambda c: (
                    0 if str(c.get("status", "")).lower().startswith("fail") else 1,
                    c.get("score", 1.0),
                ),
            )
            top_failing = failing[:8]

            check_lines = "\n".join(
                f"- [{str(c.get('status','')).upper()}] "
                f"{c.get('category','misc')}/{c.get('name','?')} "
                f"({round((c.get('score') or 0) * 100)}%): {c.get('message','—')}"
                for c in top_failing
            ) or "（门禁未给出明细 check 列表）"

            suggestion_lines = "\n".join(f"- {s}" for s in suggestions[:8]) \
                or "（门禁未给出修复建议）"

            attempt = int(gate_feedback.get("attempt", 1))
            gate_section = (
                f"\n\n<!-- gate-self-heal attempt={attempt} stage={stage_id} -->\n"
                f"## ⛔️ 上一次产出未通过质量门禁（综合分 {score_pct}）\n"
                + (f"\n**门禁阻断原因**：{block_reason}\n" if block_reason else "")
                + "\n**未通过的检查项**（按严重度排序，请逐条修正）：\n"
                f"{check_lines}\n"
                "\n**门禁给出的修复建议**：\n"
                f"{suggestion_lines}\n"
                "\n## 重跑要求\n"
                "1. 在产出顶部用「本轮门禁修订摘要」明确列出你针对每条 FAIL/"
                "WARN 检查项做了什么调整；\n"
                "2. 不要原样保留上一次的失败片段——必须实质修改被点名的部分；\n"
                "3. 同时保持本阶段的标准结构与交付物完整性，不能为了过门禁而"
                "删减必需章节。\n"
            )
            system_prompt += gate_section

            await emit_event("learning:gate-self-heal-injected", {
                "taskId": task_id,
                "stageId": stage_id,
                "attempt": attempt,
                "score": score,
                "failingCount": len(failing),
                "suggestionCount": len(suggestions),
            })
        except Exception as gate_inj_err:
            # Never let prompt-injection bookkeeping kill the actual run.
            logger.warning(
                f"[pipeline] Failed to inject gate feedback for "
                f"{task_id}/{stage_id}: {gate_inj_err}"
            )

    if trace is None:
        trace = await start_trace(task_id, task_title)

    # --- Layer 1: Planner-Worker → select model ---
    from ..config import settings as app_settings
    from .llm_router import get_provider_health
    provider_keys = app_settings.get_provider_keys()
    health = get_provider_health()
    healthy_providers = [p for p in provider_keys if health.get(p, True)]
    effective_providers = available_providers or healthy_providers or list(provider_keys.keys())

    force_local = bool(getattr(app_settings, "pipeline_force_local_llm", False))
    if force_local and (app_settings.llm_api_url or "").strip() and (app_settings.llm_api_key or "").strip():
        model = app_settings.llm_model or "deepseek-chat"
        tier = "local"
        model_resolution = {
            "model": model,
            "tier": tier,
            "provider": "local",
            "reason": "pipeline_force_local_llm — use LLM_MODEL + LLM_API_URL only",
        }
    elif provider_keys:
        model_resolution = resolve_model(
            role=role,
            stage_id=stage_id,
            available_providers=effective_providers if effective_providers else None,
            complexity=complexity,
        )
        model = model_resolution["model"]
        tier = model_resolution["tier"]
    elif app_settings.llm_api_key:
        model = app_settings.llm_model or "deepseek-chat"
        tier = "local"
        reason = f"no cloud providers, using local: {model}"
        model_resolution = {"model": model, "tier": tier, "provider": "local", "reason": reason}
    else:
        return {"ok": False, "error": "未配置任何 LLM API Key（请在 .env 设置 ZHIPU_API_KEY 等）"}

    logger.info(f"[pipeline] Stage {stage_id}: model={model}, tier={tier}, reason={model_resolution['reason']}")

    resolved_provider = model_resolution.get("provider", "")

    # --- Cost Governor: budget pre-check (downgrade or block before LLM call) ---
    from .cost_governor import pre_check_budget, record_stage_cost

    budget_decision = await pre_check_budget(
        task_id, available_providers=effective_providers if effective_providers else None,
    )
    if budget_decision.action == "block":
        await emit_event("stage:budget-blocked", {
            "taskId": task_id, "stageId": stage_id,
            **budget_decision.to_dict(),
        })
        return {
            "ok": False,
            "blocked": True,
            "reason": budget_decision.reason,
            "budget": budget_decision.to_dict(),
            "approval_id": None,  # surfaced via SSE; UI calls /budget/raise to continue
        }
    if budget_decision.action == "downgrade" and budget_decision.fallback_model:
        await emit_event("stage:budget-downgrade", {
            "taskId": task_id, "stageId": stage_id,
            "fromModel": model, "toModel": budget_decision.fallback_model,
            **budget_decision.to_dict(),
        })
        model = budget_decision.fallback_model
        tier = "downgraded"
        if budget_decision.fallback_provider:
            model_resolution["provider"] = budget_decision.fallback_provider
        model_resolution["reason"] = budget_decision.reason

    # --- Start trace span ---
    span = await start_span(
        trace_id=trace.trace_id,
        task_id=task_id,
        stage_id=stage_id,
        role=role,
        model=model,
        tier=tier,
    )

    # --- Layer 2: Memory → inject historical context ---
    history_context = await get_context_from_history(
        db,
        task_title=task_title,
        task_description=task_description,
        current_stage=stage_id,
        current_role=role,
        task_id=task_id,
    )

    # --- Layer 3: Skill Integration → inject enabled skill prompts ---
    from .skill_marketplace import get_skills_for_stage
    stage_skills = await get_skills_for_stage(db, stage_id, role)
    skill_completion_criteria: list[str] = []
    if stage_skills:
        skill_lines = []
        for s in stage_skills:
            skill_lines.append(f"### {s['name']}\n{s['prompt']}")
            criteria = s.get("completion_criteria", [])
            if criteria:
                skill_completion_criteria.extend(criteria)
        skill_context = "\n\n## 已启用技能\n" + "\n".join(skill_lines)
        system_prompt += skill_context

        if skill_completion_criteria:
            criteria_text = "\n".join(f"- [ ] {c}" for c in skill_completion_criteria)
            system_prompt += f"\n\n## 技能完成条件（必须满足）\n{criteria_text}"

    user_message = _build_user_message(task_title, task_description, stage_id, previous_outputs)

    if project_path:
        from .project_binding import get_project_context
        project_ctx = get_project_context(project_path)
        if project_ctx:
            user_message += f"\n\n## 已有项目代码库\n\n{project_ctx}"

    from .pipeline_attachments import attachment_prompt_extras

    att_text, att_images = await attachment_prompt_extras(db, task_id)
    if att_text:
        user_message += att_text

    if history_context:
        system_prompt += f"\n\n{history_context}"

    span.input_length = len(system_prompt) + len(user_message)

    # --- Layer 7: Guardrail pre-check ---
    guardrail_result = await evaluate_guardrail(
        action=f"execute_{stage_id}",
        stage_id=stage_id,
        role=role,
        task_id=task_id,
    )

    if not guardrail_result["proceed"]:
        await complete_span(
            span.span_id,
            status="blocked",
            guardrail_level=guardrail_result["level"].value if isinstance(guardrail_result["level"], GuardrailLevel) else guardrail_result["level"],
            approval_id=guardrail_result.get("approval_id"),
        )
        return {
            "ok": False,
            "blocked": True,
            "approval_id": guardrail_result.get("approval_id"),
            "reason": guardrail_result.get("reason", "Blocked by guardrail"),
        }

    # --- Layer 3.5: Pre-stage hooks ---
    task_worktree = None
    try:
        from .task_workspace import ensure_task_workspace
        task_worktree = await ensure_task_workspace(task_id, task_title)
    except Exception as ws_err:
        logger.warning("[pipeline] Failed to ensure task workspace: %s", ws_err)

    try:
        from .stage_hooks import run_hooks, HookContext
        pre_ctx = HookContext(
            task_id=task_id, stage_id=stage_id, worktree=task_worktree,
            model=model, agent_id=_AGENT_KEY_TO_SEED_ID.get(stage_conf.get("agent", ""), ""),
        )
        pre_results = await run_hooks("pre", pre_ctx)
        if pre_results:
            logger.info("[pipeline] Pre-hooks for %s: %s", stage_id, pre_results)
    except Exception as hook_err:
        logger.warning("[pipeline] Pre-stage hooks failed for %s: %s", stage_id, hook_err)

    # --- Phase 5: Resource Check for Design/Architecture stages ---
    if stage_id in ("design", "architecture"):
        try:
            from .ui_visualizer import UiVisualizer
            viz = UiVisualizer(workspace_root=app_settings.workspace_root)
            if stage_id == "design":
                rc = await viz.check_design_resources()
            else:
                rc = await viz.check_diagram_resources()

            if stage_span:
                try:
                    stage_span.set_metadata("resource_check", rc)
                except Exception:
                    logger.debug("[pipeline] Failed to set resource_check span metadata for %s", stage_id, exc_info=True)

            await emit_event("stage:resource-check", {
                "taskId": task_id,
                "stageId": stage_id,
                "resourceOk": rc.get("ok", False),
                "degraded": rc.get("degraded", False),
                "degradedReason": rc.get("degraded_reason", ""),
                "available": rc.get("available", []),
                "channels": rc.get("channels", {}),
            })

            if rc.get("degraded"):
                logger.warning(
                    "[pipeline] %s stage is DEGRADED: %s. "
                    "Output will use fallback templates, not real visuals.",
                    stage_id, rc.get("degraded_reason", "unknown"),
                )
                # 发送降级事件到前端，让用户知晓产出质量下降
                await emit_event("stage:resource-degraded", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "reason": rc.get("degraded_reason", "unknown"),
                    "fallbacks": rc.get("fallbacks", []),
                    "available": rc.get("available", []),
                    "hint": "该阶段使用了降级方案，可视化产出可能不完整",
                })

            if not rc.get("ok") and not rc.get("fallbacks"):
                err_msg = (
                    f"Visual resource check failed for stage {stage_id}: "
                    f"no image generation or diagram rendering channel available. "
                    f"Check result: {json.dumps(rc, ensure_ascii=False)}"
                )
                logger.error("[pipeline] %s", err_msg)
                await emit_event("stage:error", {
                    "taskId": task_id, "stageId": stage_id,
                    "error": err_msg, "blocked": True,
                })
                return {
                    "ok": False,
                    "blocked": True,
                    "error": err_msg,
                    "resource_check": rc,
                }
        except Exception as rce:
            logger.warning("[pipeline] Resource check failed for %s: %s", stage_id, rce)

    # 阶段超时（从配置获取，不限制 Claude Code 的执行时间）
    _stage_timeout = STAGE_TIMEOUT_SECONDS.get(stage_id, DEFAULT_STAGE_TIMEOUT)

    # --- Layer 4: LLM Call (with optional AgentRuntime tool loop) ---
    llm_result = None
    try:
        from ..agents.seed import AGENT_TOOLS
        agent_key = stage_conf.get("agent", "")
        stage_agent_id = _AGENT_KEY_TO_SEED_ID.get(agent_key, "")
        agent_tools = AGENT_TOOLS.get(stage_agent_id, [])

        # Add task worktree to sandbox so file tools work in the right directory
        if task_worktree and agent_tools:
            try:
                from .tools.sandbox import add_allowed_dir
                add_allowed_dir(str(task_worktree))
            except Exception as e:
                logger.warning("[pipeline] 无法将工作目录注册到沙箱: %s", e)

            # Inject workspace path into system prompt so the agent writes to the right place
            _tool_stages = {"design", "development", "testing", "deployment", "architecture"}
            if stage_id in _tool_stages:
                if stage_id == "design":
                    system_prompt += (
                        f"\n\n## 工作目录\n"
                        f"任务根目录: `{task_worktree}`\n"
                        f"- UI 规格 Markdown 通过工具写入 `{task_worktree}/docs/`（如已有 ui_spec 工件也可）。\n"
                        f"- 概念视觉稿：优先调用 `generate_image_asset`，文件落在 `{task_worktree}/screenshots/generated/`。\n"
                        f"- 文件读写请使用上述绝对路径。\n"
                    )
                else:
                    system_prompt += (
                        f"\n\n## 工作目录\n"
                        f"你的工作目录是: `{task_worktree}`\n"
                        f"所有文件操作请使用此目录的绝对路径。"
                        f"代码文件写入 `{task_worktree}/src/` 目录。\n"
                        f"配置文件写入 `{task_worktree}/config/` 目录。"
                    )

        # Load MCP tools from DB for this agent
        mcp_defs: dict = {}
        mcp_handlers: dict = {}
        if stage_agent_id:
            try:
                from ..models.agent import AgentMcp
                from .mcp_client import build_tool_handlers
                from sqlalchemy import select as sa_select

                mcp_rows = (await db.execute(
                    sa_select(AgentMcp).where(
                        AgentMcp.agent_id == stage_agent_id,
                        AgentMcp.enabled.is_(True),
                    )
                )).scalars().all()
                if mcp_rows:
                    records = [
                        {"id": str(r.id), "name": r.name, "server_url": r.server_url,
                         "tools": r.tools or [], "config": r.config or {}, "enabled": True}
                        for r in mcp_rows
                    ]
                    mcp_defs, mcp_handlers = await build_tool_handlers(records, fetch_if_empty=True)
                    logger.info("[pipeline] Loaded %d MCP tools for %s", len(mcp_defs), stage_agent_id)
            except Exception as mcp_err:
                logger.warning("[pipeline] MCP tool loading failed for %s: %s", stage_agent_id, mcp_err)

        # --- Layer 4 (pre): Claude Code execution for development stage ---
        # Call Claude Code FIRST for development stage to write real code to worktree.
        # If Claude Code succeeds and writes files, we SKIP the LLM/AgentRuntime
        # content generation to prevent markdown from overwriting real code output.
        cc_written_files: List[str] = []
        cc_job_id: str = ""
        _skip_llm_for_dev = False
        _cond_dev = (stage_id == "development")
        _cond_wt = bool(task_worktree)
        logger.info("[pipeline] Claude Code check stage=%s dev=%s wt=%s", stage_id, _cond_dev, _cond_wt)
        if _cond_dev and _cond_wt:
            try:
                from .codegen.codegen_agent import CodeGenAgent

                logger.info("[pipeline] CodeGenAgent starting for stage=%s worktree=%s", stage_id, task_worktree)

                await emit_event("stage:claude-code-start", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "workDir": str(task_worktree),
                    "label": "🚀 CodeGenAgent 正在生成代码...",
                })

                codegen = CodeGenAgent()
                codegen_result = await codegen.generate_from_pipeline(
                    task_id=task_id,
                    task_title=task_title,
                    pipeline_outputs=previous_outputs or {},
                    template_id=None,
                    use_claude_code=True,
                    existing_project_dir=str(task_worktree),
                )

                if codegen_result.get("ok"):
                    cc_written_files = codegen_result.get("files_written", [])
                    cc_job_id = codegen_result.get("job_id", "")
                    engine = codegen_result.get("engine", "unknown")
                    claude_summary = codegen_result.get("claude_output", "")[:2000]

                    content = (
                        f"## CodeGenAgent 执行结果（引擎: {engine}）\n\n"
                        f"- **Job ID**: {cc_job_id}\n"
                        f"- **状态**: success\n"
                        f"- **写入文件数**: {len(cc_written_files)}\n"
                        f"- **引擎**: {engine}\n\n"
                        f"### 文件列表\n\n"
                        f"```\n{chr(10).join(cc_written_files)}\n```\n\n"
                        f"### 输出摘要\n\n```\n{claude_summary}\n```\n"
                    )
                    _skip_llm_for_dev = True
                    logger.info("[pipeline] CodeGenAgent succeeded with %d files via %s, skipping LLM", len(cc_written_files), engine)
                    await emit_event("stage:claude-code-done", {
                        "taskId": task_id,
                        "stageId": stage_id,
                        "writtenFiles": cc_written_files,
                        "jobId": cc_job_id,
                    })
                else:
                    error_msg = codegen_result.get("error", "unknown error")
                    logger.warning("[pipeline] CodeGenAgent failed: %s", error_msg)
                    await emit_event("stage:claude-code-error", {
                        "taskId": task_id,
                        "stageId": stage_id,
                        "error": error_msg,
                    })
                    # Fall through to AgentRuntime/LLM fallback
            except Exception as cc_err:
                logger.warning("[pipeline] CodeGenAgent execution failed for %s: %s", task_id, cc_err)
                await emit_event("stage:claude-code-error", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "error": str(cc_err),
                })
                # Non-blocking: continue with AgentRuntime/LLM content if CodeGenAgent fails

        # --- Layer 4.5: AgentRuntime / LLM (skipped for development if Claude Code wrote files) ---
        if _skip_llm_for_dev:
            # Real code already written by Claude Code; skip LLM to avoid markdown overwrite.
            # Estimate tokens from the file count and approximate content
            from .token_tracker import _token_estimate_from_chars as _est_tok
            prompt_tokens = _est_tok(system_prompt or "") if system_prompt else 100
            # Rough estimate: ~200 tokens per code file
            completion_tokens = len(cc_written_files) * 200 if cc_written_files else 0
            logger.info("[pipeline] development stage skipped LLM/AgentRuntime because Claude Code wrote %d files", len(cc_written_files))

        # --- Layer 4.6: Testing stage build verification ---
        # Before the testing agent generates a report, try to build the code
        # that was written in the development stage. If build fails, auto-fix.
        # Phase 4 (4.2b): max 2 auto-fix retries; if both fail → return
        # stage failure with build_log_summary.
        if stage_id == "testing" and task_worktree:
            try:
                from .codegen.codegen_agent import CodeGenAgent
                codegen = CodeGenAgent()
                build_cmd = detect_build_command(task_worktree)
                if build_cmd:
                    logger.info("[pipeline] Testing stage build attempt: %s in %s", build_cmd, task_worktree)
                    build_result = await codegen.run_build(str(task_worktree), build_cmd)
                    build_log = build_result.get("output", "")
                    build_ok = build_result.get("ok", False)

                    # Phase 4.2b: auto-fix loop, max 2 retries
                    build_log_path = os.path.join(str(task_worktree), "build.log")
                    fix_attempts = 0
                    while not build_ok and fix_attempts < 2:
                        fix_attempts += 1
                        logger.warning("[pipeline] Build failed, auto-fix attempt %d/2", fix_attempts)
                        fix_result = await codegen.auto_fix(
                            task_id=task_id,
                            project_dir=str(task_worktree),
                            build_log_path=build_log_path,
                            attempt=fix_attempts,
                        )
                        if not fix_result.get("ok"):
                            logger.warning("[pipeline] Auto-fix attempt %d failed: %s", fix_attempts,
                                           fix_result.get("output", "")[:300])
                        # Retry build regardless (auto_fix may have partially fixed)
                        build_result = await codegen.run_build(str(task_worktree), build_cmd)
                        build_log = build_result.get("output", "")
                        build_ok = build_result.get("ok", False)
                        if build_ok:
                            logger.info("[pipeline] Build passed after auto-fix attempt %d", fix_attempts)
                            break

                    if not build_ok:
                        # Phase 4.2b: write failing build.log, but continue — let testing agent see it
                        _write_build_log_to_disk(str(task_worktree), build_log)
                        build_log_summary = build_log[:2000] if build_log else "no build output"
                        logger.warning("[pipeline] Build failed after %d retries — letting testing agent analyze",
                                       fix_attempts)
                        await emit_event("stage:degraded", {
                            "taskId": task_id, "stageId": stage_id,
                            "reason": "build_failed",
                            "message": f"Build failed after {fix_attempts} retries",
                            "buildLogSummary": build_log_summary[:500],
                        })

                    # Inject build result into user_message so the testing agent sees it
                    build_section = (
                        f"\n\n## 实际构建结果（自动执行）\n\n"
                        f"构建命令: `{build_cmd}`\n"
                        f"构建状态: {'✅ 通过' if build_ok else '❌ 失败'}\n"
                        f"构建日志:\n```\n{build_log[:4000]}\n```\n"
                    )
                    user_message += build_section
                    if build_ok:
                        await emit_event("stage:build-result", {
                            "taskId": task_id,
                            "stageId": stage_id,
                            "buildOk": build_ok,
                            "buildCmd": build_cmd,
                        })
                else:
                    logger.info("[pipeline] No build command detected for testing stage in %s", task_worktree)
            except Exception as build_err:
                logger.warning("[pipeline] Testing stage build check failed: %s", build_err)

        if _skip_llm_for_dev:
            # Already handled above; keep this branch so AgentRuntime/LLM is skipped
            pass
        elif agent_tools:
            from .agent_runtime import AgentRuntime
            _max_steps = 8
            if stage_agent_id in ("Agent-acceptance", "Agent-devops", "Agent-qa"):
                _max_steps = 14
            runtime = AgentRuntime(
                agent_id=stage_agent_id or stage_id,
                system_prompt=system_prompt,
                tools=agent_tools,
                model_preference={"execution": model},
                max_steps=_max_steps,
                temperature=0.7,
                task_id=task_id,
                role=role,
                dynamic_tools=mcp_defs or None,
                dynamic_handlers=mcp_handlers or None,
            )
            runtime_result = await asyncio.wait_for(
                runtime.execute(
                    db,
                    task=user_message,
                    context=previous_outputs,
                    image_attachments=att_images if att_images else None,
                    task_id=task_id,
                ),
                timeout=_stage_timeout,
            )
            if not runtime_result.get("ok"):
                raise RuntimeError(runtime_result.get("error", "AgentRuntime failed"))
            content = runtime_result.get("content", "")
            # AgentRuntime 不返回精确 token 数，用内容长度估算
            from .token_tracker import _token_estimate_from_chars as _est_tok
            completion_tokens = _est_tok(content) if content else 0
            prompt_tokens = _est_tok(system_prompt or "") if system_prompt else max(1, completion_tokens // 2)

            # --- Testing stage: auto-backtrack on explicit NEEDS WORK ---
            if stage_id == "testing" and content:
                _testing_failed = any(kw in content for kw in (
                    "NEEDS WORK", "NEEDS WORK ❌", "❌ FAIL", "FAILED ❌",
                ))
                if _testing_failed:
                    logger.warning("[pipeline] Testing stage self-reported NEEDS WORK, reverting to development")
                    await emit_event("stage:testing-failed", {
                        "taskId": task_id,
                        "stageId": stage_id,
                        "reason": "Testing stage reported NEEDS WORK",
                    })
                    return {
                        "ok": False,
                        "error": "Testing failed: NEEDS WORK",
                        "revert_to": "development",
                    }
        else:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]
            api_url = app_settings.llm_api_url if (tier == "local" or resolved_provider == "local") else ""

            async def _on_provider_fallback(payload: Dict[str, Any]) -> None:
                """Surface provider rotation to the UI. Without this the user
                sees the same 'failed' state no matter how many times the
                stage actually retried under the hood."""
                await emit_event("stage:provider-fallback", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "agent": agent_name,
                    **payload,
                })

            # --- Layer: Ruflo memory enrichment (before LLM call) ---
            if app_settings.ruflo_enabled:
                try:
                    system_prompt = await _ruflo_memory_enrich(
                        task_id=task_id,
                        stage_id=stage_id,
                        system_prompt=system_prompt,
                        stage_content=user_message,
                    )
                except Exception as ruflo_err:
                    logger.warning("[ruflo] Enrichment skipped: %s", ruflo_err)
            # Rebuild messages with enriched system prompt
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]

            _reasoning_keywords = ("reasoning", "distilled", "thinking", "o1", "o3")
            _is_reasoning_model = any(k in model.lower() for k in _reasoning_keywords)
            stage_max_tokens = 16384 if _is_reasoning_model else 8192

            llm_result = await asyncio.wait_for(
                _stream_stage_output(
                    task_id=task_id,
                    stage_id=stage_id,
                    model=model,
                    messages=messages,
                    max_tokens=stage_max_tokens,
                    api_url=api_url,
                    image_attachments=att_images if att_images else None,
                ),
                timeout=_stage_timeout,
            )
            if llm_result.get("error"):
                # Include the provider trail so the surfaced error tells the
                # operator which providers were tried and why each failed.
                trail = llm_result.get("tried_providers") or []
                trail_summary = "; ".join(
                    f"{t.get('provider')}/{t.get('model')}={t.get('status')}"
                    for t in trail
                ) if trail else ""
                detail = llm_result["error"]
                raise RuntimeError(
                    f"LLM error after fallbacks: {detail}"
                    + (f" | tried: {trail_summary}" if trail_summary else "")
                )
            content = llm_result.get("content", "")
            token_usage = llm_result.get("usage") or {}
            prompt_tokens = token_usage.get("prompt_tokens", 0)
            completion_tokens = token_usage.get("completion_tokens", 0)
            # 当 LLM 不返回 token 数时（如本地 LM Studio），用内容长度估算
            if not prompt_tokens and not completion_tokens and content:
                from .token_tracker import _token_estimate_from_chars as _est_tok
                completion_tokens = _est_tok(content)
                # 估算 prompt token（假设输入约为输出的 2-3 倍）
                prompt = system_prompt + "\n".join(
                    m.get("content", "") for m in (messages or []) if isinstance(m, dict)
                )
                prompt_tokens = _est_tok(prompt) if prompt else max(1, completion_tokens // 2)
            # If a fallback succeeded, replace the active model name so cost
            # accounting and the trace span credit the actual provider used.
            if llm_result.get("fell_back") and llm_result.get("model"):
                model = llm_result["model"]

        # --- Layer 4.7: Deployment stage — extract Docker/deploy files to worktree ---
        if stage_id == "deployment" and task_worktree and content:
            _deploy_files = extract_code_blocks_from_content(content)
            if _deploy_files:
                _deploy_dir = task_worktree / "deploy"
                _deploy_dir.mkdir(parents=True, exist_ok=True)
                for _fpath, _fcontent in _deploy_files.items():
                    _target = (_deploy_dir / _fpath).resolve()
                    if str(_target).startswith(str(_deploy_dir)):
                        _target.parent.mkdir(parents=True, exist_ok=True)
                        _target.write_text(_fcontent, encoding="utf-8")
                        logger.info("[pipeline] Deployed config: deploy/%s", _fpath)
                if _deploy_files:
                    await emit_event("stage:deploy-files-written", {
                        "taskId": task_id,
                        "stageId": stage_id,
                        "files": list(_deploy_files.keys()),
                    })

    except asyncio.TimeoutError:
        timeout_msg = (
            f"阶段 {stage_id} 执行超时（{_stage_timeout}秒）。"
            f"这可能是因为 LLM 响应过慢或模型服务暂时不可用。"
            f"建议：1) 检查模型服务状态 2) 调大超时时间（环境变量 PIPELINE_STAGE_TIMEOUT_SECONDS）"
            f"3) 重试该阶段。"
        )
        logger.error("[pipeline] Stage %s timed out after %ds", stage_id, _stage_timeout)
        await complete_span(span.span_id, status="timeout", error=timeout_msg)
        await emit_event("stage:error", {
            "taskId": task_id,
            "stageId": stage_id,
            "agent": agent_name,
            "error": timeout_msg,
            "errorKind": "timeout",
            "timeoutSeconds": _stage_timeout,
        })
        return {"ok": False, "error": timeout_msg, "errorKind": "timeout"}
    except Exception as e:
        logger.error(f"[pipeline] Stage {stage_id} LLM call failed: {e}")
        await complete_span(span.span_id, status="failed", error=str(e))
        await emit_event("stage:error", {
            "taskId": task_id,
            "stageId": stage_id,
            "agent": agent_name,
            "error": str(e),
        })
        return {"ok": False, "error": humanize_error(str(e)), "_rawError": str(e)}

    # (Layer 4.5 code moved to before Layer 4 - see above)
    if tier == "local" or resolved_provider == "local":
        api_url = app_settings.llm_api_url or ""
        if api_url and needs_output_top_up(stage_id, content):
            try:
                content = await _top_up_stage_output(
                    stage_id=stage_id,
                    model=model,
                    api_url=api_url,
                    system_prompt=system_prompt,
                    partial_content=content,
                )
            except Exception as top_up_err:
                logger.warning(
                    "[pipeline] Stage %s output top-up failed: %s",
                    stage_id, top_up_err,
                )

    # --- Layer 5 + 5.6 + 7: Self-Verify, Cross-Stage, Worktree Quality, Top-up ---
    content, verification = await _run_stage_verification(
        stage_id=stage_id,
        role=role,
        task_id=task_id,
        content=content,
        previous_outputs=previous_outputs,
        task_worktree=str(task_worktree) if task_worktree else None,
        tier=tier,
        resolved_provider=resolved_provider,
        model=model,
        system_prompt=system_prompt,
        cc_written_files=cc_written_files,
        skip_llm_for_dev=_skip_llm_for_dev,
    )

    # --- Layer 3 + 6: Tool Schema (record execution) ---
    provider = llm_result.get("provider", "openai") if llm_result else "openai"
    cost_estimate = estimate_cost(provider, model, prompt_tokens, completion_tokens)

    # Update Cost Governor ledger (best-effort; never breaks the pipeline)
    try:
        await record_stage_cost(
            task_id, stage_id=stage_id, role=role, model=model,
            cost_usd=cost_estimate, tokens=prompt_tokens + completion_tokens,
        )
    except Exception as cost_err:
        logger.debug(f"[pipeline] cost_governor record failed for {stage_id}: {cost_err}")

    span_meta = {}
    if stage_id == "development":
        if cc_job_id:
            span_meta["claude_code_job_id"] = cc_job_id
        if cc_written_files:
            span_meta["claude_code_files_written"] = len(cc_written_files)

    # --- Layer 8: Complete trace span ---
    await complete_span(
        span.span_id,
        status="completed",
        output_length=len(content),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_estimate,
        verify_status=verification.overall_status.value,
        verify_checks=[c.dict() for c in verification.checks],
        guardrail_level=guardrail_result.get("level", GuardrailLevel.AUTO_APPROVE).value
            if isinstance(guardrail_result.get("level"), GuardrailLevel)
            else guardrail_result.get("level", "auto_approve"),
        metadata_updates=span_meta or None,
    )

    # --- Layer 9: Memory → store output for future retrieval ---
    quality_score = 0.8 if verification.overall_status == VerifyStatus.PASS else 0.5 if verification.overall_status == VerifyStatus.WARN else 0.2
    await store_memory(
        db,
        task_id=task_id,
        stage_id=stage_id,
        role=role,
        title=task_title,
        content=content,
        tags=[stage_id, role, tier],
        quality_score=quality_score,
    )

    # Store stage output in working memory for subsequent stages
    await set_working_context(task_id, f"stage_{stage_id}_output", content[:2000])
    await set_working_context(task_id, f"stage_{stage_id}_model", model)

    # --- Layer 9.5: Ruflo — store output in cross-session memory ---
    if app_settings.ruflo_enabled:
        try:
            await _ruflo_memory_enrich(
                task_id=task_id,
                stage_id=stage_id,
                system_prompt="",
                store_output=True,
                output_text=content,
            )
        except Exception as ruflo_err:
            logger.debug("[ruflo] Post-stage store skipped: %s", ruflo_err)

    # --- Layer 9.5: Visual Generator → generate mockups/diagrams (Phase 5 upgrade) ---
    if stage_id in ("design", "architecture") and content:
        try:
            from .ui_visualizer import UiVisualizer
            from .artifact_writer import _write_one_artifact as _write_art_custom

            viz = UiVisualizer(
                workspace_root=app_settings.workspace_root,
                task_worktree=str(task_worktree) if task_worktree else "",
            )

            if stage_id == "design":
                # Design stage → UI mockup + design tokens + screen plan
                result = await viz.generate_mockup(
                    task_id=task_id, stage_id=stage_id,
                    design_spec=content,
                    project_name=task_title,
                )
                design_tokens = viz.generate_design_tokens(content)
                screen_plan = viz.generate_screen_plan(content)

                has_real_image = result.get("ok") and result["imagePath"]
                is_degraded = result.get("degraded", False)
                has_html = bool(result.get("htmlPath"))

                if has_real_image:
                    await _write_art_custom(
                        db, task_id=str(task_id), stage_id=stage_id,
                        artifact_type="ui_mockup",
                        content=f"![UI 设计稿]({result['imagePath']})",
                        storage_path=result["imagePath"],
                        agent_name=agent_name,
                        metadata_json={
                            "filePath": result["imagePath"],
                            "prompt": result["prompt"],
                            "design_tokens": design_tokens,
                            "screen_plan": screen_plan,
                            "degraded": False,
                        },
                    )
                    logger.info("[ui-visualizer] UI mockup PNG generated for %s", task_id[:12])

                if has_html:
                    mockup_kind = "html_supplement" if has_real_image else "degraded_fallback"
                    await _write_art_custom(
                        db, task_id=str(task_id), stage_id=stage_id,
                        artifact_type="ui_mockup_html",
                        content=f"UI 可交互原型:\n{result['htmlPath']}",
                        storage_path=result["htmlPath"],
                        agent_name=agent_name,
                        metadata_json={
                            "filePath": result["htmlPath"],
                            "mockup_kind": mockup_kind,
                            "design_tokens": design_tokens,
                            "screen_plan": screen_plan,
                        },
                    )
                    if not has_real_image:
                        # Write ui_mockup artifact pointing to HTML fallback, marked degraded
                        await _write_art_custom(
                            db, task_id=str(task_id), stage_id=stage_id,
                            artifact_type="ui_mockup",
                            content=f"[降级] UI 设计稿（HTML 保底模板，非真实设计稿）:\n{result['htmlPath']}",
                            storage_path=result["htmlPath"],
                            agent_name=agent_name,
                            metadata_json={
                                "filePath": result["htmlPath"],
                                "prompt": result["prompt"],
                                "design_tokens": design_tokens,
                                "screen_plan": screen_plan,
                                "degraded": True,
                                "degraded_reason": "no_image_gen_api_available",
                            },
                        )
                    logger.info("[ui-visualizer] UI mockup HTML %s for %s",
                                "supplement" if has_real_image else "fallback(degraded)", task_id[:12])

                if not has_real_image and not has_html:
                    err_msg = "Design stage: no UI mockup generated (both PNG and HTML failed)"
                    logger.warning("[pipeline] %s — continuing with LLM text output only", err_msg)
                    await emit_event("stage:degraded", {
                        "taskId": task_id, "stageId": stage_id,
                        "reason": "no_mockup_available",
                        "message": err_msg,
                    })

                if is_degraded:
                    logger.warning(
                        "[pipeline] Design stage %s degraded: no image gen API available, "
                        "using HTML template fallback (not a real mockup)", task_id[:12])
                    await emit_event("stage:degraded", {
                        "taskId": task_id,
                        "stageId": stage_id,
                        "reason": "no_image_gen_api_available",
                        "message": "UI 设计稿降级为 HTML 保底模板，非真实设计稿。请配置 OPENAI_API_KEY 或 GEMINI_API_KEY 以生成真实设计稿。",
                    })

                # Generate .pen design file (Pencil-compatible) alongside mockups
                try:
                    from .pen_generator import generate_pen_file as _gen_pen
                    pen_result = _gen_pen(
                        task_id=task_id,
                        task_worktree=str(task_worktree) if task_worktree else "",
                        design_spec=content,
                        project_name=task_title,
                        design_tokens=design_tokens,
                    )
                    if pen_result and pen_result.get("ok"):
                        await _write_art_custom(
                            db, task_id=str(task_id), stage_id=stage_id,
                            artifact_type="attachment",
                            content=f"Pencil 设计文件 (.pen)\n{pen_result['penPath']}",
                            storage_path=pen_result["relativePath"],
                            agent_name=agent_name,
                            metadata_json={
                                "penPath": pen_result["penPath"],
                                "relativePath": pen_result["relativePath"],
                                "format": "pen",
                                "tool": "pencil",
                                "degraded": False,
                            },
                        )
                        logger.info("[pipeline] .pen design file generated for %s: %s",
                                    task_id[:12], pen_result["penPath"])
                except Exception as pen_err:
                    logger.warning("[pipeline] .pen generation skipped: %s", pen_err)

            elif stage_id == "architecture":
                # Architecture stage → architecture diagrams + structured data + consistency
                arch_result = await viz.generate_all_architecture_artifacts(
                    task_id=task_id, stage_id=stage_id,
                    arch_spec=content,
                    project_name=task_title,
                )
                diagram_result = arch_result.get("diagram", {})

                if diagram_result.get("ok") and diagram_result.get("htmlPath"):
                    # Write architecture.mmd
                    mermaid_raw = diagram_result.get("mermaidRaw", {})
                    if mermaid_raw.get("architecture"):
                        await _write_art_custom(
                            db, task_id=str(task_id), stage_id=stage_id,
                            artifact_type="architecture",
                            content=f"```mermaid\n{mermaid_raw['architecture']}\n```\n\n## Sequence\n\n```mermaid\n{mermaid_raw.get('sequence', '')}\n```\n\n## Deployment\n\n```mermaid\n{mermaid_raw.get('deployment', '')}\n```",
                            storage_path="",
                            agent_name=agent_name,
                            metadata_json={"format": "mermaid", "diagrams": list(mermaid_raw.keys())},
                        )

                    # Write architecture.html
                    await _write_art_custom(
                        db, task_id=str(task_id), stage_id=stage_id,
                        artifact_type="architecture_diagram",
                        content=f"架构图:\n{diagram_result['htmlPath']}",
                        storage_path=diagram_result["htmlPath"],
                        agent_name=agent_name,
                        metadata_json={
                            "filePath": diagram_result["htmlPath"],
                            "componentCount": diagram_result.get("componentCount", 0),
                            "flowCount": diagram_result.get("flowCount", 0),
                            "api_contract": arch_result.get("api_contract", {}),
                            "data_model": arch_result.get("data_model", {}),
                            "file_plan": arch_result.get("file_plan", {}),
                            "consistency_ok": arch_result.get("consistency_ok", True),
                            "consistency_issues": arch_result.get("consistency_issues", []),
                        },
                    )

                    # Phase 5: consistency check — warn but don't block pipeline
                    if not arch_result.get("consistency_ok", True):
                        issues = arch_result.get("consistency_issues", [])
                        logger.warning(
                            "[pipeline] Architecture consistency check had issues: %s",
                            "; ".join(issues))
                        await emit_event("stage:degraded", {
                            "taskId": task_id, "stageId": stage_id,
                            "reason": "consistency_issues",
                            "consistency_issues": issues,
                        })

                    logger.info("[ui-visualizer] Architecture diagrams + structured data generated for %s (%d components, %d flows)", task_id[:12], diagram_result.get("componentCount", 0), diagram_result.get("flowCount", 0))
                else:
                    err_msg = "Architecture stage: no architecture diagram generated"
                    logger.warning("[pipeline] %s — continuing with LLM text output only", err_msg)
                    await emit_event("stage:degraded", {
                        "taskId": task_id, "stageId": stage_id,
                        "reason": "no_diagram_available",
                        "message": err_msg,
                    })

        except Exception as viz_err:
            logger.warning("[ui-visualizer] Visual generation failed for %s: %s — continuing", stage_id, viz_err)
            await emit_event("stage:degraded", {
                "taskId": task_id, "stageId": stage_id,
                "reason": "visual_generation_error",
                "message": str(viz_err),
            })

    # --- Phase 6: QA Real Execution (post-LLM, pre-artifact-write) ---
    if stage_id == "testing" and task_worktree:
        try:
            from .qa_executor import QaExecutor
            from .artifact_writer import write_qa_artifacts

            qa = QaExecutor(str(task_worktree))
            qa_result = await qa.run_full_qa()
            logger.info(
                "[pipeline] Phase 6 QA complete for %s: ok=%s, blocked=%s",
                task_id[:12], qa_result.get("ok"), qa_result.get("blocked"),
            )

            # Write QA artifacts to DB (test_report, build_log, test_log, screenshot, console_errors)
            qa_arts = await write_qa_artifacts(db, str(task_id), str(task_worktree), qa_result)
            if qa_arts:
                logger.info("[pipeline] Wrote %d Phase 6 QA artifacts for %s", len(qa_arts), task_id[:12])

            # Blocked (no source_manifest / missing tools) is a real gate
            # failure. Continuing would let the pipeline report delivery
            # without executable evidence.
            if qa_result.get("blocked"):
                err_msg = qa_result.get("error", "QA resources unavailable")
                logger.error("[pipeline] QA blocked for %s: %s", task_id[:12], err_msg)
                await emit_event("stage:error", {
                    "taskId": task_id, "stageId": stage_id,
                    "reason": "qa_blocked",
                    "error": err_msg,
                    "blocked": True,
                    "resource_check": qa_result.get("resource_check", {}),
                })
                return {
                    "ok": False,
                    "blocked": True,
                    "error": humanize_error(f"qa blocked: {err_msg}"), "_rawError": f"QA blocked: {err_msg}",
                    "qa_result": qa_result,
                    "revert_to": "development",
                }
            # Failed install/build/test/browser smoke means the testing stage
            # failed; do not let LLM prose override real command results.
            elif not qa_result.get("ok"):
                failed_step = qa_result.get("failed_step", "unknown")
                err_msg = qa_result.get("error", "QA execution failed")
                logger.error("[pipeline] QA failed for %s at %s: %s",
                             task_id[:12], failed_step, err_msg)
                await emit_event("stage:error", {
                    "taskId": task_id, "stageId": stage_id,
                    "reason": "qa_failed",
                    "error": err_msg,
                    "failed_step": failed_step,
                })
                return {
                    "ok": False,
                    "error": humanize_error(f"QA failed at {failed_step}: {err_msg}"), "_rawError": f"QA failed at {failed_step}: {err_msg}",
                    "qa_result": qa_result,
                    "revert_to": "development",
                }

            # Success — inject QA report into content so artifact writer gets it
            test_report = qa_result.get("report_markdown", "")
            if test_report:
                content = (content or "") + f"\n\n## QA Real Execution Results\n\n{test_report}\n"

        except ImportError as ie:
            logger.error("[pipeline] qa_executor not available: %s", ie)
            await emit_event("stage:error", {
                "taskId": task_id,
                "stageId": stage_id,
                "error": f"qa_executor_unavailable: {ie}",
            })
            return {"ok": False, "blocked": True, "error": f"qa_executor_unavailable: {ie}"}
        except Exception as qa_err:
            logger.error("[pipeline] Phase 6 QA execution failed: %s", qa_err)
            await emit_event("stage:qa-error", {
                "taskId": task_id,
                "stageId": stage_id,
                "error": str(qa_err),
            })
            return {"ok": False, "error": f"Phase 6 QA execution failed: {qa_err}"}

    # --- Phase 7: Deploy closure (post-LLM, pre-artifact-write) ---
    if stage_id == "deployment" and task_worktree:
        try:
            from .deploy.local_preview import LocalPreview, check_deploy_resources
            from .deploy.vercel import deploy_to_vercel
            from .artifact_writer import write_deploy_artifacts

            # 1. Resource check
            deploy_rc = check_deploy_resources()
            if not deploy_rc.get("any_available"):
                err_raw = "No deploy channel available (local nor Vercel)"
                logger.error("[pipeline] No deploy channel available for %s", task_id[:12])
                await emit_event("stage:error", {
                    "taskId": task_id, "stageId": stage_id,
                    "reason": "no_deploy_channel",
                    "error": humanize_error("no deploy channel"),
                    "blocked": True,
                    "resource_check": deploy_rc,
                })
                return {
                    "ok": False,
                    "blocked": True,
                    "error": humanize_error("no deploy channel"),
                    "_rawError": err_raw,
                    "resource_check": deploy_rc,
                }

            # 2. Only attempt deploy if at least one channel is available
            if deploy_rc.get("any_available"):
                deploy_result = None

                # Vercel preferred when token is available
                vercel_token = os.environ.get("VERCEL_TOKEN", "")
                if vercel_token:
                    logger.info("[pipeline] Deploying %s via Vercel", task_id[:12])
                    try:
                        project_name = f"agenthub-{task_id[:12]}"
                        vercel_result = await deploy_to_vercel(
                            project_dir=str(task_worktree),
                            project_name=project_name,
                            token=vercel_token,
                            production=False,
                        )
                        if vercel_result.get("ok"):
                            deploy_result = {
                                "url": vercel_result.get("url", ""),
                                "provider": "vercel",
                                "environment": "preview",
                                "health_status": "healthy",
                                "deployed_at": datetime.utcnow().isoformat(),
                                "screenshot_path": "",
                                "ok": True,
                            }
                            logger.info("[pipeline] Vercel deploy succeeded: %s", deploy_result["url"])
                        else:
                            vercel_error = vercel_result.get("error", "")
                            vercel_status = vercel_result.get("status", 0)
                            if vercel_status in (401, 403):
                                err_raw = (
                                    f"Vercel auth failed (status={vercel_status}): "
                                    f"{vercel_error[:500]}. Check VERCEL_TOKEN validity."
                                )
                                logger.error("[pipeline] %s", err_raw)
                                await emit_event("stage:error", {
                                    "taskId": task_id,
                                    "stageId": stage_id,
                                    "reason": "vercel_auth_failed",
                                    "error": humanize_error("vercel auth failed"),
                                    "provider": "vercel",
                                })
                                return {"ok": False, "blocked": True, "error": humanize_error("vercel auth failed"), "_rawError": err_raw}
                            elif vercel_status == 429:
                                logger.warning("[pipeline] Vercel rate limited (429), falling back to local")
                            else:
                                logger.warning(
                                    "[pipeline] Vercel deploy failed (status=%s), falling back to local: %s",
                                    vercel_status, vercel_error[:200])
                            await emit_event("stage:deploy-fallback", {
                                "taskId": task_id,
                                "stageId": stage_id,
                                "fromProvider": "vercel",
                                "toProvider": "local",
                                "status": vercel_status,
                                "error": vercel_error[:500],
                            })
                    except Exception as ve:
                        logger.warning("[pipeline] Vercel deploy exception, falling back to local: %s", ve)
                        await emit_event("stage:deploy-fallback", {
                            "taskId": task_id,
                            "stageId": stage_id,
                            "fromProvider": "vercel",
                            "toProvider": "local",
                            "error": str(ve)[:500],
                        })

                # Fallback to local preview
                preview = None
                if deploy_result is None:
                    logger.info("[pipeline] Deploying %s via local preview", task_id[:12])
                    preview = LocalPreview(str(task_worktree))
                    local_result = await preview.deploy()

                    if local_result.ok:
                        deploy_result = {
                            "url": local_result.url,
                            "provider": "local",
                            "environment": "preview",
                            "health_status": local_result.health_status,
                            "deployed_at": local_result.deployed_at,
                            "screenshot_path": local_result.screenshot_path,
                            "port_used": local_result.port_used,
                            "ok": True,
                        }
                    else:
                        await preview.close()
                        err_msg = local_result.error or "Local preview failed"
                        logger.error("[pipeline] Local preview failed: %s", err_msg)
                        await emit_event("stage:error", {
                            "taskId": task_id, "stageId": stage_id,
                            "reason": "local_preview_failed",
                            "error": err_msg,
                            "provider": "local",
                        })
                        return {"ok": False, "error": humanize_error(f"Local preview failed: {err_msg}"), "_rawError": f"Local preview failed: {err_msg}"}

                # Write deploy artifacts
                if deploy_result:
                    deploy_arts = await write_deploy_artifacts(
                        db, str(task_id), str(task_worktree), deploy_result,
                    )
                    logger.info("[pipeline] Wrote %d deploy artifacts for %s (provider=%s, url=%s)",
                                len(deploy_arts), task_id[:12],
                                deploy_result.get("provider"),
                                deploy_result.get("url", "")[:50])

                    # Inject deploy info into content for standard artifact write
                    deploy_info = (
                        f"\n\n## 部署结果\n\n"
                        f"- Provider: {deploy_result.get('provider')}\n"
                        f"- URL: {deploy_result.get('url', 'N/A')}\n"
                        f"- Health: {deploy_result.get('health_status')}\n"
                    )
                    content = (content or "") + deploy_info

                    await emit_event("stage:deploy-complete", {
                        "taskId": task_id,
                        "stageId": stage_id,
                        "url": deploy_result.get("url", ""),
                        "provider": deploy_result.get("provider", "unknown"),
                        "healthStatus": deploy_result.get("health_status", "unknown"),
                    })

                    if preview is not None:
                        # Keep local preview alive for interactive/manual
                        # inspection after the stage completes. It will still
                        # be cleaned up when the backend process exits.
                        preview.detach()

        except ImportError as ie:
            logger.error("[pipeline] Deploy modules not available: %s", ie)
            await emit_event("stage:error", {
                "taskId": task_id,
                "stageId": stage_id,
                "error": f"deploy_unavailable: {ie}",
            })
            return {"ok": False, "blocked": True, "error": f"deploy_unavailable: {ie}"}
        except Exception as deploy_err:
            logger.error("[pipeline] Phase 7 deploy failed: %s", deploy_err)
            await emit_event("stage:error", {
                "taskId": task_id,
                "stageId": stage_id,
                "error": str(deploy_err),
            })
            return {"ok": False, "error": humanize_error(f"Phase 7 deploy failed: {deploy_err}"), "_rawError": f"Phase 7 deploy failed: {deploy_err}"}

    # --- Layer 10: Artifact Writer → persist stage output to TaskArtifact ---
    try:
        from .artifact_writer import (
            write_stage_artifacts_v2,
            _write_one_artifact,
            AUX_STAGE_LABELS,
        )

        if stage_id == "development" and cc_written_files:
            written_arts = await write_stage_artifacts_v2(
                db, task_id=task_id, task_title=task_title,
                stage_id=stage_id, content=content, agent_name=agent_name,
            )
            code_link_json = json.dumps({
                "job_id": cc_job_id,
                "files": cc_written_files,
                "worktree": str(task_worktree) if task_worktree else "",
                "generated_at": datetime.utcnow().isoformat(),
            }, ensure_ascii=False, indent=2)
            await _write_one_artifact(
                db, task_id, stage_id, "code_link", code_link_json,
                "docs/code-snapshot.md", agent_name,
            )
            logger.info("[pipeline] Wrote %d artifacts for development stage (incl. code_link with %d files)",
                len(written_arts) + 1, len(cc_written_files))
            if task_worktree:
                from .artifact_writer import write_code_artifacts
                try:
                    code_arts = await write_code_artifacts(
                        db, str(task_id), str(task_worktree), agent_name,
                    )
                    if code_arts:
                        logger.info(
                            "[pipeline] Wrote %d code artifact row(s) from worktree",
                            len(code_arts),
                        )
                except Exception as code_art_err:
                    logger.warning("[pipeline] write_code_artifacts failed: %s", code_art_err)
        elif (content or "").strip() or stage_id in AUX_STAGE_LABELS:
            n = len(await write_stage_artifacts_v2(
                db,
                task_id=task_id,
                task_title=task_title,
                stage_id=stage_id,
                content=content or "",
                agent_name=agent_name,
            ))
            logger.info("[pipeline] Wrote %d artifact row(s) for stage %s", n, stage_id)

        await emit_event("stage:artifact-written", {
            "taskId": task_id,
            "stageId": stage_id,
        })
    except Exception as art_err:
        logger.warning("[pipeline] Artifact write failed for %s: %s", stage_id, art_err)
        try:
            await db.rollback()
        except Exception:
            logger.debug("[pipeline] DB rollback after artifact write failure failed for %s", stage_id, exc_info=True)

    # Default: contract passes.  We update this below when check runs.
    ok_vc: bool = True
    missing_vc: tuple = ()

    if app_settings.artifact_store_v2 and app_settings.artifact_contract_enforce:
        from .artifact_contract import (
            validate_stage_artifact_contract,
            validate_stage_artifact_contract_rules_strict,
        )

        try:
            ok_vc, missing_vc = await validate_stage_artifact_contract(
                db, str(task_id), stage_id,
            )
            if not ok_vc:
                logger.warning(
                    "[pipeline] Artifact contract unmet after stage %s: missing %s",
                    stage_id, missing_vc)
                await emit_event("stage:degraded", {
                    "taskId": task_id, "stageId": stage_id,
                    "reason": "contract_unmet",
                    "message": f"Missing artifacts: {missing_vc}",
                    "contractMissing": missing_vc,
                })

            if app_settings.artifact_contract_rules_strict:
                ok_sr, rules_errs = await validate_stage_artifact_contract_rules_strict(
                    db, str(task_id), stage_id,
                )
                if not ok_sr:
                    logger.warning(
                        "[pipeline] Artifact contract rules violated after stage %s: %s",
                        stage_id, rules_errs)
                    await emit_event("stage:degraded", {
                        "taskId": task_id, "stageId": stage_id,
                        "reason": "contract_rules_violated",
                        "message": f"Rule violations: {rules_errs}",
                        "contractRules": rules_errs,
                    })
        except Exception as contract_err:
            logger.warning(
                "[pipeline] Artifact contract check failed for %s (DB may be in invalid state): %s",
                stage_id, contract_err)
            try:
                await db.rollback()
            except Exception:
                logger.error("[pipeline] DB rollback failed after artifact contract error for %s", stage_id, exc_info=True)

    # F2: When contract check fails in strict mode, return degraded result
    # so the caller knows the stage didn't produce required outputs.
    if (
        app_settings.artifact_store_v2
        and app_settings.artifact_contract_enforce
        and app_settings.artifact_contract_rules_strict
        and not ok_vc
    ):
        logger.warning(
            "[pipeline] F2-contract-block: stage %s has unmet artifacts %s — returning degraded",
            stage_id, missing_vc)
        await emit_event("stage:completed", {
            "taskId": task_id,
            "stageId": stage_id,
            "agent": agent_name,
            "icon": agent_icon,
            "degraded": True,
            "contractMissing": list(missing_vc),
        })
        return {
            "ok": False,
            "degraded": True,
            "stopped_at": stage_id,
            "reason": f"Artifact contract unmet (strict): missing {list(missing_vc)}",
            "contract_missing": list(missing_vc),
            "content": content,
            "model": model,
            "tier": tier,
            "trace_id": trace.trace_id,
            "span_id": span.span_id,
        }

    await emit_event("stage:completed", {
        "taskId": task_id,
        "stageId": stage_id,
        "agent": agent_name,
        "icon": agent_icon,
        "model": model,
        "tier": tier,
        "tokens": prompt_tokens + completion_tokens,
        "costUsd": cost_estimate,
        "verifyStatus": verification.overall_status.value,
    })

    return {
        "ok": True,
        "content": content,
        "model": model,
        "tier": tier,
        "skill_completion_criteria": skill_completion_criteria,
        "verification": {
            "status": verification.overall_status.value,
            "auto_proceed": verification.auto_proceed,
            "checks": [c.dict() for c in verification.checks],
            "suggestions": verification.suggestions,
        },
        "tokens": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": prompt_tokens + completion_tokens,
        },
        "cost_usd": cost_estimate,
        "trace_id": trace.trace_id,
        "span_id": span.span_id,
    }


async def execute_full_pipeline(
    db: AsyncSession,
    *,
    task_id: str,
    task_title: str,
    task_description: str,
    stages: Optional[List[str]] = None,
    available_providers: Optional[List[str]] = None,
    complexity: Optional[str] = None,
    force_continue: bool = False,
    prior_outputs: Optional[Dict[str, str]] = None,
    project_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a full pipeline with all maturation layers.
    Persists each stage result to DB and emits SSE events in real-time.
    When force_continue=True, verification warnings/failures are logged
    but the pipeline continues (used by auto-run).
    prior_outputs: outputs from already-completed stages (used when resuming).
    """
    from ..models.pipeline import PipelineTask, PipelineStage

    if stages is None:
        stages = list(STAGE_ROLE_PROMPTS.keys())

    trace = await start_trace(task_id, task_title)
    outputs: Dict[str, str] = dict(prior_outputs) if prior_outputs else {}
    results: List[Dict[str, Any]] = []

    await emit_event("pipeline:auto-start", {
        "taskId": task_id,
        "title": task_title,
        "stages": stages,
        "agentTeam": [
            {"stage": sid, **AGENT_PROFILES.get(STAGE_ROLE_PROMPTS[sid].get("agent", ""), {})}
            for sid in stages if sid in STAGE_ROLE_PROMPTS
        ],
    })

    # Load the task and its stages from DB
    import uuid as _uuid
    try:
        task_uuid = _uuid.UUID(task_id)
    except ValueError:
        task_uuid = None

    db_task: Optional[PipelineTask] = None
    db_stages: Dict[str, PipelineStage] = {}
    if task_uuid:
        result = await db.execute(
            select(PipelineTask)
            .options(selectinload(PipelineTask.stages))
            .where(PipelineTask.id == task_uuid)
        )
        db_task = result.scalar_one_or_none()
        if db_task:
            db_stages = {s.stage_id: s for s in db_task.stages}

    # Ensure task worktree exists for post-stage hooks
    task_worktree = None
    try:
        from .task_workspace import ensure_task_workspace
        task_worktree = await ensure_task_workspace(task_id, task_title)
    except Exception as ws_err:
        logger.warning("[pipeline] Failed to ensure task workspace: %s", ws_err)

    for stage_id in stages:
        logger.info(f"[pipeline] Executing stage: {stage_id}")
        # ── 双重同行评审设计说明 ──
        # 每个阶段有两处同行评审，这不是重复，而是分工：
        # 1. 早期评审（质量门禁之前，行 3089-3130）：快速把关，在进入昂贵的质量门禁
        #    LLM 调用之前先过滤掉明显不合格的产出。通过则缓存结果跳过第二轮。
        # 2. 后期评审（质量门禁之后，行 3297-3433）：带重试循环 + 反馈注入的深度评审。
        #    如果早期已通过则自动跳过（避免重复调用），仅在早期拒绝或未配置时进入。
        # 这种「早期快速拒绝 + 后期深度修复」的设计可以节省约 50% 的审阅延迟/成本。
        early_peer_review_ok: Optional[Dict[str, Any]] = None

        # Mark current stage as active in DB
        if db_task:
            db_task.current_stage_id = stage_id
            if stage_id in db_stages:
                db_stages[stage_id].status = "active"
                db_stages[stage_id].started_at = datetime.utcnow()
            try:
                await db.flush()
            except Exception as flush_err:
                logger.warning("[pipeline] DB flush failed marking stage active: %s", flush_err)
                try:
                    await db.rollback()
                except Exception:
                    logger.debug("[pipeline] DB rollback after flush failure failed for stage %s", stage_id, exc_info=True)

        result = await execute_stage(
            db,
            task_id=task_id,
            task_title=task_title,
            task_description=task_description,
            stage_id=stage_id,
            previous_outputs=outputs,
            trace=trace,
            available_providers=available_providers,
            complexity=complexity,
            project_path=project_path,
        )

        results.append({"stage_id": stage_id, **result})

        if not result.get("ok"):
            # Persist error state to DB
            if stage_id in db_stages:
                db_stages[stage_id].status = "blocked" if result.get("blocked") else "error"
            if db_task:
                db_task.status = "paused" if result.get("blocked") else "active"
            # Phase 4.2b: write scheduler_last_error for build failure or stage error
            if result.get("build_log_summary"):
                err_msg = result["error"][:500]
            else:
                err_msg = result.get("error", "Stage execution failed")[:500]
            if db_task:
                db_task.scheduler_last_error = err_msg
            try:
                await db.flush()
            except Exception as flush_err:
                logger.warning("[pipeline] DB flush failed persisting error state: %s", flush_err)
                try:
                    await db.rollback()
                except Exception:
                    pass

            if result.get("blocked") and not force_continue:
                await complete_trace(trace.trace_id, status="blocked")
                await emit_event("pipeline:auto-paused", {
                    "taskId": task_id,
                    "stoppedAt": stage_id,
                    "reason": result.get("reason", "Blocked by guardrail"),
                })
                return {
                    "ok": False,
                    "blocked": True,
                    "stopped_at": stage_id,
                    "approval_id": result.get("approval_id"),
                    "reason": result.get("reason", "Blocked by guardrail"),
                    "results": results,
                    "trace_id": trace.trace_id,
                }

            if force_continue:
                logger.warning(
                    f"[pipeline] Stage {stage_id} failed but force_continue=True, skipping to next"
                )
                await emit_event("stage:error", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "error": result.get("error", "Unknown error"),
                    "continuing": True,
                })
                continue

            await complete_trace(trace.trace_id, status="failed")
            await emit_event("pipeline:auto-error", {
                "taskId": task_id,
                "stoppedAt": stage_id,
                "error": result.get("error", "Unknown error"),
            })
            return {
                "ok": False,
                "stopped_at": stage_id,
                "error": result.get("error"),
                "results": results,
                "trace_id": trace.trace_id,
            }

        content = result.get("content", "")
        outputs[stage_id] = content

        # Persist stage output + verification data
        verification = result.get("verification", {})
        quality_score = 0.8 if verification.get("status") == "pass" else 0.5 if verification.get("status") == "warn" else 0.2
        if stage_id in db_stages:
            db_stages[stage_id].output = content
            db_stages[stage_id].verify_status = verification.get("status")
            db_stages[stage_id].verify_checks = verification.get("checks")
            db_stages[stage_id].quality_score = quality_score
        try:
            await db.flush()
        except Exception as flush_err:
            logger.warning("[pipeline] DB flush failed persisting stage output: %s", flush_err)
            try:
                await db.rollback()
            except Exception:
                pass

        # Write to delivery docs on disk (dual-write: global legacy + task-scoped)
        try:
            from ..api.delivery_docs import write_stage_output
            await write_stage_output(stage_id, content)
        except Exception as doc_err:
            logger.warning(f"[pipeline] Failed to write legacy delivery doc for {stage_id}: {doc_err}")
        try:
            from .task_workspace import write_stage_output_v2
            await write_stage_output_v2(task_id, task_title, stage_id, content)
        except Exception as ws_err:
            logger.warning(f"[pipeline] Failed to write task workspace doc for {stage_id}: {ws_err}")

        # Note: artifact writing is now handled inside execute_stage() (Layer 10)
        # to ensure artifacts are written even when stages are run individually.
        # The duplicate call here has been removed to avoid double-writing.

        # --- Peer Review (Layer 11) ---
        review_config = STAGE_REVIEW_CONFIG.get(stage_id)
        if review_config and review_config.get("reviewer_agent"):
            try:
                review_result = await review_stage_output(
                    db,
                    task_id=task_id,
                    stage_id=stage_id,
                    stage_output=content,
                    task_title=task_title,
                    task_description=task_description,
                    previous_outputs=outputs,
                )
                if stage_id in db_stages:
                    db_stages[stage_id].review_status = "approved" if review_result.get("approved") else "rejected"
                    db_stages[stage_id].reviewer_feedback = review_result.get("feedback", "")
                    db_stages[stage_id].reviewer_agent = review_result.get("reviewer_agent", "")
                    db_stages[stage_id].review_attempts = (db_stages[stage_id].review_attempts or 0) + 1
                await db.flush()

                if not review_result.get("approved"):
                    await emit_event("stage:peer-review-blocked", {
                        "taskId": task_id,
                        "stageId": stage_id,
                        "reviewer": review_result.get("reviewer", ""),
                        "feedback": review_result.get("feedback", "")[:500],
                    })
                    # If review rejects, pause pipeline unless force_continue
                    if not force_continue:
                        await complete_trace(trace.trace_id, status="review_rejected")
                        return {
                            "ok": False,
                            "stopped_at": stage_id,
                            "reason": "Peer review rejected",
                            "review_result": review_result,
                            "results": results,
                            "trace_id": trace.trace_id,
                        }
                else:
                    early_peer_review_ok = review_result
            except Exception as review_err:
                logger.warning("[pipeline] Peer review failed for %s: %s", stage_id, review_err)

        # --- Post-stage hooks (code extraction, test validation, etc.) ---
        try:
            from .stage_hooks import run_hooks, HookContext
            post_ctx = HookContext(
                task_id=task_id, stage_id=stage_id, worktree=task_worktree,
                content=content, model=result.get("model", ""),
                agent_id=_AGENT_KEY_TO_SEED_ID.get(
                    STAGE_ROLE_PROMPTS.get(stage_id, {}).get("agent", ""), ""),
            )
            post_results = await run_hooks("post", post_ctx)
            if post_results:
                logger.info("[pipeline] Post-hooks for %s: %s", stage_id, post_results)
                for pr in post_results:
                    if not pr.get("ok") and stage_id in db_stages:
                        err = pr.get("error", "hook failed")
                        db_stages[stage_id].last_error = (err or "")[:2000]
                await emit_event("stage:hooks-complete", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "hooks": post_results,
                })
        except Exception as hook_err:
            logger.warning("[pipeline] Post-stage hooks failed for %s: %s", stage_id, hook_err)
            if stage_id in db_stages:
                db_stages[stage_id].last_error = str(hook_err)[:2000]

        # --- Layer 3.7: Skill Completion Criteria Validation ---
        skill_criteria_results = []
        skill_completion_criteria = result.get("skill_completion_criteria") or []
        if skill_completion_criteria and content:
            try:
                from .role_card_builder import build_skill_criteria_check
                skill_criteria_results = build_skill_criteria_check(content, skill_completion_criteria)
                passed = sum(1 for r in skill_criteria_results if r["passed"])
                total = len(skill_criteria_results)
                logger.info(
                    "[pipeline] Skill criteria for %s: %d/%d passed",
                    stage_id, passed, total,
                )
                await emit_event("stage:skill-criteria", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "passed": passed,
                    "total": total,
                    "results": skill_criteria_results,
                })
            except Exception as sc_err:
                logger.warning("[pipeline] Skill criteria check failed: %s", sc_err)

        # --- Quality Gate Evaluation ---
        gate_result = None
        try:
            from .quality_gates import evaluate_quality_gate
            from .self_verify import StageVerification, VerifyStatus, VerifyResult

            heuristic = StageVerification(
                stage_id=stage_id, role="",
                overall_status=VerifyStatus(verification.get("status", "pass")),
                checks=[VerifyResult(check_name=c.get("check_name", c.get("name", "")), status=VerifyStatus(c.get("status", "pass")), message=c.get("message", "")) for c in verification.get("checks", [])],
                auto_proceed=verification.get("auto_proceed", True),
            )
            task_template = db_task.template if db_task else None
            # Per-task overrides set via the dashboard's "门禁阈值" drawer
            # take precedence over template/global defaults — see
            # quality_gates._get_stage_config for the merge rules.
            task_overrides = (db_task.quality_gate_config if db_task else None) or None
            gate_result = await evaluate_quality_gate(
                stage_id, content,
                template=task_template,
                previous_outputs=outputs,
                heuristic_result=heuristic,
                skip_llm=force_continue,
                task_overrides=task_overrides,
            )

            if stage_id in db_stages:
                db_stages[stage_id].gate_status = gate_result.overall_status.value
                db_stages[stage_id].gate_score = gate_result.overall_score
                db_stages[stage_id].gate_details = {
                    "checks": [c.dict() for c in gate_result.checks],
                    "suggestions": gate_result.suggestions,
                    "block_reason": gate_result.block_reason,
                }
            await db.flush()

            await emit_event("stage:quality-gate", {
                "taskId": task_id,
                "stageId": stage_id,
                "gateStatus": gate_result.overall_status.value,
                "gateScore": gate_result.overall_score,
                "canProceed": gate_result.can_proceed,
                "blockReason": gate_result.block_reason,
            })

            if not gate_result.can_proceed and not force_continue:
                if db_task:
                    db_task.status = "paused"
                if stage_id in db_stages:
                    db_stages[stage_id].status = "blocked"
                await db.flush()
                await complete_trace(trace.trace_id, status="paused")

                # Learning loop — persist GATE_FAIL signal
                try:
                    from .learning_loop import capture_signal
                    await capture_signal(
                        db, task_id=task_id, stage_id=stage_id,
                        role=STAGE_ROLE_PROMPTS.get(stage_id, {}).get("role", ""),
                        signal_type="GATE_FAIL", severity="error",
                        reviewer_feedback=gate_result.block_reason,
                        output_excerpt=content,
                        quality_score=gate_result.overall_score,
                        metadata={"suggestions": gate_result.suggestions},
                    )
                except Exception as exc:
                    logger.debug("[learning] GATE_FAIL signal capture failed: %s", exc)

                await emit_event("pipeline:auto-paused", {
                    "taskId": task_id,
                    "stoppedAt": stage_id,
                    "reason": f"质量门禁未通过: {gate_result.block_reason or '评分过低'}",
                    "gateScore": gate_result.overall_score,
                })
                return {
                    "ok": False,
                    "paused": True,
                    "stopped_at": stage_id,
                    "reason": f"Quality gate failed: {gate_result.block_reason}",
                    "gate_result": gate_result.dict(),
                    "results": results,
                    "trace_id": trace.trace_id,
                }
        except Exception as gate_err:
            logger.warning(f"[pipeline] Quality gate evaluation failed for {stage_id}: {gate_err}")

        if not verification.get("auto_proceed", True):
            if force_continue:
                logger.warning(
                    f"[pipeline] Stage {stage_id} verification failed but force_continue=True, proceeding"
                )
                await emit_event("stage:verify-warn", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "checks": verification.get("checks", []),
                    "suggestions": verification.get("suggestions", []),
                })
            else:
                if db_task:
                    db_task.status = "paused"
                await db.flush()
                await complete_trace(trace.trace_id, status="paused")
                await emit_event("pipeline:auto-paused", {
                    "taskId": task_id,
                    "stoppedAt": stage_id,
                    "reason": "Verification requires human review",
                })
                return {
                    "ok": False,
                    "paused": True,
                    "stopped_at": stage_id,
                    "reason": "Verification failed, requires human review",
                    "results": results,
                    "trace_id": trace.trace_id,
                }

        # --- Peer Review: downstream agent reviews this stage's output ---
        review_conf = STAGE_REVIEW_CONFIG.get(stage_id, {})
        from .learning_loop import get_active_addendum as _get_active_addendum
        _task_tpl = db_task.template if db_task else None
        active_addendum = await _get_active_addendum(
            db, stage_id=stage_id, template=_task_tpl, complexity=complexity,
        )
        if review_conf.get("reviewer_agent") and not force_continue:
            # 后期评审入口：如果早期评审已通过，直接复用结果跳过此轮（避免重复 LLM 调用）
            if early_peer_review_ok is not None and early_peer_review_ok.get("approved"):
                results[-1]["review"] = early_peer_review_ok
                logger.info(
                    "[pipeline] Stage %s peer review: skipping duplicate post-gate reviewer call",
                    stage_id,
                )
            retries = 0
            while (
                early_peer_review_ok is None or not early_peer_review_ok.get("approved")
            ) and retries < MAX_REVIEW_RETRIES:
                if stage_id in db_stages:
                    db_stages[stage_id].status = "reviewing"
                await db.flush()

                review_result = await review_stage_output(
                    db,
                    task_id=task_id,
                    stage_id=stage_id,
                    stage_output=content,
                    task_title=task_title,
                    task_description=task_description,
                    previous_outputs=outputs,
                    injected_override_id=(
                        active_addendum.get("id") if active_addendum else None
                    ),
                    injected_override_mode=(
                        active_addendum.get("mode") if active_addendum else None
                    ),
                )

                results[-1]["review"] = review_result

                if stage_id in db_stages:
                    db_stages[stage_id].reviewer_agent = review_result.get("reviewer", "")
                    db_stages[stage_id].reviewer_feedback = review_result.get("feedback", "")
                    db_stages[stage_id].review_attempts = retries + 1

                if review_result.get("approved", True):
                    logger.info(f"[pipeline] Stage {stage_id} peer review: APPROVED by {review_result.get('reviewer', '?')}")
                    if stage_id in db_stages:
                        db_stages[stage_id].review_status = "approved"
                    await db.flush()
                    break

                retries += 1
                feedback = review_result.get("feedback", "")
                logger.warning(f"[pipeline] Stage {stage_id} peer review: REJECTED (attempt {retries}/{MAX_REVIEW_RETRIES})")

                if stage_id in db_stages:
                    db_stages[stage_id].review_status = "rejected"
                await db.flush()

                if retries >= MAX_REVIEW_RETRIES:
                    if db_task:
                        db_task.status = "paused"
                    if stage_id in db_stages:
                        db_stages[stage_id].status = "rejected"
                    await db.flush()
                    await emit_event("pipeline:auto-paused", {
                        "taskId": task_id,
                        "stoppedAt": stage_id,
                        "reason": f"Peer review rejected after {MAX_REVIEW_RETRIES} retries",
                        "feedback": feedback[:500],
                    })
                    return {
                        "ok": False,
                        "paused": True,
                        "stopped_at": stage_id,
                        "reason": f"Peer review rejected by {review_result.get('reviewer', '?')}",
                        "review_feedback": feedback,
                        "results": results,
                        "trace_id": trace.trace_id,
                    }

                # Re-execute stage with reviewer feedback injected.
                # We pass the *rejected* draft along with the event so the
                # frontend's "self-heal" drawer can show a before/after diff
                # without needing a separate API round-trip. The DB column
                # ``output`` will be overwritten on the next iteration, so
                # this is the only place we get to capture the rejected
                # version.
                rejected_draft = (
                    db_stages[stage_id].output
                    if stage_id in db_stages
                    else (results[-1].get("content", "") if results else "")
                )
                await emit_event("stage:rework", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "attempt": retries + 1,
                    "feedback": feedback[:300],
                    "rejectedDraft": (rejected_draft or "")[:4000],
                    "rejectedDraftTruncated": bool(rejected_draft and len(rejected_draft) > 4000),
                    "reviewer": review_result.get("reviewer", ""),
                })

                rework_outputs = dict(outputs)
                rework_outputs[f"{stage_id}_review_feedback"] = (
                    f"## 审阅反馈（来自 {review_result.get('reviewer', '审阅者')}）\n\n"
                    f"{feedback}\n\n请根据以上反馈修改你的产出。"
                )

                if stage_id in db_stages:
                    db_stages[stage_id].status = "active"
                    db_stages[stage_id].started_at = datetime.utcnow()
                await db.flush()

                rework = await execute_stage(
                    db,
                    task_id=task_id,
                    task_title=task_title,
                    task_description=task_description,
                    stage_id=stage_id,
                    previous_outputs=rework_outputs,
                    trace=trace,
                    available_providers=available_providers,
                    complexity=complexity,
                )

                if not rework.get("ok"):
                    break

                content = rework.get("content", "")
                outputs[stage_id] = content
                results[-1] = {"stage_id": stage_id, **rework}

                if stage_id in db_stages:
                    db_stages[stage_id].output = content
                await db.flush()

        # --- Human Approval Gate ---
        if review_conf.get("human_gate") and not force_continue:
            from .guardrails import ApprovalRequest, GuardrailLevel as GL, _store_approval
            approval = ApprovalRequest(
                task_id=task_id,
                stage_id=stage_id,
                action=f"approve_{stage_id}",
                description=f"阶段「{stage_id}」已完成，需要人工审批确认后才能继续",
                risk_level=GL.REQUIRE_REVIEW,
                requested_by="pipeline",
            )
            await _store_approval(approval)

            if db_task:
                db_task.status = "paused"
            if stage_id in db_stages:
                db_stages[stage_id].status = "awaiting_approval"
                db_stages[stage_id].approval_id = approval.id
            await db.flush()

            await emit_event("stage:awaiting-approval", {
                "taskId": task_id,
                "stageId": stage_id,
                "approvalId": approval.id,
                "label": f"阶段「{stage_id}」等待人工审批...",
            })

            # 跨渠道通知：IM / webhook / 邮件
            if db_task:
                try:
                    from .notify import broadcast_task_event
                    stage_label = {
                        "planning": "需求规划", "design": "UI/UX 设计",
                        "architecture": "架构设计", "development": "开发实现",
                        "testing": "测试验证", "reviewing": "审查验收",
                        "deployment": "部署上线",
                    }.get(stage_id, stage_id)
                    await broadcast_task_event(
                        db_task,
                        event="awaiting_approval",
                        message=f"阶段「{stage_label}」已完成，等待人工审批",
                        extras={
                            "阶段": stage_label,
                            "审批ID": approval.id,
                            "操作": f"前往 {task_id[:8]} 详情页进行审批",
                        },
                    )
                except Exception as notify_err:
                    logger.debug("[pipeline] approval notification failed: %s", notify_err)

            await complete_trace(trace.trace_id, status="paused")
            return {
                "ok": False,
                "paused": True,
                "awaiting_approval": True,
                "approval_id": approval.id,
                "stopped_at": stage_id,
                "reason": f"阶段 {stage_id} 需要人工审批",
                "results": results,
                "trace_id": trace.trace_id,
            }

        # --- Hermes Oversight: unified supervision before stage finalization ---
        try:
            from .hermes_oversight import run_hermes_oversight
            content_to_check = content or ""
            hermes_report = await run_hermes_oversight(
                db,
                task_id=task_id,
                stage_id=stage_id,
                role=STAGE_ROLE_PROMPTS.get(stage_id, {}).get("role", ""),
                content=content_to_check,
                previous_outputs=outputs,
                force_continue=force_continue,
            )
            if hermes_report.overall_score < 7.0:
                logger.info(
                    "[hermes] Stage %s score=%.1f — %s",
                    stage_id, hermes_report.overall_score, hermes_report.verdict.value,
                )

            await emit_event("stage:hermes-oversight", {
                "taskId": task_id,
                "stageId": stage_id,
                "verdict": hermes_report.verdict.value,
                "overallScore": hermes_report.overall_score,
                "summary": hermes_report.summary,
            })

            if stage_id in db_stages:
                db_stages[stage_id].hermes_score = hermes_report.overall_score
                db_stages[stage_id].hermes_verdict = hermes_report.verdict.value
        except Exception as hermes_err:
            logger.warning("[hermes] Oversight failed for %s: %s", stage_id, hermes_err)

        # Mark stage as finalized
        if stage_id in db_stages:
            db_stages[stage_id].status = "done"
            db_stages[stage_id].completed_at = datetime.utcnow()
        await db.flush()

        # --- Acceptance REJECT_TO detection (reviewing stage only) ---
        # The acceptance agent can output "REJECTED REJECT_TO: <target_stage>"
        # to indicate the deliverable should be reworked from a specific stage.
        # When detected, we auto-rework from that stage instead of proceeding.
        if stage_id == "reviewing" and content:
            reject_to_stage = _parse_reject_to(content)
            if reject_to_stage and reject_to_stage in stages:
                reject_idx = stages.index(reject_to_stage)
                current_idx = stages.index(stage_id)
                if reject_idx < current_idx:
                    reject_reason = _extract_reject_reason(content)
                    logger.info(
                        "[pipeline] Acceptance REJECT_TO: %s → reworking from %s",
                        task_id, reject_to_stage,
                    )
                    await emit_event("pipeline:acceptance-reject-to", {
                        "taskId": task_id,
                        "rejectToStage": reject_to_stage,
                        "reason": reject_reason[:500],
                    })

                    for s_id in stages[reject_idx:current_idx + 1]:
                        if s_id in db_stages:
                            db_stages[s_id].status = "pending"
                            if s_id == reject_to_stage:
                                db_stages[s_id].reject_feedback = reject_reason[:2000]
                    if db_task:
                        db_task.current_stage_id = reject_to_stage
                    await db.flush()

                    rework_stages = stages[reject_idx:]
                    for rework_sid in rework_stages:
                        rework_reject_fb = None
                        if rework_sid == reject_to_stage:
                            rework_reject_fb = reject_reason

                        if rework_sid in db_stages:
                            db_stages[rework_sid].status = "active"
                            db_stages[rework_sid].started_at = datetime.utcnow()
                        await db.flush()

                        rework_result = await execute_stage(
                            db,
                            task_id=task_id,
                            task_title=task_title,
                            task_description=task_description,
                            stage_id=rework_sid,
                            previous_outputs=outputs,
                            trace=trace,
                            available_providers=available_providers,
                            complexity=complexity,
                            reject_feedback=rework_reject_fb,
                            reject_count=1,
                        )
                        if rework_result.get("ok"):
                            rework_content = rework_result.get("content", "")
                            outputs[rework_sid] = rework_content
                            results.append({"stage_id": rework_sid, **rework_result})
                            if rework_sid in db_stages:
                                db_stages[rework_sid].output = rework_content
                                db_stages[rework_sid].status = "done"
                                db_stages[rework_sid].completed_at = datetime.utcnow()
                            await db.flush()
                        else:
                            if db_task:
                                db_task.status = "paused"
                            await db.flush()
                            return {
                                "ok": False,
                                "paused": True,
                                "stopped_at": rework_sid,
                                "reason": f"Rework failed at {rework_sid} after acceptance REJECT_TO",
                                "results": results,
                                "trace_id": trace.trace_id,
                            }

        if stage_id != stages[0]:
            prev_stage = stages[stages.index(stage_id) - 1]
            await update_quality_score(db, task_id, prev_stage, 0.8)

    # All stages complete — compute overall quality. Status decision below.
    if db_task:
        q_scores = [
            float(s.quality_score)
            for s in db_task.stages
            if s.quality_score is not None and float(s.quality_score) > 0
        ]
        if q_scores:
            db_task.overall_quality_score = round(sum(q_scores) / len(q_scores), 3)
        else:
            gate_scores = [
                float(s.gate_score) for s in db_task.stages
                if s.gate_score is not None
            ]
            if gate_scores:
                db_task.overall_quality_score = round(
                    sum(gate_scores) / len(gate_scores), 3
                )
    await db.flush()

    # Auto-compile deliverables
    try:
        from ..api.delivery_docs import compile_deliverables
        deliverable_md = await compile_deliverables(task_id, db)
        logger.info(f"[pipeline] Compiled deliverables for task {task_id} ({len(deliverable_md)} chars)")
    except Exception as e:
        logger.warning(f"[pipeline] Failed to compile deliverables: {e}")
        deliverable_md = None

    # ── Final acceptance terminus ─────────────────────────────────────
    # Decision tree (kept here, NOT in compile_deliverables, so callers that
    # invoke compile manually don't accidentally trip the gate):
    #
    #   1. ``auto_final_accept = True``  → straight to ``done``,
    #                                       final_acceptance_status="accepted",
    #                                       by="auto"
    #   2. otherwise                      → ``status=awaiting_final_acceptance``,
    #                                       final_acceptance_status="pending",
    #                                       wait for /final-accept or /final-reject
    auto_accept = bool(db_task and db_task.auto_final_accept)
    if db_task:
        if auto_accept:
            db_task.status = "done"
            db_task.current_stage_id = "done"
            db_task.final_acceptance_status = "accepted"
            db_task.final_acceptance_by = "auto"
            db_task.final_acceptance_at = datetime.utcnow()
        else:
            db_task.status = "awaiting_final_acceptance"
            db_task.current_stage_id = "final_acceptance"
            db_task.final_acceptance_status = "pending"
        await db.flush()

    await complete_trace(trace.trace_id, status="completed")

    summary = {
        "stages_completed": len(results),
        "total_tokens": sum(r.get("tokens", {}).get("total", 0) for r in results),
        "total_cost_usd": round(sum(r.get("cost_usd", 0) for r in results), 6),
    }

    if auto_accept:
        await emit_event("pipeline:auto-completed", {
            "taskId": task_id,
            "title": task_title,
            "stagesCompleted": summary["stages_completed"],
            "totalTokens": summary["total_tokens"],
            "totalCostUsd": summary["total_cost_usd"],
            "traceId": trace.trace_id,
            "hasDeliverable": deliverable_md is not None,
        })
    else:
        await emit_event("pipeline:awaiting-final-acceptance", {
            "taskId": task_id,
            "title": task_title,
            "stagesCompleted": summary["stages_completed"],
            "totalTokens": summary["total_tokens"],
            "totalCostUsd": summary["total_cost_usd"],
            "traceId": trace.trace_id,
            "hasDeliverable": deliverable_md is not None,
            "overallQualityScore": (
                db_task.overall_quality_score if db_task else None
            ),
        })

    # Cross-channel broadcast for critical events
    if db_task:
        try:
            from .notify import broadcast_task_event
            event_name = "completed" if auto_accept else "awaiting_acceptance"
            msg = (
                f"全部 {summary['stages_completed']} 个阶段完成"
                if auto_accept
                else f"全部 {summary['stages_completed']} 个阶段完成，等待最终验收"
            )
            await broadcast_task_event(
                db_task,
                event=event_name,
                message=msg,
                extras={"质量分": f"{round((db_task.overall_quality_score or 0) * 100)}%"},
            )
        except Exception as notify_err:
            logger.debug("[pipeline] cross-channel broadcast failed: %s", notify_err)

    return {
        "ok": True,
        "results": results,
        "trace_id": trace.trace_id,
        "summary": summary,
    }


def _parse_reject_to(content: str) -> Optional[str]:
    """Parse REJECT_TO: <stage_id> from acceptance agent output."""
    import re
    match = re.search(r"REJECT(?:ED)?\s+REJECT_TO:\s*(\S+)", content, re.IGNORECASE)
    if match:
        return match.group(1).strip().lower()
    return None


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


# ── Ruflo MCP Bridge Integration ──────────────────────────────────────


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
    if not _s.ruflo_enabled:
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


# ── Phase 4.2b helper ───────────────────────────────────────────────────


def _write_build_log_to_disk(project_dir: str, log_text: str) -> str:
    """Write build.log to project_dir. Returns the file path."""
    path = os.path.join(project_dir, "build.log")
    with open(path, "w", encoding="utf-8") as f:
        f.write(log_text)
    return path
