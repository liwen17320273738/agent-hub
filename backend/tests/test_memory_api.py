"""Tests for the memory API endpoints."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_memory_search_requires_auth(client):
    """Memory search should require authentication."""
    r = await client.get("/api/memory/search?q=test")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_memory_search(client, db, auth_headers):
    """Memory search should return results."""
    r = await client.get("/api/memory/search?q=test+query", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "results" in data
    assert "count" in data


@pytest.mark.asyncio
async def test_memory_patterns(client, db, auth_headers):
    """List patterns endpoint should work."""
    r = await client.get("/api/memory/patterns", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "patterns" in data


@pytest.mark.asyncio
async def test_memory_stats(client, db, auth_headers):
    """Memory stats endpoint should return counts."""
    r = await client.get("/api/memory/stats", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "totalMemories" in data
    assert "totalPatterns" in data
    assert "avgQualityScore" in data


@pytest.mark.asyncio
async def test_working_memory_crud(client, db, auth_headers, sample_task_id):
    """Test working memory set/get/delete cycle."""
    # Set
    r = await client.post(
        f"/api/memory/working/{sample_task_id}",
        json={"key": "test_key", "value": "test_value"},
        headers=auth_headers,
    )
    assert r.status_code == 200

    # Get
    r = await client.get(
        f"/api/memory/working/{sample_task_id}", headers=auth_headers
    )
    assert r.status_code == 200

    # Delete
    r = await client.delete(
        f"/api/memory/working/{sample_task_id}", headers=auth_headers
    )
    assert r.status_code == 200
