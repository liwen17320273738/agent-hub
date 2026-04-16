"""Tests for gateway endpoints — verify auth enforcement."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_openclaw_requires_api_key(client):
    """OpenClaw intake must reject when no PIPELINE_API_KEY is configured."""
    res = await client.post("/api/gateway/openclaw/intake", json={
        "title": "Test intake",
    })
    assert res.status_code in (403, 503)


@pytest.mark.asyncio
async def test_feishu_requires_verification_token(client):
    """Feishu webhook must reject when verification_token is not configured."""
    res = await client.post("/api/gateway/feishu/webhook", json={
        "type": "event_callback",
        "event": {"message": {"content": '{"text": "hello"}'}},
    })
    assert res.status_code in (403, 503)


@pytest.mark.asyncio
async def test_qq_without_auth_rejected(client):
    """QQ webhook without auth header should be rejected when PIPELINE_API_KEY is set."""
    import os
    old = os.environ.get("PIPELINE_API_KEY", "")
    os.environ["PIPELINE_API_KEY"] = "test-secret"
    try:
        res = await client.post("/api/gateway/qq/webhook", json={
            "content": "test",
        })
        assert res.status_code == 403
    finally:
        if old:
            os.environ["PIPELINE_API_KEY"] = old
        else:
            os.environ.pop("PIPELINE_API_KEY", None)
