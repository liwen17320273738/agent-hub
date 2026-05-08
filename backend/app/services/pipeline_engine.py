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

import json
import logging
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
)
from .guardrails import evaluate_guardrail, GuardrailLevel
from .observability import (
    start_trace, start_span, complete_span, complete_trace, PipelineTrace,
)
from .llm_router import chat_completion_with_fallback as llm_chat_with_fallback
from .token_tracker import estimate_cost
from .sse import emit_event

logger = logging.getLogger(__name__)


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
        "reviewer_prompt": """你是架构师 Agent，现在需要审阅 CEO Agent 产出的 PRD（产品需求文档）。
请从技术可行性角度评估：
1. 需求描述是否清晰、无歧义？
2. 技术约束是否合理？
3. 是否有遗漏的关键需求或非功能需求？
4. 里程碑是否现实可行？

最终结论（第一行必须是以下之一）：
- **APPROVE** — PRD 质量合格，可以开始架构设计
- **REJECT** — 需要修改（列出具体问题和修改建议）""",
        "human_gate": False,
    },
    "design": {
        "reviewer_agent": "product-agent",
        "reviewer_prompt": """你是产品经理 Agent，现在需要审阅 UI/UX 设计师产出的设计规范。
请从产品体验角度评估：
1. 设计是否覆盖 PRD 中的核心用户故事？
2. 关键界面是否有具体布局/状态/空态/错误态规范？
3. 设计 Token（颜色/字号/间距）是否一致、可复用？
4. 是否说明了响应式断点和无障碍考量？

最终结论（第一行必须是以下之一）：
- **APPROVE** — 设计规范完整，开发可据此动工
- **REJECT** — 缺关键页面或规范不足（列出具体问题）""",
        "human_gate": False,
    },
    "architecture": {
        "reviewer_agent": "developer-agent",
        "reviewer_prompt": """你是开发 Agent，现在需要审阅架构师 Agent 产出的技术方案。
请从开发落地角度评估：
1. API 设计是否完整、可实现？
2. 数据模型是否合理、性能可接受？
3. 技术选型是否成熟稳定？
4. 是否有模糊不清、需要澄清的设计决策？

最终结论（第一行必须是以下之一）：
- **APPROVE** — 技术方案可行，可以开始开发
- **REJECT** — 需要修改（列出具体问题和修改建议）""",
        "human_gate": False,
    },
    "development": {
        "reviewer_agent": "qa-agent",
        "reviewer_prompt": """你是测试 Agent，现在需要审阅开发 Agent 产出的代码实现。
请从质量角度做初步评估：
1. 代码是否覆盖了 PRD 中的核心用户故事？
2. 是否有明显的安全漏洞或逻辑错误？
3. 错误处理和边界情况是否完整？
4. 代码结构是否清晰、可测试？

最终结论（第一行必须是以下之一）：
- **APPROVE** — 代码质量可接受，可以进入正式测试
- **REJECT** — 需要修改（列出具体问题和修改建议）""",
        "human_gate": False,
    },
    "testing": {
        "reviewer_agent": "acceptance-agent",
        "reviewer_prompt": """你是验收官 Agent，现在需要审阅测试 Agent 的测试报告。
请从最终交付角度评估：
1. 测试覆盖率是否达标？是否覆盖 PRD 全部用户故事？
2. 发现的缺陷严重程度如何？P0/P1 是否清零？
3. 是否提供了证据（测试报告、覆盖率数据、截图、日志）？

最终结论（第一行必须是以下之一）：
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
        "reviewer_prompt": """你是 CEO Agent。验收官 Agent 已经给出最终验收报告。
请用 30 秒做最终上线前 Go/No-Go：
1. 验收报告结论是否明确（APPROVED/REJECTED）？
2. 是否所有 P0 风险都已记录？
3. 上线后有什么监控/回滚预案？

最终结论（第一行必须是以下之一）：
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
        "reviewer_prompt": """你是架构师 Agent，请审阅安全工程师的审计报告。
评估：
1. 安全审计是否覆盖所有关键模块？
2. 报告中的修复建议是否技术上可执行？
3. 是否遗漏架构层的纵深防御考量？

第一行：APPROVE / REJECT。
""",
        "human_gate": False,
    },
    "legal-review": {
        "reviewer_agent": "ceo-agent",
        "reviewer_prompt": """你是 CEO Agent，请审阅法务的合规审查。
评估：
1. 法律风险评级是否合理？
2. 业务上是否能接受 CONDITIONAL 中的限制？
3. 是否需要调整 PRD 范围以满足合规？

第一行：APPROVE / REJECT。
""",
        "human_gate": True,
    },
    "data-modeling": {
        "reviewer_agent": "product-agent",
        "reviewer_prompt": """你是产品经理 Agent，请审阅数据分析师的指标方案。
评估：
1. 北极星指标是否真正反映北极星目标？
2. 埋点是否覆盖 PRD 全部用户故事？
3. 报表是否能驱动后续迭代决策？

第一行：APPROVE / REJECT。
""",
        "human_gate": False,
    },
    "marketing-launch": {
        "reviewer_agent": "ceo-agent",
        "reviewer_prompt": """你是 CEO Agent，请审阅 CMO 的上线营销包。
评估：
1. 渠道与预算分配是否合理？
2. 文案是否准确传达产品价值？
3. 节奏与 KPI 是否可执行？

第一行：APPROVE / REJECT。
""",
        "human_gate": False,
    },
    "finance-review": {
        "reviewer_agent": "ceo-agent",
        "reviewer_prompt": """你是 CEO Agent，请审阅 CFO 的商业可持续性评估。
评估：
1. 成本估算是否反映真实的算力/带宽/LLM 用量？
2. 单位经济是否健康？
3. 风险点是否需要在 PRD 阶段裁掉？

第一行：APPROVE / REJECT。
""",
        "human_gate": True,
    },
}

