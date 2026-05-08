"""Relay gateway: customer OpenAI-compatible keys and org balance."""
from __future__ import annotations

import pytest

from app.config import settings


@pytest.mark.asyncio
async def test_relay_topup_create_key_chat_debits(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "pipeline_api_key", "", raising=False)

    top = await client.post("/api/relay/balance/topup", json={"amount_usd": 100.0}, headers=auth_headers)
    assert top.status_code == 200
    assert top.json()["relay_balance_usd"] == 100.0

    kr = await client.post("/api/relay/keys", json={"name": "e2e"}, headers=auth_headers)
    assert kr.status_code == 200
    relay_key = kr.json()["plaintext_key"]
    assert relay_key.startswith("ahrelay_")

    async def fake_chat(**kwargs):
        return {
            "content": "ok",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            "provider": "deepseek",
            "latency_ms": 1,
        }

    monkeypatch.setattr("app.services.llm_router.chat_completion", fake_chat)

    chat = await client.post(
        "/v1/chat/completions",
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "hello"}],
        },
        headers={"Authorization": f"Bearer {relay_key}"},
    )
    assert chat.status_code == 200

    bal = await client.get("/api/relay/balance", headers=auth_headers)
    assert bal.status_code == 200
    assert bal.json()["relay_balance_usd"] < 100.0


@pytest.mark.asyncio
async def test_relay_fallback_pricing_when_catalog_misses(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "pipeline_api_key", "", raising=False)
    monkeypatch.setattr(settings, "relay_fallback_usd_per_1k_total", 0.01, raising=False)

    top = await client.post("/api/relay/balance/topup", json={"amount_usd": 50.0}, headers=auth_headers)
    assert top.status_code == 200
    start_bal = top.json()["relay_balance_usd"]

    kr = await client.post("/api/relay/keys", json={}, headers=auth_headers)
    relay_key = kr.json()["plaintext_key"]

    async def fake_chat(**kwargs):
        return {
            "content": "ok",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 1000},
            "provider": "local",
            "latency_ms": 1,
        }

    monkeypatch.setattr("app.services.llm_router.chat_completion", fake_chat)

    chat = await client.post(
        "/v1/chat/completions",
        json={
            "model": "vendor/unknown-model-xyz",
            "messages": [{"role": "user", "content": "hello"}],
        },
        headers={"Authorization": f"Bearer {relay_key}"},
    )
    assert chat.status_code == 200

    bal = (await client.get("/api/relay/balance", headers=auth_headers)).json()["relay_balance_usd"]
    # 2000 tokens * 0.01/1k = 0.02 base, markup 1.0
    assert bal < start_bal
    assert abs(start_bal - bal - 0.02) < 1e-6


@pytest.mark.asyncio
async def test_relay_insufficient_balance_returns_402(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "pipeline_api_key", "", raising=False)

    kr = await client.post("/api/relay/keys", json={}, headers=auth_headers)
    assert kr.status_code == 200
    relay_key = kr.json()["plaintext_key"]

    async def fake_chat(**kwargs):
        return {
            "content": "ok",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "provider": "deepseek",
            "latency_ms": 1,
        }

    monkeypatch.setattr("app.services.llm_router.chat_completion", fake_chat)

    chat = await client.post(
        "/v1/chat/completions",
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "x"}],
        },
        headers={"Authorization": f"Bearer {relay_key}"},
    )
    assert chat.status_code == 402


@pytest.mark.asyncio
async def test_pipeline_server_key_bypasses_relay_balance(client, monkeypatch):
    monkeypatch.setattr(settings, "pipeline_api_key", "integration-server-key-32chars-minimum____", raising=False)

    async def fake_chat(**kwargs):
        return {
            "content": "pong",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "provider": "deepseek",
            "latency_ms": 1,
        }

    monkeypatch.setattr("app.services.llm_router.chat_completion", fake_chat)

    resp = await client.post(
        "/v1/chat/completions",
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "ping"}],
        },
        headers={"Authorization": "Bearer integration-server-key-32chars-minimum____"},
    )
    assert resp.status_code == 200
    assert "pong" in resp.json()["choices"][0]["message"]["content"]


@pytest.mark.asyncio
async def test_v1_models_accepts_relay_key_without_positive_balance(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "pipeline_api_key", "", raising=False)

    kr = await client.post("/api/relay/keys", json={}, headers=auth_headers)
    relay_key = kr.json()["plaintext_key"]

    resp = await client.get("/v1/models", headers={"Authorization": f"Bearer {relay_key}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("object") == "list"
    assert len(body.get("data", [])) >= 1


@pytest.mark.asyncio
async def test_relay_policy_unauthorized(client):
    res = await client.get("/api/relay/policy")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_relay_policy_returns_billing_fields(client, auth_headers):
    res = await client.get("/api/relay/policy", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert "markup_multiplier" in body
    assert "fallback_usd_per_1k_total" in body
    assert "min_balance_usd" in body
    assert isinstance(body["markup_multiplier"], (int, float))
    assert isinstance(body["fallback_usd_per_1k_total"], (int, float))
    assert isinstance(body["min_balance_usd"], (int, float))
    assert "rate_limit_per_minute" in body
    assert float(body["rate_limit_per_minute"]) > 0
