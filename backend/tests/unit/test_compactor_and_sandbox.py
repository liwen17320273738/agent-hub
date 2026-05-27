"""Tests for context_compactor and sandbox_auto_docker features."""
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

# ── Context Compactor Tests ──────────────────────────────────────────

from app.services.context_compactor import (
    estimate_message_tokens,
    get_model_context_size,
    should_compact,
    _split_messages,
    compact_messages,
    _simple_truncation_summary,
    _COMPACT_THRESHOLD_RATIO,
)


class TestEstimateMessageTokens:
    def test_empty_messages(self):
        assert estimate_message_tokens([]) >= 1  # max(1, 0)

    def test_simple_text(self):
        msgs = [{"role": "user", "content": "a" * 400}]
        # 400 chars / 4 = 100 tokens
        assert estimate_message_tokens(msgs) == 100

    def test_multimodal_content(self):
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "b" * 800},
            {"type": "image_url", "image_url": {"url": "http://example.com"}},
        ]}]
        # 800 chars / 4 = 200 tokens (image_url not counted as text)
        assert estimate_message_tokens(msgs) == 200

    def test_tool_calls_counted(self):
        msgs = [{"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "bash", "arguments": '{"command": "ls"}'}},
        ]}]
        tokens = estimate_message_tokens(msgs)
        assert tokens > 0  # arguments string contributes


class TestGetModelContextSize:
    def test_known_model(self):
        assert get_model_context_size("gpt-4o") == 128_000

    def test_known_model_case_insensitive(self):
        assert get_model_context_size("DeepSeek-Chat") == 128_000

    def test_unknown_model_returns_default(self):
        assert get_model_context_size("some-unknown-model") == 128_000

    def test_claude_models(self):
        assert get_model_context_size("claude-3-5-sonnet") == 200_000


class TestShouldCompact:
    def test_small_messages_no_compact(self):
        msgs = [{"role": "user", "content": "hello"}]
        assert should_compact(msgs, "gpt-4o") is False

    def test_large_messages_trigger_compact(self):
        # Create messages that exceed 75% of 128k = 96k tokens ≈ 384k chars
        big_content = "x" * 400_000  # 100k tokens
        msgs = [{"role": "user", "content": big_content}]
        assert should_compact(msgs, "gpt-4o") is True


class TestSplitMessages:
    def test_empty(self):
        sys, compact, recent = _split_messages([])
        assert sys == [] and compact == [] and recent == []

    def test_system_only(self):
        msgs = [{"role": "system", "content": "You are helpful"}]
        sys, compact, recent = _split_messages(msgs)
        assert len(sys) == 1
        assert compact == []
        assert recent == []

    def test_few_messages(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        sys, compact, recent = _split_messages(msgs, min_recent=4)
        # 2 rest messages <= 4 min_recent, so nothing compactable
        assert len(sys) == 1
        assert compact == []
        assert len(recent) == 2

    def test_many_messages(self):
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(20):
            msgs.append({"role": "user", "content": f"msg {i}"})
        sys, compact, recent = _split_messages(msgs, min_recent=4)
        assert len(sys) == 1
        assert len(compact) == 16  # 20 - 4
        assert len(recent) == 4


class TestSimpleTruncationSummary:
    def test_basic(self):
        msgs = [
            {"role": "user", "content": "Hello there"},
            {"role": "assistant", "content": "Hi! How can I help?"},
        ]
        summary = _simple_truncation_summary(msgs)
        assert "[user]" in summary
        assert "[assistant]" in summary
        assert "Hello there" in summary


class TestCompactMessages:
    @pytest.mark.asyncio
    async def test_no_compact_needed(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        result = await compact_messages(msgs, "gpt-4o", min_recent=4)
        # Nothing to compact, returns original
        assert result is msgs

    @pytest.mark.asyncio
    async def test_compact_with_mock_llm(self):
        # Create enough messages to trigger compaction
        msgs = [{"role": "system", "content": "sys prompt"}]
        for i in range(10):
            msgs.append({"role": "user", "content": f"message {i} " + "x" * 10000})
            msgs.append({"role": "assistant", "content": f"response {i}"})

        with patch("app.services.context_compactor.chat_completion_with_fallback",
                   new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {
                "content": "## Summary\n- Discussed items 0-5\n- Key decision: use Python",
                "ok": True,
            }

            with patch("app.services.context_compactor.should_compact", return_value=True):
                result = await compact_messages(msgs, "gpt-4o", min_recent=4)

                # Should have: system + compacted summary + recent
                assert result[0]["role"] == "system"
                assert "auto-compacted" in result[1]["content"]
                # Recent messages preserved
                assert len(result) < len(msgs)


# ── Sandbox Auto Docker Tests ──────────────────────────────────────────

class TestSandboxAutoDocker:
    def test_config_default(self):
        from app.config import Settings
        s = Settings()
        # sandbox_auto_docker defaults to True
        assert s.sandbox_auto_docker is True
        # sandbox_use_docker defaults to False
        assert s.sandbox_use_docker is False

    @pytest.mark.asyncio
    async def test_auto_docker_enabled(self):
        from app.services.tools.bash_tool import bash_execute
        from app.config import Settings

        settings = Settings(sandbox_auto_docker=True, sandbox_use_docker=False)

        with patch("app.services.tools.bash_tool.settings", settings):
            with patch("app.services.tools.bash_tool.is_docker_available_async",
                       new_callable=AsyncMock, return_value=True):
                with patch("app.services.tools.bash_tool.docker_exec",
                           new_callable=AsyncMock) as mock_docker:
                    mock_docker.return_value = {
                        "ok": True, "stdout": "hello", "stderr": "",
                        "exit_code": 0, "engine": "docker",
                    }
                    with patch("app.services.tools.bash_tool.get_sandbox_root",
                               return_value="/tmp/sandbox"):
                        result = await bash_execute({"command": "echo hello"})
                        # Should have called docker_exec (auto-enabled)
                        mock_docker.assert_called_once()
                        assert "[engine: docker]" in result


# ── Agent Runtime workspace_dir injection Tests ──────────────────────────

class TestWorkspaceDirInjection:
    @pytest.mark.asyncio
    async def test_bash_gets_workspace_dir(self):
        from app.services.agent_runtime import AgentRuntime

        runtime = AgentRuntime(
            agent_id="test-agent",
            system_prompt="test",
            tools=["bash"],
            task_id="test-task-123",
        )

        with patch("app.services.agent_runtime.find_task_root",
                   return_value="/tmp/workspace/TASK-test-task-123-proj"):
            with patch("app.services.agent_runtime.execute_tool",
                       new_callable=AsyncMock, return_value="ok") as mock_exec:
                await runtime._execute_tool_call("bash", {"command": "ls"})

                # Check that workspace_dir was injected
                call_args = mock_exec.call_args
                params = call_args[0][1]  # second positional arg
                assert params.get("workspace_dir") == "/tmp/workspace/TASK-test-task-123-proj"

    @pytest.mark.asyncio
    async def test_non_bash_no_workspace_dir(self):
        from app.services.agent_runtime import AgentRuntime

        runtime = AgentRuntime(
            agent_id="test-agent",
            system_prompt="test",
            tools=["file_read"],
            task_id="test-task-123",
        )

        with patch("app.services.agent_runtime.execute_tool",
                   new_callable=AsyncMock, return_value="ok") as mock_exec:
            await runtime._execute_tool_call("file_read", {"path": "/tmp/test.txt"})

            call_args = mock_exec.call_args
            params = call_args[0][1]
            # file_read should NOT get workspace_dir injected
            assert "workspace_dir" not in params