MAX_REVIEW_RETRIES = 2

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

根据以下需求，输出一份专业级 PRD（产品需求文档），必须包含：
1. **需求概述** — 一句话描述核心价值主张
2. **目标用户** — 用户画像、使用场景
3. **功能范围** — IN-SCOPE（必做）/ OUT-OF-SCOPE（不做）/ FUTURE（未来考虑）
4. **用户故事** — 至少5条（格式: As a [角色] I want [功能] So that [价值]）
5. **验收标准** — 每个用户故事对应可量化的验收条件
6. **非功能需求** — 性能指标、安全要求、兼容性、可访问性
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

根据 PRD 输出技术方案，必须包含：
1. **技术选型** — 语言/框架/数据库/中间件，附选型理由和对比
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
   | # | PRD 验收标准 | 实际结果 | 证据 | 通过? |
   |---|---|---|---|---|
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

输出安全审计报告（必须用表格列出每条 finding）：

| 严重度 | 类别 | 位置 | 描述 | 修复建议 |
|---|---|---|---|---|

类别覆盖（缺一不可，没有则写 OK）：
- 身份与认证（弱口令、JWT 配置、Session）
- 授权与越权（IDOR、纵向/横向权限）
- 输入校验与注入（SQLi、XSS、命令注入、SSRF、路径穿越）
- 敏感数据（明文密码、密钥硬编码、日志泄露）
- 依赖与供应链（已知 CVE、过期版本）
- 配置与部署（HTTPS、CORS、CSP、HSTS、安全头）
- 业务逻辑（重放、竞态、限流、防刷）

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

输出合规审查报告：

