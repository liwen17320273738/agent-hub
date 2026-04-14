"""
Agent Runtime — executes agents with tools, memory, and self-verification.

Each agent gets:
- Bound tools (per-agent, from registry with real implementations)
- Memory context injection
- Planner-Worker model separation
- Standard OpenAI function calling loop
- Output verification
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from .llm_router import chat_completion
from .planner_worker import resolve_model
from .memory import get_context_from_history, store_memory
from .self_verify import verify_stage_output
from .sse import emit_event
from .tools import TOOL_REGISTRY, execute_tool, get_tool_definitions

logger = logging.getLogger(__name__)


class AgentRuntime:
    """Runtime execution environment for a single agent."""

    def __init__(
        self,
        agent_id: str,
        system_prompt: str,
        tools: List[str],
        model_preference: Optional[Dict[str, str]] = None,
        max_steps: int = 10,
        temperature: float = 0.7,
    ):
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self.tool_names = [t for t in tools if t in TOOL_REGISTRY]
        self.tools = get_tool_definitions(self.tool_names)
        self.model_preference = model_preference or {}
        self.max_steps = max_steps
        self.temperature = temperature

    async def execute(
        self,
        db: AsyncSession,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a task using standard function calling loop."""
        await emit_event("agent:execute-start", {
            "agentId": self.agent_id, "task": task[:200],
        })

        planning_model = self.model_preference.get("planning", "")
        execution_model = self.model_preference.get("execution", "")

        model_info = resolve_model(
            role=self.agent_id,
            stage_id="agent-execution",
            preferred_model=planning_model or execution_model or None,
        )
        model = model_info["model"]

        history_context = await get_context_from_history(
            db,
            task_title=task[:200],
            task_description=task,
            current_stage="agent-execution",
            current_role=self.agent_id,
        )

        system = self.system_prompt
        if history_context:
            system += f"\n\n## 相关历史\n{history_context}"

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]

        if context:
            ctx_str = "\n".join(f"- {k}: {v}" for k, v in context.items() if v)
            if ctx_str:
                messages.append({"role": "user", "content": f"## 上下文\n{ctx_str}"})

        observations: List[str] = []
        final_output = ""

        for step in range(self.max_steps):
            # 使用标准 function calling 格式
            call_kwargs: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": self.temperature,
            }
            if self.tools:
                # 直接传 function 定义列表，llm_router 负责按 provider 格式包装
                call_kwargs["tools"] = self.tools
                call_kwargs["tool_choice"] = "auto"

            result = await chat_completion(**call_kwargs)

            if "error" in result:
                return {"ok": False, "error": result["error"], "step": step}

            # 检查是否有 function call
            tool_calls = result.get("tool_calls") or []
            content = result.get("content", "")

            if not tool_calls:
                # 没有工具调用，模型已给出最终答案
                final_output = content
                break

            # 将 assistant 消息（含 tool_calls）加入历史
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls,
            })

            # 逐个执行工具调用，将结果追加到消息
            for tc in tool_calls:
                tool_name = tc.get("function", {}).get("name", "")
                try:
                    tool_input = json.loads(tc.get("function", {}).get("arguments", "{}"))
                except json.JSONDecodeError:
                    tool_input = {}

                observation = await self._execute_tool_call(tool_name, tool_input)
                observations.append(f"[{tool_name}]: {observation}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": observation,
                })

        verification = verify_stage_output(
            stage_id="agent-output", role=self.agent_id, output=final_output,
        )

        await store_memory(
            db,
            task_id=self.agent_id,
            stage_id="agent-execution",
            role=self.agent_id,
            title=task[:200],
            content=final_output,
            quality_score=0.8 if verification.overall_status.value == "pass" else 0.5,
        )

        await emit_event("agent:execute-complete", {
            "agentId": self.agent_id,
            "steps": len(observations),
            "outputLength": len(final_output),
            "verification": verification.overall_status.value,
        })

        return {
            "ok": True,
            "content": final_output,
            "steps": len(observations),
            "observations": observations,
            "model": model,
            "verification": verification.overall_status.value,
        }

    async def _execute_tool_call(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """Execute a tool call using the real tool registry."""
        await emit_event("agent:tool-call", {
            "agentId": self.agent_id,
            "tool": tool_name,
            "input": {k: str(v)[:200] for k, v in tool_input.items()},
        })

        result = await execute_tool(tool_name, tool_input, allowed_tools=self.tool_names)

        await emit_event("agent:tool-result", {
            "agentId": self.agent_id,
            "tool": tool_name,
            "outputLength": len(result),
        })

        return result

