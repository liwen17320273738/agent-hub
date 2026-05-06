"""Tests for LLM per-model circuit breaker (consecutive retriable failures)."""
import pytest

from app.config import settings
from app.services.llm_router import (
    circuit_is_open,
    circuit_on_retriable_failure,
    circuit_on_success,
)


@pytest.mark.asyncio
async def test_circuit_opens_after_threshold(monkeypatch):
    monkeypatch.setattr(settings, "llm_circuit_breaker_enabled", True)
    monkeypatch.setattr(settings, "llm_circuit_failure_threshold", 2)
    monkeypatch.setattr(settings, "llm_circuit_open_seconds", 60)
    monkeypatch.setattr(settings, "llm_circuit_streak_ttl_seconds", 300)

    await circuit_on_success("deepseek", "deepseek-chat", "")
    assert await circuit_is_open("deepseek", "deepseek-chat", "") is False

    await circuit_on_retriable_failure("deepseek", "deepseek-chat", "")
    assert await circuit_is_open("deepseek", "deepseek-chat", "") is False

    await circuit_on_retriable_failure("deepseek", "deepseek-chat", "")
    assert await circuit_is_open("deepseek", "deepseek-chat", "") is True

    await circuit_on_success("deepseek", "deepseek-chat", "")
    assert await circuit_is_open("deepseek", "deepseek-chat", "") is False


@pytest.mark.asyncio
async def test_circuit_disabled_no_open(monkeypatch):
    monkeypatch.setattr(settings, "llm_circuit_breaker_enabled", False)
    monkeypatch.setattr(settings, "llm_circuit_failure_threshold", 1)

    await circuit_on_retriable_failure("openai", "gpt-4o-mini", "")
    assert await circuit_is_open("openai", "gpt-4o-mini", "") is False