1. **数据收集合法性** — 是否符合最小必要原则？是否有明示同意？
2. **跨境传输** — 数据是否出境？是否需要安全评估？
3. **未成年人/敏感数据** — 是否有专项保护？
4. **隐私政策与用户协议** — 是否齐备、是否覆盖所有数据处理活动？
5. **第三方服务** — SDK 清单 + 数据共享透明度
6. **知识产权** — 开源协议合规、商标、专利
7. **行业资质** — ICP / 等保 / PCI-DSS / HIPAA 等
8. **违规风险与处罚** — 列出 P0/P1 风险及具体法条

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
                context_parts.append(f"## 前置阶段 — {lbl}\n{out[:800]}")
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
            "label": f"⚠️ {reviewer_name} 审阅失败（{e}），自动通过但建议人工复查",
        })
        return {
            "reviewed": True,
            "approved": True,
            "auto_approved_on_error": True,
            "reason": f"Review error (auto-approved): {e}",
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
        "label": f"{agent_icon} {agent_name} 正在处理「{stage_id}」阶段...",
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
            except Exception:
                pass

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
                        f"### Claude 输出摘要\n\n```\n{claude_summary}\n```\n"
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
            # Still record minimal metrics so cost/trace accounting works.
            prompt_tokens = 0
            completion_tokens = 0
            logger.info("[pipeline] development stage skipped LLM/AgentRuntime because Claude Code wrote %d files", len(cc_written_files))

        # --- Layer 4.6: Testing stage build verification ---
        # Before the testing agent generates a report, try to build the code
        # that was written in the development stage. If build fails, auto-fix.
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
                    if not build_ok:
                        logger.warning("[pipeline] Build failed, attempting auto-fix: %s", build_log[:500])
                        fix_result = await codegen.auto_fix(
                            task_id=task_id,
                            project_dir=str(task_worktree),
                            error_output=build_log,
                            attempt=1,
                        )
                        if fix_result.get("ok"):
                            # Retry build after fix
                            build_result = await codegen.run_build(str(task_worktree), build_cmd)
                            build_log = build_result.get("output", "")
                            build_ok = build_result.get("ok", False)
                            logger.info("[pipeline] Build retry after auto-fix: ok=%s", build_ok)
                        else:
                            logger.warning("[pipeline] Auto-fix failed: %s", fix_result.get("output", "")[:500])
                    # Inject build result into user_message so the testing agent sees it
                    build_section = (
                        f"\n\n## 实际构建结果（自动执行）\n\n"
                        f"构建命令: `{build_cmd}`\n"
                        f"构建状态: {'✅ 通过' if build_ok else '❌ 失败'}\n"
                        f"构建日志:\n```\n{build_log[:4000]}\n```\n"
                    )
                    user_message += build_section
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
            runtime_result = await runtime.execute(
                db,
                task=user_message,
                context=previous_outputs,
                image_attachments=att_images if att_images else None,
                task_id=task_id,
            )
            if not runtime_result.get("ok"):
                raise RuntimeError(runtime_result.get("error", "AgentRuntime failed"))
            content = runtime_result.get("content", "")
            prompt_tokens = 0
            completion_tokens = 0

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

            llm_result = await llm_chat_with_fallback(
                model=model,
                messages=messages,
                max_tokens=stage_max_tokens,
                api_url=api_url,
                image_attachments=att_images if att_images else None,
                on_fallback=_on_provider_fallback,
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

    except Exception as e:
        logger.error(f"[pipeline] Stage {stage_id} LLM call failed: {e}")
        await complete_span(span.span_id, status="failed", error=str(e))
        await emit_event("stage:error", {
            "taskId": task_id,
            "stageId": stage_id,
            "agent": agent_name,
            "error": str(e),
        })
        return {"ok": False, "error": str(e)}

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

    # --- Layer 5: Self-Verify → validate output ---
    verification = verify_stage_output(
        stage_id=stage_id,
        role=role,
        output=content,
        previous_outputs=previous_outputs,
    )

    # For development stage with Claude Code output, override verification
    # with heuristic scoring based on actual files in the worktree.
    if stage_id == "development" and _skip_llm_for_dev and task_worktree:
        wt_report = verify_worktree_code_quality(task_worktree)
        if wt_report:
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
                ],
                auto_proceed=wt_report.auto_proceed,
                suggestions=wt_report.suggestions,
            )
            logger.info(
                "[pipeline] development stage quality override: %s (score inferred from %d files)",
                verification.overall_status.value,
                len(cc_written_files),
            )

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
            except Exception as top_up_err:
                logger.warning(
                    "[pipeline] Stage %s repair top-up failed: %s",
                    stage_id, top_up_err,
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

    # --- Layer 9.6: Visual Generator → generate mockups/diagrams ---
    if stage_id in ("design", "architecture") and content:
        try:
            from .ui_visualizer import UiVisualizer
            from .artifact_writer import _write_one_artifact as _write_art_custom
            viz = UiVisualizer(workspace_root=app_settings.workspace_root)

            if stage_id == "design":
                # Design stage → UI mockup
                result = await viz.generate_mockup(
                    task_id=task_id, stage_id=stage_id,
                    design_spec=content,
                    project_name=task_title,
                )
                if result.get("ok"):
                    if result["imagePath"]:
                        await _write_art_custom(
                            db, task_id=str(task_id), stage_id=stage_id,
                            artifact_type="ui_mockup",
                            content=f"![UI 设计稿]({result['imagePath']})",
                            storage_path=result["imagePath"],
                            agent_name=agent_name,
                            metadata_json={"filePath": result["imagePath"], "prompt": result["prompt"]},
                        )
                    if result["htmlPath"]:
                        await _write_art_custom(
                            db, task_id=str(task_id), stage_id=stage_id,
                            artifact_type="ui_mockup_html",
                            content=f"UI 可交互原型:\n{result['htmlPath']}",
                            storage_path=result["htmlPath"],
                            agent_name=agent_name,
                            metadata_json={"filePath": result["htmlPath"]},
                        )
                    logger.info("[ui-visualizer] Generated UI mockups for %s", task_id[:12])
            elif stage_id == "architecture":
                # Architecture stage → architecture diagrams
                result = await viz.generate_architecture_diagram(
                    task_id=task_id, stage_id=stage_id,
                    arch_spec=content,
                    project_name=task_title,
                )
                if result.get("ok") and result.get("htmlPath"):
                    await _write_art_custom(
                        db, task_id=str(task_id), stage_id=stage_id,
                        artifact_type="architecture_diagram",
                        content=f"架构图:\n{result['htmlPath']}",
                        storage_path=result["htmlPath"],
                        agent_name=agent_name,
                        metadata_json={
                            "filePath": result["htmlPath"],
                            "componentCount": result.get("componentCount", 0),
                            "flowCount": result.get("flowCount", 0),
                        },
                    )
                    logger.info("[ui-visualizer] Generated architecture diagrams for %s", task_id[:12])
        except Exception as viz_err:
            logger.warning("[ui-visualizer] Visual generation skipped: %s", viz_err)

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

        # Mark current stage as active in DB
        if db_task:
            db_task.current_stage_id = stage_id
            if stage_id in db_stages:
                db_stages[stage_id].status = "active"
                db_stages[stage_id].started_at = datetime.utcnow()
            await db.flush()

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
            await db.flush()

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
        await db.flush()

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
            retries = 0
            while retries < MAX_REVIEW_RETRIES:
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
        if stage_id in ("reviewing", "deployment"):
            max_prev = 18_000
        elif stage_id in ("testing", "development", "architecture"):
            max_prev = 12_000
        else:
            max_prev = 800
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
