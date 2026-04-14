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
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession

from .planner_worker import resolve_model, ModelTier
from .memory import store_memory, get_context_from_history, update_quality_score
from .self_verify import verify_stage_output, VerifyStatus
from .guardrails import evaluate_guardrail, GuardrailLevel
from .observability import (
    start_trace, start_span, complete_span, complete_trace, PipelineTrace,
)
from .llm_router import chat_completion as llm_chat
from .token_tracker import estimate_cost

logger = logging.getLogger(__name__)

STAGE_ROLE_PROMPTS = {
    "planning": {
        "role": "product-manager",
        "system": """你是一位资深产品经理。根据以下需求，输出一份结构化 PRD，必须包含：
1. 需求概述（一句话描述核心价值）
2. 目标用户
3. 功能范围（IN-SCOPE / OUT-OF-SCOPE）
4. 用户故事（至少3条，格式: As a... I want... So that...）
5. 验收标准（可量化的条件列表）
6. 非功能需求（性能/安全/兼容性）
7. 里程碑和优先级
用 Markdown 格式输出。""",
    },
    "architecture": {
        "role": "architect",
        "system": """你是一位资深技术架构师。根据 PRD 输出技术方案，必须包含：
1. 技术选型和理由
2. 系统架构（组件/模块划分）
3. 数据模型设计
4. API 接口设计（RESTful 路由表）
5. 实现步骤（按优先级排序，每步预估工时）
6. 风险点和降级方案
7. 文件变更清单
用 Markdown 格式输出。""",
    },
    "development": {
        "role": "developer",
        "system": """你是一位全栈高级开发工程师。根据 PRD 和架构方案，输出完整的实现方案：
1. 项目结构（目录树）
2. 核心模块代码（关键文件的完整代码）
3. 数据库 Schema / Migration
4. API 路由实现
5. 前端页面/组件实现
6. 配置文件
7. 依赖列表（package.json / requirements.txt）
输出实际可运行的代码，用 Markdown 代码块标注语言和文件路径。""",
    },
    "testing": {
        "role": "qa-lead",
        "system": """你是一位资深 QA 负责人。根据 PRD 和开发产出，输出测试验证报告：
1. 测试范围
2. 测试用例清单（编号 + 步骤 + 预期结果）
3. 边界条件和异常场景
4. 回归关注点
5. 性能/安全验证项
6. 测试代码（单元测试 + 集成测试的实际代码）
7. 结论：PASS ✅ 或 NEEDS WORK ❌（附具体原因）
用 Markdown 格式输出。""",
    },
    "reviewing": {
        "role": "orchestrator",
        "system": """你是项目总控。审查所有阶段产出，输出验收评审报告：
1. 各阶段完成度评估（每个阶段打分 1-10）
2. 需求覆盖度检查
3. 质量风险评估
4. 代码质量评估（安全性、可维护性、性能）
5. 验收结论：APPROVED ✅ 或 REJECTED ❌
6. 如 REJECTED，明确指出需要返回哪个阶段修改什么
用 Markdown 格式输出。""",
    },
    "deployment": {
        "role": "devops",
        "system": """你是一位 DevOps 工程师。根据前面所有阶段的产出，生成部署方案：
1. 部署环境要求（Node 版本、Python 版本、数据库等）
2. 构建命令和步骤
3. Docker 配置（Dockerfile + docker-compose.yml）
4. CI/CD 流水线配置（GitHub Actions / GitLab CI）
5. 环境变量清单
6. 部署检查清单（pre-deploy / post-deploy）
7. 回滚方案
8. 监控和告警配置
用 Markdown 格式输出，包含实际可用的配置文件代码。""",
    },
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

    role = stage_conf["role"]
    system_prompt = stage_conf["system"]

    if trace is None:
        trace = start_trace(task_id, task_title)

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
    span = start_span(
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
    )

    user_message = _build_user_message(task_title, task_description, stage_id, previous_outputs)
    if history_context:
        system_prompt += f"\n\n{history_context}"

    span.input_length = len(system_prompt) + len(user_message)

    # --- Layer 7: Guardrail pre-check ---
    guardrail_result = evaluate_guardrail(
        action=f"execute_{stage_id}",
        stage_id=stage_id,
        role=role,
        task_id=task_id,
    )

    if not guardrail_result["proceed"]:
        complete_span(
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

    # --- Layer 4: LLM Call ---
    try:
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
        complete_span(span.span_id, status="failed", error=str(e))
        return {"ok": False, "error": str(e)}

    # --- Layer 5: Self-Verify → validate output ---
    verification = verify_stage_output(
        stage_id=stage_id,
        role=role,
        output=content,
        previous_outputs=previous_outputs,
    )

    # --- Layer 3 + 6: Tool Schema (record execution) ---
    provider = llm_result.get("provider", "openai")
    cost_estimate = estimate_cost(provider, model, prompt_tokens, completion_tokens)

    # --- Layer 8: Complete trace span ---
    complete_span(
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
) -> Dict[str, Any]:
    """
    Execute a full pipeline with all maturation layers.
    Stops if verification fails or guardrail blocks.
    """
    if stages is None:
        stages = list(STAGE_ROLE_PROMPTS.keys())

    trace = start_trace(task_id, task_title)
    outputs: Dict[str, str] = {}
    results: List[Dict[str, Any]] = []

    for stage_id in stages:
        logger.info(f"[pipeline] Executing stage: {stage_id}")

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
            if result.get("blocked"):
                complete_trace(trace.trace_id, status="blocked")
                return {
                    "ok": False,
                    "blocked": True,
                    "stopped_at": stage_id,
                    "results": results,
                    "trace_id": trace.trace_id,
                }
            complete_trace(trace.trace_id, status="failed")
            return {
                "ok": False,
                "stopped_at": stage_id,
                "error": result.get("error"),
                "results": results,
                "trace_id": trace.trace_id,
            }

        outputs[stage_id] = result.get("content", "")

        verification = result.get("verification", {})
        if not verification.get("auto_proceed", True):
            complete_trace(trace.trace_id, status="paused")
            return {
                "ok": False,
                "paused": True,
                "stopped_at": stage_id,
                "reason": "Verification failed, requires human review",
                "results": results,
                "trace_id": trace.trace_id,
            }

        # Update quality scores based on downstream success
        if stage_id != stages[0]:
            prev_stage = stages[stages.index(stage_id) - 1]
            await update_quality_score(db, task_id, prev_stage, 0.8)

    complete_trace(trace.trace_id, status="completed")

    return {
        "ok": True,
        "results": results,
        "trace_id": trace.trace_id,
        "summary": {
            "stages_completed": len(results),
            "total_tokens": sum(r.get("tokens", {}).get("total", 0) for r in results),
            "total_cost_usd": round(sum(r.get("cost_usd", 0) for r in results), 6),
        },
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
