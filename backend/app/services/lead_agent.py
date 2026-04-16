"""
Lead Agent — deer-flow style intelligent task decomposition & execution.

Replaces the Node.js leadAgent.mjs with full Python maturation stack:
- Planner-Worker model separation for planning vs execution
- DAG-based subtask dependency resolution
- Self-verification on each subtask output
- Memory injection from past tasks
- SSE event broadcasting
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .llm_router import chat_completion
from .planner_worker import resolve_model
from .memory import get_context_from_history, store_memory
from .self_verify import verify_stage_output
from .sse import emit_event
from .observability import start_trace, start_span, complete_span, complete_trace

logger = logging.getLogger(__name__)

LEAD_AGENT_SYSTEM = """你是 OpenClaw Lead Agent，AI 军团的总指挥。你的职责是：

1. **分析需求**：理解用户意图，判断复杂度
2. **任务分解**：将复杂需求拆分为可并行执行的子任务
3. **角色分配**：为每个子任务指定最合适的专家角色
4. **质量把控**：审查各子任务产出，决定是否通过

## 可用角色
- product-manager: 产品经理，负责 PRD、用户故事、验收标准
- developer: 技术架构师，负责技术方案、API 设计、数据模型
- executor: 开发执行者，负责代码实现
- qa-lead: QA 负责人，负责测试方案和验证
- orchestrator: 总控评审，负责验收

## 输出格式
你必须以 JSON 格式输出任务分解计划：
```json
{
  "analysis": "对需求的理解和分析",
  "subtasks": [
    {
      "id": "subtask-1",
      "title": "子任务标题",
      "role": "product-manager",
      "prompt": "给该角色的详细指令",
      "dependsOn": [],
      "priority": 1
    }
  ],
  "strategy": "parallel | sequential | mixed",
  "estimatedComplexity": "low | medium | high"
}
```

## 规则
- 简单需求(low)：1-2 个子任务即可
- 中等需求(medium)：3-4 个子任务，可并行
- 复杂需求(high)：5+ 个子任务，注意依赖关系
- 每次最多 5 个并行子任务
- 子任务的 prompt 必须包含充足上下文，子 agent 无法看到其他子任务的内容"""


ROLE_PROMPTS = {
    "product-manager": "你是一位资深产品经理，请输出结构化 PRD（包含用户故事、验收标准、功能范围、里程碑）。",
    "developer": "你是一位资深技术架构师，请输出技术方案（技术选型、数据模型、API 设计、实现步骤、风险点）。",
    "qa-lead": "你是一位资深 QA 负责人，请输出测试方案（测试用例、边界条件、回归关注点、PASS/FAIL 结论）。",
    "orchestrator": "你是项目总控，请审查所有产出并给出验收评审（打分、覆盖度、结论）。",
    "executor": "你是开发执行者，请列出需要执行的具体代码变更清单。",
}


async def analyze_and_decompose(
    db: AsyncSession,
    task_id: str,
    title: str,
    description: str,
    previous_outputs: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Lead Agent analyzes a requirement and produces a subtask plan."""
    await emit_event("lead-agent:analyzing", {"taskId": task_id, "title": title})

    history = await get_context_from_history(
        db, task_title=title, task_description=description,
        current_stage="lead-agent", current_role="lead-agent",
    )
    system = LEAD_AGENT_SYSTEM
    if history:
        system += f"\n\n## 历史上下文\n{history}"

    parts = [
        f"## 需求标题\n{title}",
        f"## 需求描述\n{description or '(无详细描述)'}",
    ]
    if previous_outputs:
        for stage_id, output in previous_outputs.items():
            if output:
                parts.append(f"### {stage_id}\n{output}")
    user_msg = "\n\n".join(parts)

    planning_model = resolve_model(
        role="lead-agent", stage_id="lead-agent", complexity="high",
    )

    result = await chat_completion(
        model=planning_model["model"],
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
    )

    if "error" in result:
        await emit_event("lead-agent:error", {"taskId": task_id, "error": result["error"]})
        return {"ok": False, "error": result["error"]}

    content = result["content"]
    plan = _parse_plan(content, title, description)

    await emit_event("lead-agent:plan-ready", {
        "taskId": task_id,
        "plan": {
            "analysis": plan.get("analysis", ""),
            "subtaskCount": len(plan.get("subtasks", [])),
            "strategy": plan.get("strategy", "sequential"),
            "complexity": plan.get("estimatedComplexity", "medium"),
        },
    })

    return {"ok": True, "plan": plan, "rawAnalysis": content}


