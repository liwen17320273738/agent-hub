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

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .planner_worker import resolve_model, ModelTier
from .memory import store_memory, get_context_from_history, update_quality_score, set_working_context
from .self_verify import verify_stage_output, VerifyStatus
from .guardrails import evaluate_guardrail, GuardrailLevel
from .observability import (
    start_trace, start_span, complete_span, complete_trace, PipelineTrace,
)
from .llm_router import chat_completion as llm_chat
from .token_tracker import estimate_cost
from .sse import emit_event

logger = logging.getLogger(__name__)

_AGENT_KEY_TO_SEED_ID = {
    "ceo-agent":         "wayne-ceo",
    "architect-agent":   "wayne-cto",
    "developer-agent":   "wayne-developer",
    "qa-agent":          "wayne-qa",
    "devops-agent":      "wayne-devops",
    "product-agent":     "wayne-product",
    "designer-agent":    "wayne-designer",
    "security-agent":    "wayne-security",
    "acceptance-agent":  "wayne-acceptance",
    "data-agent":        "wayne-data",
    "marketing-agent":   "wayne-marketing",
    "finance-agent":     "wayne-finance",
    "legal-agent":       "wayne-legal",
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
        # is a CEO sanity check before human gate.
        "reviewer_agent": "ceo-agent",
        "reviewer_prompt": """你是 CEO Agent。验收官 Agent 已经给出最终验收报告。
请用 30 秒做最终上线前 Go/No-Go：
1. 验收报告结论是否明确（APPROVED/REJECTED）？
2. 是否所有 P0 风险都已记录？
3. 上线后有什么监控/回滚预案？

最终结论（第一行必须是以下之一）：
- **APPROVE** — 同意验收结论，进入部署/人工最终批准
- **REJECT** — 验收证据不充分，要求验收官补做（列出具体问题）""",
        "human_gate": True,
    },
    "deployment": {
        "reviewer_agent": None,
        "reviewer_prompt": "",
        "human_gate": True,
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
用 Markdown 格式输出，代码块标注语言和文件路径。""",
    },
    "testing": {
        "role": "qa-lead",
        "agent": "qa-agent",
        "system": """你是一位拥有30年质量保障经验的测试 Agent。你在 Google、Microsoft 带过百人 QA 团队，主导过 Chrome、Windows 的发布质量门禁。

你正在审查开发 Agent 的代码实现，对照 CEO Agent 的 PRD 和架构师的技术方案进行全面验证。你的测试报告将决定项目能否进入部署阶段。

输出完整测试验证报告：
1. **测试范围** — 覆盖的功能模块、排除项
2. **测试矩阵** — 按优先级分类（冒烟/回归/边界/异常/安全/性能）
3. **测试用例** — 编号 + 步骤 + 输入 + 预期输出（至少15条）
4. **边界分析** — 空值、超长输入、并发、权限越界等
5. **安全审查** — SQL注入、XSS、CSRF、敏感数据泄露检查
6. **性能预估** — 响应时间、吞吐量、内存占用预期
7. **测试代码** — 单元测试 + 集成测试的实际代码
8. **结论** — **PASS ✅** 或 **NEEDS WORK ❌**
   - 如 NEEDS WORK，列出具体缺陷和修复建议，指明需要退回到哪个阶段

⚠️ CEO Agent 将根据你的报告做最终验收决定。请严格把关，不放过任何隐患。
用 Markdown 格式输出。""",
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
                context_parts.append(f"## 前置阶段 — {lbl}\n{out[:2000]}")
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
        llm_result = await llm_chat(model=model, messages=messages, api_url=api_url)
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
    project_path: Optional[str] = None,
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

    if trace is None:
        trace = await start_trace(task_id, task_title)

    # --- Layer 1: Planner-Worker → select model ---
    from ..config import settings as app_settings
    provider_keys = app_settings.get_provider_keys()
    effective_providers = available_providers or list(provider_keys.keys())

    if provider_keys:
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
        model_resolution = {"model": model, "tier": tier, "reason": reason}
    else:
        return {"ok": False, "error": "未配置任何 LLM API Key（请在 .env 设置 ZHIPU_API_KEY 等）"}

    logger.info(f"[pipeline] Stage {stage_id}: model={model}, tier={tier}, reason={model_resolution['reason']}")

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
    if stage_skills:
        skill_context = "\n\n## 已启用技能\n" + "\n".join(
            f"### {s['name']}\n{s['prompt']}" for s in stage_skills
        )
        system_prompt += skill_context

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

    # --- Layer 4: LLM Call (with optional AgentRuntime tool loop) ---
    llm_result = None
    try:
        from ..agents.seed import AGENT_TOOLS
        agent_key = stage_conf.get("agent", "")
        stage_agent_id = _AGENT_KEY_TO_SEED_ID.get(agent_key, "")
        agent_tools = AGENT_TOOLS.get(stage_agent_id, [])

        if agent_tools:
            from .agent_runtime import AgentRuntime
            runtime = AgentRuntime(
                agent_id=stage_agent_id or stage_id,
                system_prompt=system_prompt,
                tools=agent_tools,
                model_preference={"execution": model},
                max_steps=5,
                temperature=0.7,
                task_id=task_id,
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
        else:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]
            api_url = app_settings.llm_api_url if tier == "local" else ""
            llm_result = await llm_chat(
                model=model,
                messages=messages,
                api_url=api_url,
                image_attachments=att_images if att_images else None,
            )
            if llm_result.get("error"):
                raise RuntimeError(f"LLM error: {llm_result['error']}")
            content = llm_result.get("content", "")
            token_usage = llm_result.get("usage") or {}
            prompt_tokens = token_usage.get("prompt_tokens", 0)
            completion_tokens = token_usage.get("completion_tokens", 0)

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

    # --- Layer 5: Self-Verify → validate output ---
    verification = verify_stage_output(
        stage_id=stage_id,
        role=role,
        output=content,
        previous_outputs=previous_outputs,
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

        # Write to delivery docs on disk
        try:
            from ..api.delivery_docs import write_stage_output
            await write_stage_output(stage_id, content)
        except Exception as doc_err:
            logger.warning(f"[pipeline] Failed to write delivery doc for {stage_id}: {doc_err}")

        # --- Quality Gate Evaluation ---
        gate_result = None
        try:
            from .quality_gates import evaluate_quality_gate, GateStatus
            from .self_verify import StageVerification, VerifyStatus, VerifyResult

            heuristic = StageVerification(
                stage_id=stage_id, role="",
                overall_status=VerifyStatus(verification.get("status", "pass")),
                checks=[VerifyResult(check_name=c.get("check_name", c.get("name", "")), status=VerifyStatus(c.get("status", "pass")), message=c.get("message", "")) for c in verification.get("checks", [])],
                auto_proceed=verification.get("auto_proceed", True),
            )
            task_template = db_task.template if db_task else None
            gate_result = await evaluate_quality_gate(
                stage_id, content,
                template=task_template,
                previous_outputs=outputs,
                heuristic_result=heuristic,
                skip_llm=force_continue,
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

                # Re-execute stage with reviewer feedback injected
                await emit_event("stage:rework", {
                    "taskId": task_id,
                    "stageId": stage_id,
                    "attempt": retries + 1,
                    "feedback": feedback[:300],
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

        # Mark stage as finalized
        if stage_id in db_stages:
            db_stages[stage_id].status = "done"
            db_stages[stage_id].completed_at = datetime.utcnow()
        await db.flush()

        if stage_id != stages[0]:
            prev_stage = stages[stages.index(stage_id) - 1]
            await update_quality_score(db, task_id, prev_stage, 0.8)

    # All stages complete — compute overall quality and mark task as done
    if db_task:
        db_task.status = "done"
        db_task.current_stage_id = "done"
        gate_scores = [
            s.gate_score for s in db_task.stages
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

    await complete_trace(trace.trace_id, status="completed")

    summary = {
        "stages_completed": len(results),
        "total_tokens": sum(r.get("tokens", {}).get("total", 0) for r in results),
        "total_cost_usd": round(sum(r.get("cost_usd", 0) for r in results), 6),
    }

    await emit_event("pipeline:auto-completed", {
        "taskId": task_id,
        "title": task_title,
        "stagesCompleted": summary["stages_completed"],
        "totalTokens": summary["total_tokens"],
        "totalCostUsd": summary["total_cost_usd"],
        "traceId": trace.trace_id,
        "hasDeliverable": deliverable_md is not None,
    })

    return {
        "ok": True,
        "results": results,
        "trace_id": trace.trace_id,
        "summary": summary,
    }


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
        for sid, output in previous_outputs.items():
            label = stage_label.get(sid, sid)
            if output:
                parts.append(f"## {label}\n{output}")

    return "\n\n".join(parts)
