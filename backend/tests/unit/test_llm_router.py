"""Tests for multi-provider LLM router."""
from app.services.llm_router import (
    infer_provider,
    _extract_system_and_messages,
    _build_anthropic_body,
    _build_gemini_body,
    _parse_anthropic_response,
    _parse_gemini_response,
)


def test_infer_provider_from_model():
    assert infer_provider("claude-3-opus") == "anthropic"
    assert infer_provider("gemini-pro") == "google"
    assert infer_provider("deepseek-chat") == "deepseek"
    assert infer_provider("gpt-4o") == "openai"
    assert infer_provider("glm-4") == "zhipu"
    assert infer_provider("qwen-turbo") == "qwen"


def test_infer_provider_from_url():
    assert infer_provider("custom", "https://api.anthropic.com/v1/messages") == "anthropic"
    assert infer_provider("custom", "https://generativelanguage.googleapis.com") == "google"
    assert infer_provider("custom", "https://api.deepseek.com/v1") == "deepseek"


def test_extract_system_and_messages():
    msgs = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!"},
        {"role": "user", "content": "How?"},
    ]
    system, convo = _extract_system_and_messages(msgs)
    assert system == "You are helpful."
    assert len(convo) == 3
    assert convo[0]["role"] == "user"


def test_build_anthropic_body():
    msgs = [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "Test"},
    ]
    body = _build_anthropic_body("claude-3", msgs, 0.5, 1000)
    assert body["model"] == "claude-3"
    assert body["system"] == "Be concise."
    assert len(body["messages"]) == 1


def test_build_gemini_body():
    msgs = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
    ]
    body = _build_gemini_body(msgs, 0.7, 2048)
    assert body["contents"][1]["role"] == "model"
    assert body["generationConfig"]["maxOutputTokens"] == 2048


def test_parse_anthropic_response():
    data = {
        "content": [{"type": "text", "text": "Hello!"}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    content, usage = _parse_anthropic_response(data)
    assert content == "Hello!"
    assert usage["total_tokens"] == 15


def test_parse_gemini_response():
    data = {
        "candidates": [{"content": {"parts": [{"text": "World"}]}}],
        "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 3, "totalTokenCount": 11},
    }
    content, usage = _parse_gemini_response(data)
    assert content == "World"
    assert usage["total_tokens"] == 11
