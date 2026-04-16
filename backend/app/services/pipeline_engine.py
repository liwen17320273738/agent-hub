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
    "ceo-agent": "wayne-ceo",
    "architect-agent": "wayne-cto",
    "developer-agent": "wayne-developer",
    "qa-agent": "wayne-qa",
    "devops-agent": "wayne-devops",
}

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
        "reviewer_agent": "ceo-agent",
        "reviewer_prompt": """你是 CEO Agent，现在需要审阅测试 Agent 的测试报告。
请从产品验收角度评估：
1. 测试覆盖率是否达标？
2. 发现的缺陷严重程度如何？
3. 是否满足 PRD 中定义的验收标准？

最终结论（第一行必须是以下之一）：
- **APPROVE** — 测试通过，可以进入验收评审
- **REJECT** — 需要修改（列出具体问题，指明退回到哪个阶段）""",
        "human_gate": False,
    },
    "reviewing": {
        "reviewer_agent": None,
        "reviewer_prompt": "",
        "human_gate": True,
    },
    "deployment": {
        "reviewer_agent": None,
        "reviewer_prompt": "",
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
        "role": "orchestrator",
        "agent": "ceo-agent",
        "system": """你是 CEO Agent（总指挥），现在进入验收评审环节。你需要以 CEO 的视角审查所有阶段产出，做出最终决策。

你的团队（架构师、开发、测试、运维 Agent）已经完成了各自的工作。现在你需要：

输出验收评审报告：
1. **各阶段评分** — 每个阶段打分 1-10，附评分理由
   - 需求规划（PRD质量）
   - 架构设计（方案合理性）
   - 开发实现（代码质量）
   - 测试验证（覆盖完整度）
2. **需求覆盖度** — 逐条核对 PRD 中的用户故事和验收标准
3. **风险评估** — 技术债务、安全隐患、性能瓶颈
4. **质量总评** — 代码可维护性、架构扩展性、用户体验
5. **最终结论** — **APPROVED ✅** 或 **REJECTED ❌**
   - 如 APPROVED：附上线建议和注意事项
   - 如 REJECTED：明确指出需要退回到哪个阶段修改什么（格式: `REJECT_TO: <stage_id>`）

⚠️ 你的决策将直接影响是否进入部署阶段。请确保评审全面、客观。
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
        "architecture": "技术架构方案",
        "development": "代码实现",
        "testing": "测试报告",
        "reviewing": "验收评审",
        "deployment": "部署方案",
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
    system_prompt = stage_conf["system"]

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
            )
            runtime_result = await runtime.execute(
                db, task=user_message, context=previous_outputs,
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
                checks=[VerifyResult(check_name=c.get("name", ""), status=VerifyStatus(c.get("status", "pass")), message=c.get("message", "")) for c in verification.get("checks", [])],
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
            "architecture": "技术架构方案",
            "development": "开发实现产出",
            "testing": "测试验证报告",
            "reviewing": "审查验收报告",
            "deployment": "部署方案",
        }
        for sid, output in previous_outputs.items():
            label = stage_label.get(sid, sid)
            if output:
                parts.append(f"## {label}\n{output}")

    return "\n\n".join(parts)
