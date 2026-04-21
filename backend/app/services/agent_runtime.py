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
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

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
        task_id: Optional[str] = None,
        dynamic_tools: Optional[Dict[str, Dict[str, Any]]] = None,
        dynamic_handlers: Optional[Dict[str, Callable[[Dict[str, Any]], Awaitable[str]]]] = None,
        role: Optional[str] = None,
    ):
        """
        dynamic_tools / dynamic_handlers: tools NOT in the global TOOL_REGISTRY,
            typically loaded per-execution from MCP servers. They merge into
            the OpenAI tool list and are dispatched via dynamic_handlers in
            `_execute_tool_call`.
        """
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self.tool_names = [t for t in tools if t in TOOL_REGISTRY]
        self.tools = get_tool_definitions(self.tool_names)
        self.dynamic_handlers: Dict[str, Callable[[Dict[str, Any]], Awaitable[str]]] = dynamic_handlers or {}
        # Keep the full descriptor (annotations, category, ...) around so
        # the sandbox layer can consult MCP-declared semantics instead of
        # falling back to prefix heuristics on every call.
        self.dynamic_tool_meta: Dict[str, Dict[str, Any]] = {}
        if dynamic_tools:
            for name, defn in dynamic_tools.items():
                if name in self.dynamic_handlers:
                    self.tools.append({
                        "name": defn.get("name", name),
                        "description": defn.get("description", ""),
                        "parameters": defn.get("parameters", {"type": "object", "properties": {}}),
                    })
                    self.dynamic_tool_meta[name] = defn
        self.model_preference = model_preference or {}
        self.max_steps = max_steps
        self.temperature = temperature
        self.task_id = task_id
        # Role drives the runtime skill-sandbox whitelist in tools/registry.py
        self.role = role

    async def execute(
        self,
        db: AsyncSession,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        image_attachments: Optional[List[Tuple[str, str]]] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a task using standard function calling loop.

        image_attachments: (mime, base64) pairs sent only on step 0 for multimodal providers.
        """
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

            if step == 0 and image_attachments:
                call_kwargs["image_attachments"] = image_attachments

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

        effective_task_id = task_id or self.task_id or self.agent_id
        await store_memory(
            db,
            task_id=effective_task_id,
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
        """Execute a tool call.

        Order of dispatch:
          1. dynamic_handlers (e.g. MCP tools loaded per execution)
          2. global TOOL_REGISTRY (with allowed_tools whitelist)
        """
        await emit_event("agent:tool-call", {
            "agentId": self.agent_id,
            "tool": tool_name,
            "input": {k: str(v)[:200] for k, v in tool_input.items()},
        })

        if tool_name in self.dynamic_handlers:
            # Apply role-based sandbox to MCP / dynamic tools too. The
            # policy is coarser (prefix-based) than the static whitelist
            # because we don't enumerate MCP tools at code-time. See
            # tools/registry.mcp_tool_allowed for the rules.
            from .tools.registry import mcp_tool_allowed, _audit_sandbox_denial

            verdict = mcp_tool_allowed(
                self.role,
                tool_name,
                metadata=self.dynamic_tool_meta.get(tool_name),
            )
            if not verdict["allowed"]:
                await _audit_sandbox_denial(
                    role=self.role or "",
                    tool_name=tool_name,
                    agent_id=self.agent_id,
                    task_id=self.task_id,
                    reason=f"[mcp] {verdict['reason']}",
                )
                result = (
                    f"Error: SANDBOX_DENIED — MCP tool '{tool_name}' "
                    f"blocked for role '{self.role}'. "
                    f"Reason: {verdict['reason']}"
                )
            else:
                handler = self.dynamic_handlers[tool_name]
                try:
                    result = await handler(tool_input)
                except Exception as e:
                    logger.error(f"[agent_runtime] dynamic tool {tool_name} crashed: {e}")
                    result = f"Error: dynamic tool '{tool_name}' failed: {e}"
        else:
            result = await execute_tool(
                tool_name, tool_input,
                allowed_tools=self.tool_names,
                role=self.role,
                agent_id=self.agent_id,
                task_id=self.task_id,
            )

        await emit_event("agent:tool-result", {
            "agentId": self.agent_id,
            "tool": tool_name,
            "outputLength": len(result),
        })

        return result

