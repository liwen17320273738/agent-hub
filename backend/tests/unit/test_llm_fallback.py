"""Unit tests for the multi-provider fallback wrapper.

These tests stub the underlying ``chat_completion`` so they don't make any
real HTTP calls — we only care about the *routing* logic:

* retriable failure detection (status codes + error substrings),
* falling through to the next provider when keys are configured,
* short-circuit on non-retriable errors (so a 401 doesn't burn the chain),
* on_fallback callback fires with the right payload,
* the returned dict carries `tried_providers` + `fell_back`.
"""
from __future__ import annotations

import pytest

from app.services import llm_router
from app.services.llm_router import (
    _is_retriable_failure,
    chat_completion_with_fallback,
)


# ── Retriable detection ─────────────────────────────────────────────

@pytest.mark.parametrize("payload, expected", [
    ({"status": 429, "error": "rate limit exceeded"}, True),
    ({"status": 402, "error": "Insufficient Balance"}, True),
    ({"status": 503, "error": "service unavailable"}, True),
    ({"status": 500, "error": "internal server error"}, True),
    ({"status": 504, "error": "上游请求超时"}, True),
    # Zhipu's 1302 comes back as 200 with an error body — must still trip.
    ({"status": 200, "error": '{"code":"1302","message":"您的账户已达到速率限制"}'}, True),
    # Non-retriable: 401/403/400 are config bugs, not transient.
    ({"status": 401, "error": "invalid api key"}, False),
    ({"status": 403, "error": "forbidden"}, False),
    ({"status": 400, "error": "bad request: missing field"}, False),
    # Healthy success — never retriable.
    ({"status": 200, "content": "hello"}, False),
])
def test_is_retriable_failure(payload, expected):
    assert _is_retriable_failure(payload) is expected


# ── Fallback orchestration ──────────────────────────────────────────

class _Stub:
    """Captures call args + returns scripted responses for chat_completion."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


@pytest.fixture
def patch_keys(monkeypatch):
    """Pretend deepseek + openai + zhipu have keys configured."""
    def fake_get_provider_keys(self):
        return {"deepseek": "sk-d", "openai": "sk-o", "zhipu": "sk-z"}
    from app.config import Settings
    monkeypatch.setattr(Settings, "get_provider_keys", fake_get_provider_keys)


@pytest.fixture
def no_same_provider_retry(monkeypatch):
    """``chat_completion_with_fallback`` uses ``chat_completion_with_retry``, which
    can call the stub multiple times on rate limits. These unit tests only model
    provider *chain* behaviour, so collapse retry to a single ``chat_completion``."""

    async def _once(**kwargs):
        return await llm_router.chat_completion(**kwargs)

    monkeypatch.setattr(llm_router, "chat_completion_with_retry", _once)


@pytest.mark.asyncio
async def test_fallback_skips_to_deepseek_on_zhipu_rate_limit(
    monkeypatch, patch_keys, no_same_provider_retry,
):
    stub = _Stub([
        # Primary (zhipu): rate-limited
        {"status": 200, "error": '{"code":"1302","message":"您的账户已达到速率限制"}'},
        # Fallback (deepseek): success
        {"status": 200, "content": "hello from deepseek", "model": "deepseek-chat",
         "provider": "deepseek", "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
    ])
    monkeypatch.setattr(llm_router, "chat_completion", stub)

    fallback_payloads = []
    async def on_fb(payload):
        fallback_payloads.append(payload)

    result = await chat_completion_with_fallback(
        model="glm-4-flash",
        messages=[{"role": "user", "content": "hi"}],
        on_fallback=on_fb,
    )

    assert result["content"] == "hello from deepseek"
    assert result["fell_back"] is True
    assert len(result["tried_providers"]) == 2
    assert result["tried_providers"][0]["provider"] == "zhipu"
    assert result["tried_providers"][0]["ok"] is False
    assert result["tried_providers"][1]["provider"] == "deepseek"
    assert result["tried_providers"][1]["ok"] is True

    # Callback should fire exactly once (one rotation: zhipu → deepseek).
    assert len(fallback_payloads) == 1
    assert fallback_payloads[0]["from_provider"] == "zhipu"
    assert fallback_payloads[0]["to_provider"] == "deepseek"
    assert "1302" in fallback_payloads[0]["reason"]


@pytest.mark.asyncio
async def test_fallback_short_circuits_on_401(monkeypatch, patch_keys):
    """401 is a config error — must NOT fall back (would burn other keys
    on the same wrong-config call)."""
    stub = _Stub([
        {"status": 401, "error": "invalid api key"},
    ])
    monkeypatch.setattr(llm_router, "chat_completion", stub)

    result = await chat_completion_with_fallback(
        model="glm-4-flash",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert result.get("error")
    assert result["fell_back"] is False
    assert len(result["tried_providers"]) == 1  # only the primary tried
    assert len(stub.calls) == 1


@pytest.mark.asyncio
async def test_fallback_returns_last_error_when_all_fail(
    monkeypatch, patch_keys, no_same_provider_retry,
):
    stub = _Stub([
        {"status": 429, "error": "rate limit"},                        # zhipu
        {"status": 503, "error": "service unavailable"},               # deepseek
        {"status": 502, "error": "bad gateway"},                       # openai
    ])
    monkeypatch.setattr(llm_router, "chat_completion", stub)

    result = await chat_completion_with_fallback(
        model="glm-4-flash",
        messages=[{"role": "user", "content": "hi"}],
        max_attempts=3,
    )

    assert result.get("error")
    assert result["fell_back"] is False  # no successful fallback
    assert len(result["tried_providers"]) == 3
    assert all(t["ok"] is False for t in result["tried_providers"])


@pytest.mark.asyncio
async def test_fallback_skips_providers_without_keys(monkeypatch, no_same_provider_retry):
    """Only deepseek has a key → primary zhipu fails → only one fallback tried."""
    def only_deepseek(self):
        return {"deepseek": "sk-d"}
    from app.config import Settings
    monkeypatch.setattr(Settings, "get_provider_keys", only_deepseek)

    stub = _Stub([
        {"status": 429, "error": "rate limit"},                    # zhipu primary
        {"status": 200, "content": "ok", "model": "deepseek-chat"}, # deepseek
    ])
    monkeypatch.setattr(llm_router, "chat_completion", stub)

    result = await chat_completion_with_fallback(
        model="glm-4-flash",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert result["content"] == "ok"
    assert result["fell_back"] is True
    providers_tried = [t["provider"] for t in result["tried_providers"]]
    assert providers_tried == ["zhipu", "deepseek"]


@pytest.mark.asyncio
async def test_fallback_treats_tool_calls_without_text_as_success(
    monkeypatch, patch_keys, no_same_provider_retry,
):
    """GLM and others often return assistant turns with tool_calls and empty content."""
    stub = _Stub([
        {
            "status": 200,
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "function": {"name": "noop", "arguments": "{}"},
            }],
            "model": "glm-4.5",
            "provider": "zhipu",
        },
    ])
    monkeypatch.setattr(llm_router, "chat_completion", stub)

    result = await chat_completion_with_fallback(
        model="glm-4.5",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "noop", "description": "t", "parameters": {"type": "object"}}],
    )

    assert not result.get("error")
    assert result.get("tool_calls")
    assert result["fell_back"] is False
    assert len(result["tried_providers"]) == 1
    assert result["tried_providers"][0]["ok"] is True
