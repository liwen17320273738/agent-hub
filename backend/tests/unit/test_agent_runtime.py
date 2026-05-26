"""Unit tests for AgentRuntime and agent delegation.

Covers:
- AgentRuntime initialization and tool binding
- AgentRuntime.execute with synthetic (no-tool) LLM response
- AgentRuntime._execute_tool_call dispatching (dynamic vs registry)
- delegate_to_agent parameter validation and role resolution
- Edge cases: empty tools, missing role, empty task, unknown role
- Self-verification integration

Why these tests matter:
AgentRuntime runs the core ReAct loop for every pipeline stage and
agent delegation call. A regression here breaks the entire execution
chain — no agent produces output until this module is correct.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_runtime import AgentRuntime
from app.services.agent_delegate import ROLE_TO_SEED_ID


# ── helpers ──────────────────────────────────────────────────────────────

def _make_chat_result(content: str, tool_calls: list | None = None) -> dict:
    """Simulate a non-streaming LLM response dict."""
    return {
        "content": content,
        "tool_calls": tool_calls or [],
        "error": None,
    }


# ── AgentRuntime construction ────────────────────────────────────────────

class TestAgentRuntimeInit:
    """Construction / tool-binding."""

    def test_basic_init(self):
        runtime = AgentRuntime(
            agent_id="test-agent",
            system_prompt="You are a test agent.",
            tools=["file_read"],
        )
        assert runtime.agent_id == "test-agent"
        assert runtime.system_prompt == "You are a test agent."
        assert "file_read" in runtime.tool_names
        assert len(runtime.tools) == 1
        assert runtime.tools[0]["name"] == "file_read"
        assert runtime.max_steps == 10
        assert runtime.temperature == 0.7

    def test_init_with_unknown_tool_is_filtered(self):
        """Tools that do not exist in TOOL_REGISTRY are silently filtered."""
        runtime = AgentRuntime(
            agent_id="test-agent",
            system_prompt="",
            tools=["file_read", "__does_not_exist_42__"],
        )
        assert "__does_not_exist_42__" not in runtime.tool_names
        assert "file_read" in runtime.tool_names

    def test_init_with_model_preference(self):
        runtime = AgentRuntime(
            agent_id="test-agent",
            system_prompt="",
            tools=[],
            model_preference={"planning": "claude-sonnet-4", "execution": "gpt-4o"},
        )
        assert runtime.model_preference["planning"] == "claude-sonnet-4"

    def test_init_with_max_steps(self):
        runtime = AgentRuntime(agent_id="test-agent", system_prompt="", tools=[], max_steps=3)
        assert runtime.max_steps == 3

    def test_init_with_dynamic_tools(self):
        handler = AsyncMock(return_value="handler result")
        runtime = AgentRuntime(
            agent_id="test-agent",
            system_prompt="",
            tools=[],
            dynamic_tools={
                "custom_search": {
                    "name": "custom_search",
                    "description": "Search custom data source",
                    "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                },
            },
            dynamic_handlers={"custom_search": handler},
        )
        assert "custom_search" in runtime.dynamic_handlers
        names = [t["name"] for t in runtime.tools]
        assert "custom_search" in names

    def test_dynamic_tool_meta_stored(self):
        """dynamic_tool_meta should preserve full descriptor for sandbox layer."""
        meta = {
            "name": "my_tool",
            "description": "desc",
            "parameters": {"type": "object", "properties": {}},
            "category": "custom",
        }
        runtime = AgentRuntime(
            agent_id="a", system_prompt="", tools=[],
            dynamic_tools={"my_tool": meta}, dynamic_handlers={"my_tool": AsyncMock()},
        )
        assert runtime.dynamic_tool_meta["my_tool"]["category"] == "custom"

    def test_role_is_stored(self):
        runtime = AgentRuntime(agent_id="a", system_prompt="", tools=[], role="qa")
        assert runtime.role == "qa"


# ── AgentRuntime.execute ────────────────────────────────────────────────

class TestAgentRuntimeExecute:
    """Core execution loop."""

    @pytest.mark.asyncio
    @patch("app.services.agent_runtime.chat_completion")
    async def test_simple_no_tool_execution(self, mock_chat, db: AsyncSession):
        """Agent receives a task and produces output without calling any tools."""
        mock_chat.return_value = _make_chat_result("This is the final answer.")

        runtime = AgentRuntime(
            agent_id="test-agent",
            system_prompt="You are a helpful assistant.",
            tools=[],
        )
        result = await runtime.execute(db, task="Say hello")

        assert result["ok"] is True
        assert result["content"] == "This is the final answer."
        assert result["steps"] == 0
        assert "model" in result
        assert "verification" in result

    @pytest.mark.asyncio
    @patch("app.services.agent_runtime.chat_completion")
    async def test_execute_with_image_attachments(self, mock_chat, db: AsyncSession):
        """image_attachments are forwarded on step 0 only."""
        mock_chat.return_value = _make_chat_result("Done")
        runtime = AgentRuntime(agent_id="test", system_prompt="", tools=[])
        result = await runtime.execute(
            db, task="describe", image_attachments=[("image/png", "base64data")],
        )
        assert result["ok"] is True

    @pytest.mark.asyncio
    @patch("app.services.agent_runtime.chat_completion")
    async def test_execute_propagates_error(self, mock_chat, db: AsyncSession):
        """LLM error is propagated back."""
        mock_chat.return_value = {"error": "API key not configured", "status": 503}
        runtime = AgentRuntime(agent_id="test", system_prompt="", tools=[])
        result = await runtime.execute(db, task="fail")
        assert result["ok"] is False
        assert "API key not configured" in result["error"]

    @pytest.mark.asyncio
    @patch("app.services.agent_runtime.chat_completion")
    async def test_execute_runs_tool_call_cycle(self, mock_chat, db: AsyncSession):
        """Agent calls a tool, gets result, then produces final output."""
        mock_chat.side_effect = [
            # Step 0: LLM calls file_read tool
            {
                "content": "Let me read the file.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "file_read",
                            "arguments": '{"path": "/tmp/test.txt"}',
                        },
                    }
                ],
                "error": None,
            },
            # Step 1: LLM produces final output after tool result
            _make_chat_result("The file contains: hello world"),
        ]

        runtime = AgentRuntime(
            agent_id="test-agent",
            system_prompt="You are a helpful assistant.",
            tools=["file_read"],
            max_steps=5,
        )
        result = await runtime.execute(db, task="Read and summarize")

        assert result["ok"] is True
        assert "hello world" in result["content"]
        assert result["steps"] >= 1

    @pytest.mark.asyncio
    @patch("app.services.agent_runtime.chat_completion")
    async def test_execute_handles_dynamic_tool(self, mock_chat, db: AsyncSession):
        """Dynamic tools are dispatched through dynamic_handlers."""
        handler = AsyncMock(return_value='{"result": "custom data"}')
        mock_chat.side_effect = [
            {
                "content": "Using custom tool",
                "tool_calls": [
                    {
                        "id": "call_dyn",
                        "function": {
                            "name": "custom_search",
                            "arguments": '{"q": "test"}',
                        },
                    }
                ],
                "error": None,
            },
            _make_chat_result("Custom search done."),
        ]

        runtime = AgentRuntime(
            agent_id="test-agent",
            system_prompt="",
            tools=[],
            dynamic_tools={
                "custom_search": {
                    "name": "custom_search",
                    "description": "Search",
                    "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                },
            },
            dynamic_handlers={"custom_search": handler},
            max_steps=5,
        )
        result = await runtime.execute(db, task="Search something")
        assert result["ok"] is True
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.services.agent_runtime.chat_completion")
    async def test_synth_output_when_empty(self, mock_chat, db: AsyncSession):
        """When the model returns empty content after tool calls, a synthesis round is triggered."""
        mock_chat.side_effect = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "file_read", "arguments": '{"path": "x"}'},
                    }
                ],
                "error": None,
            },
            _make_chat_result("Synthesized final output"),
        ]
        runtime = AgentRuntime(agent_id="test", system_prompt="", tools=["file_read"], max_steps=5)
        result = await runtime.execute(db, task="do it")
        assert result["ok"] is True
        assert result["content"] == "Synthesized final output"


# ── _execute_tool_call ───────────────────────────────────────────────────

class TestAgentRuntimeExecuteToolCall:

    @pytest.mark.asyncio
    async def test_execute_dynamic_tool(self):
        handler = AsyncMock(return_value="dynamic result")
        runtime = AgentRuntime(
            agent_id="test", system_prompt="", tools=[],
            dynamic_tools={"my_tool": {"name": "my_tool", "description": "", "parameters": {}}},
            dynamic_handlers={"my_tool": handler},
        )
        result = await runtime._execute_tool_call("my_tool", {"key": "val"})
        assert result == "dynamic result"
        handler.assert_awaited_once_with({"key": "val"})

    @pytest.mark.asyncio
    async def test_execute_registry_tool(self):
        runtime = AgentRuntime(
            agent_id="test", system_prompt="", tools=["file_read"],
        )
        result = await runtime._execute_tool_call("file_read", {"path": "/nonexistent"})
        assert "Error" in result or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        runtime = AgentRuntime(agent_id="test", system_prompt="", tools=[])
        result = await runtime._execute_tool_call("__bogus_tool__", {})
        assert "unknown" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_dynamic_tool_precedence_over_registry(self):
        """dynamic_handlers take priority over TOOL_REGISTRY for same name."""
        handler = AsyncMock(return_value="from dynamic")
        runtime = AgentRuntime(
            agent_id="test", system_prompt="", tools=[],
            dynamic_tools={"file_read": {"name": "file_read", "description": "", "parameters": {}}},
            dynamic_handlers={"file_read": handler},
        )
        result = await runtime._execute_tool_call("file_read", {})
        assert result == "from dynamic"


# ── delegate_to_agent ────────────────────────────────────────────────────

class TestDelegateToAgent:

    @pytest.mark.asyncio
    @patch("app.services.agent_delegate.async_session_factory")
    @patch("app.services.agent_delegate.AgentRuntime")
    async def test_delegate_basic(self, mock_runtime_cls, mock_factory):
        """Happy path: delegate resolves role, spins up runtime, returns answer."""
        mock_runtime = AsyncMock()
        mock_runtime.execute.return_value = {"ok": True, "content": "Security analysis complete.", "steps": 2}
        mock_runtime_cls.return_value = mock_runtime

        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_factory.return_value = mock_session

        from app.services.agent_delegate import delegate_to_agent
        result = await delegate_to_agent({"role": "security", "task": "Review auth module"})
        assert "[delegate→security" in result
        assert "Security analysis complete." in result
        assert "steps=2" in result

    @pytest.mark.asyncio
    async def test_delegate_missing_role(self):
        from app.services.agent_delegate import delegate_to_agent
        result = await delegate_to_agent({"task": "do something"})
        assert "both 'role' and 'task' are required" in result

    @pytest.mark.asyncio
    async def test_delegate_missing_task(self):
        from app.services.agent_delegate import delegate_to_agent
        result = await delegate_to_agent({"role": "security"})
        assert "both 'role' and 'task' are required" in result

    @pytest.mark.asyncio
    async def test_delegate_unknown_role(self):
        from app.services.agent_delegate import delegate_to_agent
        result = await delegate_to_agent({"role": "wizard", "task": "cast spell"})
        assert "unknown role" in result

    def test_delegate_role_aliases_resolve(self):
        """Role aliases (frontend, backend, tester, etc.) should resolve to correct seed_id."""
        assert ROLE_TO_SEED_ID["frontend"] == "Agent-developer"
        assert ROLE_TO_SEED_ID["backend"] == "Agent-developer"
        assert ROLE_TO_SEED_ID["tester"] == "Agent-qa"
        assert ROLE_TO_SEED_ID["ui"] == "Agent-designer"
        assert ROLE_TO_SEED_ID["ux"] == "Agent-designer"
        assert ROLE_TO_SEED_ID["sre"] == "Agent-devops"

    @pytest.mark.asyncio
    @patch("app.services.agent_delegate.AgentRuntime")
    @patch("app.services.agent_delegate.async_session_factory")
    async def test_delegate_execution_failure(self, mock_factory, mock_runtime_cls):
        """When runtime returns ok=False, delegate returns failure message."""
        mock_runtime = AsyncMock()
        mock_runtime.execute.return_value = {"ok": False, "error": "LLM call failed"}
        mock_runtime_cls.return_value = mock_runtime

        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_factory.return_value = mock_session

        from app.services.agent_delegate import delegate_to_agent
        result = await delegate_to_agent({"role": "qa", "task": "run tests"})
        assert "Error" in result
        assert "LLM call failed" in result

    @pytest.mark.asyncio
    @patch("app.services.agent_delegate.AgentRuntime")
    @patch("app.services.agent_delegate.async_session_factory")
    async def test_delegate_empty_response(self, mock_factory, mock_runtime_cls):
        """When content is empty, return sentinel."""
        mock_runtime = AsyncMock()
        mock_runtime.execute.return_value = {"ok": True, "content": "", "steps": 0}
        mock_runtime_cls.return_value = mock_runtime

        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_factory.return_value = mock_session

        from app.services.agent_delegate import delegate_to_agent
        result = await delegate_to_agent({"role": "data", "task": "analyze"})
        assert "empty response" in result

    @pytest.mark.asyncio
    @patch("app.services.agent_delegate.AgentRuntime")
    @patch("app.services.agent_delegate.async_session_factory")
    async def test_delegate_truncates_long_output(self, mock_factory, mock_runtime_cls):
        """Long output is truncated to _MAX_RETURN_CHARS."""
        mock_runtime = AsyncMock()
        mock_runtime.execute.return_value = {"ok": True, "content": "x" * 10000, "steps": 1}
        mock_runtime_cls.return_value = mock_runtime

        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_factory.return_value = mock_session

        from app.services.agent_delegate import delegate_to_agent
        result = await delegate_to_agent({"role": "legal", "task": "review"})
        assert len(result) < 10000
        assert "truncated" in result

    @pytest.mark.asyncio
    @patch("app.services.agent_delegate.AgentRuntime")
    @patch("app.services.agent_delegate.async_session_factory")
    async def test_delegate_passes_context(self, mock_factory, mock_runtime_cls):
        """Context dict is forwarded to runtime.execute."""
        mock_runtime = AsyncMock()
        mock_runtime.execute.return_value = {"ok": True, "content": "Done", "steps": 0}
        mock_runtime_cls.return_value = mock_runtime

        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_factory.return_value = mock_session

        from app.services.agent_delegate import delegate_to_agent
        await delegate_to_agent({"role": "security", "task": "review", "context": {"a": 1}})
        _, call_kwargs = mock_runtime.execute.await_args
        assert call_kwargs.get("context") == {"a": 1}

    @pytest.mark.asyncio
    @patch("app.services.agent_delegate.AgentRuntime")
    @patch("app.services.agent_delegate.async_session_factory")
    async def test_delegate_clamps_max_steps(self, mock_factory, mock_runtime_cls):
        """max_steps is clamped to [1, 8]."""
        mock_runtime = AsyncMock()
        mock_runtime.execute.return_value = {"ok": True, "content": "Done", "steps": 0}
        mock_runtime_cls.return_value = mock_runtime

        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_factory.return_value = mock_session

        from app.services.agent_delegate import delegate_to_agent

        # Upper bound
        await delegate_to_agent({"role": "designer", "task": "mockup", "max_steps": 999})
        _, init_kwargs = mock_runtime_cls.call_args
        assert init_kwargs["max_steps"] <= 8

        # Lower bound
        mock_runtime_cls.reset_mock()
        mock_runtime2 = AsyncMock()
        mock_runtime2.execute.return_value = {"ok": True, "content": "Done", "steps": 0}
        mock_runtime_cls.return_value = mock_runtime2
        await delegate_to_agent({"role": "designer", "task": "mockup", "max_steps": 0})
        _, init_kwargs = mock_runtime_cls.call_args
        assert init_kwargs["max_steps"] >= 1

    def test_delegate_filters_self_from_tools(self):
        """delegate_to_agent should not be in the tools list passed to AgentRuntime."""
        from app.agents.seed import AGENT_TOOLS
        for seed_id, tools in AGENT_TOOLS.items():
            filtered = [t for t in tools if t != "delegate_to_agent"]
            assert "delegate_to_agent" not in filtered


# ── ROLE_TO_SEED_ID completeness ────────────────────────────────────────

class TestRoleMapping:

    def test_all_short_prompts_have_seed_id(self):
        """Every entry in _SHORT_PROMPTS should have a corresponding seed_id
        in ROLE_TO_SEED_ID (or be reachable via an alias)."""
        from app.services.agent_delegate import _SHORT_PROMPTS
        for seed_id in _SHORT_PROMPTS:
            roles = [r for r, s in ROLE_TO_SEED_ID.items() if s == seed_id]
            assert roles, f"{seed_id} has no role mapping in ROLE_TO_SEED_ID"

    def test_all_seed_ids_have_prompt(self):
        """Every ROLE_TO_SEED_ID value should have a short prompt."""
        from app.services.agent_delegate import _SHORT_PROMPTS
        missing = [s for s in ROLE_TO_SEED_ID.values() if s not in _SHORT_PROMPTS]
        assert not missing, f"Missing short prompts for seed IDs: {set(missing)}"