async def execute_subtasks(
    db: AsyncSession,
    task_id: str,
    subtasks: List[Dict[str, Any]],
    trace_id: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Execute subtasks in dependency-ordered batches with parallel execution."""
    results: Dict[str, Dict[str, Any]] = {}
    groups = _group_by_dependency(subtasks)

    for group in groups:
        await emit_event("subtasks:batch-start", {
            "taskId": task_id,
            "batchSize": len(group),
            "subtaskIds": [s["id"] for s in group],
        })

        coros = [
            _execute_one_subtask(db, task_id, st, results, trace_id)
            for st in group
        ]
        batch_results = await asyncio.gather(*coros, return_exceptions=True)

        for i, subtask in enumerate(group):
            settled = batch_results[i]
            if isinstance(settled, Exception):
                results[subtask["id"]] = {
                    "ok": False,
                    "error": str(settled),
                    "subtaskId": subtask["id"],
                }
            else:
                results[subtask["id"]] = settled

    return results


async def run_smart_pipeline(
    db: AsyncSession,
    task_id: str,
    title: str,
    description: str,
) -> Dict[str, Any]:
    """Full smart pipeline: decompose → execute → collect → verify."""
    await emit_event("pipeline:smart-start", {"taskId": task_id, "title": title})

    trace = await start_trace(task_id, title)

    decomposition = await analyze_and_decompose(db, task_id, title, description)
    if not decomposition["ok"]:
        await complete_trace(trace.trace_id, status="failed")
        return decomposition

    plan = decomposition["plan"]
    subtask_results = await execute_subtasks(
        db, task_id, plan.get("subtasks", []), trace_id=trace.trace_id,
    )

    stage_mapping = {
        "product-manager": "planning",
        "developer": "architecture",
        "executor": "development",
        "qa-lead": "testing",
        "orchestrator": "reviewing",
        "devops": "deployment",
        "architect": "architecture",
    }
    stage_outputs: Dict[str, str] = {}
    for _, result in subtask_results.items():
        if not result.get("ok"):
            continue
        target_stage = stage_mapping.get(result.get("role", ""))
        if target_stage:
            stage_outputs[target_stage] = result.get("content", "")

    # Persist stage outputs to DB
    from datetime import datetime
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from ..models.pipeline import PipelineTask, PipelineStage
    import uuid as _uuid
    try:
        task_uuid = _uuid.UUID(task_id)
        db_result = await db.execute(
            select(PipelineTask)
            .options(selectinload(PipelineTask.stages))
            .where(PipelineTask.id == task_uuid)
        )
        db_task = db_result.scalar_one_or_none()
        if db_task:
            db_stage_map = {s.stage_id: s for s in db_task.stages}
            for stage_id, output in stage_outputs.items():
                if stage_id in db_stage_map:
                    db_stage_map[stage_id].output = output
                    db_stage_map[stage_id].status = "done"
                    db_stage_map[stage_id].completed_at = datetime.utcnow()
            last_done = max(
                (PIPELINE_STAGE_ORDER.index(sid) for sid in stage_outputs if sid in PIPELINE_STAGE_ORDER),
                default=-1,
            )
            if last_done >= 0 and last_done + 1 < len(PIPELINE_STAGE_ORDER):
                next_sid = PIPELINE_STAGE_ORDER[last_done + 1]
                db_task.current_stage_id = next_sid
                if next_sid in db_stage_map:
                    db_stage_map[next_sid].status = "active"
                    db_stage_map[next_sid].started_at = datetime.utcnow()
            elif last_done + 1 >= len(PIPELINE_STAGE_ORDER):
                db_task.status = "done"
                db_task.current_stage_id = "done"
            await db.flush()
    except Exception as e:
        logger.warning(f"Failed to persist smart-run results to DB: {e}")

    completed = sum(1 for r in subtask_results.values() if r.get("ok"))
    await complete_trace(trace.trace_id, status="completed")

    await emit_event("pipeline:smart-completed", {
        "taskId": task_id,
        "subtaskCount": len(plan.get("subtasks", [])),
        "completedSubtasks": completed,
    })

    return {
        "ok": True,
        "plan": plan,
        "subtaskResults": subtask_results,
        "stageOutputs": stage_outputs,
        "traceId": trace.trace_id,
    }


PIPELINE_STAGE_ORDER = ["planning", "architecture", "development", "testing", "reviewing", "deployment"]


# --- internals ---

async def _execute_one_subtask(
    db: AsyncSession,
    task_id: str,
    subtask: Dict[str, Any],
    previous_results: Dict[str, Dict[str, Any]],
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    subtask_id = subtask.get("id", "unknown")
    role = subtask.get("role", "developer")

    await emit_event("subtask:start", {
        "taskId": task_id, "subtaskId": subtask_id,
        "title": subtask.get("title", ""), "role": role,
    })

    context_from_deps = ""
    for dep_id in subtask.get("dependsOn", []):
        dep = previous_results.get(dep_id)
        if dep and dep.get("ok"):
            context_from_deps += f"\n\n### 前置任务 [{dep_id}] 产出\n{dep.get('content', '')}"

    system_prompt = ROLE_PROMPTS.get(role, "请处理以下任务。")
    user_prompt = subtask.get("prompt", "") + context_from_deps

    execution_model = resolve_model(
        role=role, stage_id="subtask", complexity="medium",
    )

    result = await chat_completion(
        model=execution_model["model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    if "error" in result:
        await emit_event("subtask:failed", {
            "taskId": task_id, "subtaskId": subtask_id, "error": result["error"],
        })
        return {"ok": False, "error": result["error"], "subtaskId": subtask_id, "role": role}

    content = result["content"]

    verification = verify_stage_output(
        stage_id="subtask", role=role, output=content,
    )

    await store_memory(
        db, task_id=task_id, stage_id="subtask", role=role,
        title=subtask.get("title", ""), content=content,
        quality_score=0.8 if verification.overall_status.value == "pass" else 0.5,
    )

    await emit_event("subtask:completed", {
        "taskId": task_id, "subtaskId": subtask_id,
        "title": subtask.get("title", ""), "role": role,
        "outputLength": len(content),
    })

    return {
        "ok": True, "content": content, "subtaskId": subtask_id,
        "title": subtask.get("title", ""), "role": role,
        "verification": verification.overall_status.value,
        "model": execution_model["model"],
    }


def _parse_plan(content: str, title: str, description: str) -> Dict[str, Any]:
    """Extract JSON plan from LLM output, with fallback."""
    try:
        match = re.search(r"```json\s*([\s\S]*?)```", content)
        json_str = match.group(1) if match else content
        return json.loads(json_str.strip())
    except (json.JSONDecodeError, AttributeError):
        return {
            "analysis": content,
            "subtasks": [{
                "id": "subtask-1",
                "title": title,
                "role": "product-manager",
                "prompt": f"请针对以下需求进行处理:\n{title}\n{description}",
                "dependsOn": [],
                "priority": 1,
            }],
            "strategy": "sequential",
            "estimatedComplexity": "medium",
        }


def _group_by_dependency(subtasks: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Group subtasks into dependency-ordered batches for parallel execution."""
    groups: List[List[Dict[str, Any]]] = []
    done: set = set()
    remaining = list(subtasks)

    while remaining:
        batch = [
            s for s in remaining
            if not s.get("dependsOn") or all(d in done for d in s["dependsOn"])
        ]
        if not batch:
            groups.append(remaining)
            break
        groups.append(batch)
        for s in batch:
            done.add(s["id"])
        remaining = [s for s in remaining if s["id"] not in done]

    return groups
