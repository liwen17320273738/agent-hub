"""Tests for observability API endpoints."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_traces_list(client, db, auth_headers):
    """List traces endpoint should work."""
    r = await client.get("/api/observability/traces", headers=auth_headers)
    assert r.status_code == 200
    assert "traces" in r.json()


@pytest.mark.asyncio
async def test_traces_requires_auth(client):
    r = await client.get("/api/observability/traces")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_trace_not_found(client, db, auth_headers):
    r = await client.get(
        "/api/observability/traces/nonexistent", headers=auth_headers
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_approvals_list(client, db, auth_headers):
    r = await client.get("/api/observability/approvals", headers=auth_headers)
    assert r.status_code == 200
    assert "approvals" in r.json()


@pytest.mark.asyncio
async def test_audit_log(client, db, auth_headers):
    r = await client.get("/api/observability/audit-log", headers=auth_headers)
    assert r.status_code == 200
    assert "entries" in r.json()


@pytest.mark.asyncio
async def test_resolve_model(client, db, auth_headers):
    r = await client.post(
        "/api/observability/planner/resolve-model",
        json={"role": "developer", "stage_id": "development"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert "resolution" in data
    assert "model" in data["resolution"]


@pytest.mark.asyncio
async def test_estimate_cost(client, db, auth_headers):
    r = await client.post(
        "/api/observability/planner/estimate-cost",
        json={
            "stages": [
                {"id": "planning", "role": "product-manager"},
                {"id": "development", "role": "developer"},
            ]
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert "estimate" in data
