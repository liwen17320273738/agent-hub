"""Tests for authentication and authorization."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_login_success(client, db, test_user):
    res = await client.post("/api/auth/login", json={
        "email": "testuser@test.com",
        "password": "testpass123",
    })
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["user"]["email"] == "testuser@test.com"


@pytest.mark.asyncio
async def test_login_wrong_password(client, db, test_user):
    res = await client.post("/api/auth/login", json={
        "email": "testuser@test.com",
        "password": "wrongpassword",
    })
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_me_unauthenticated(client):
    res = await client.get("/api/auth/me")
    assert res.status_code in (401, 403)


@pytest.mark.asyncio
async def test_me_authenticated(client, db, auth_headers):
    res = await client.get("/api/auth/me", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "testuser@test.com"
