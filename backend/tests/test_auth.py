"""Tests for authentication and authorization."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_login_success(client, db, test_user):
    res = await client.post("/api/auth/login", json={
        "email": test_user.email,
        "password": "testpass123",
    })
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["user"]["email"] == test_user.email


@pytest.mark.asyncio
async def test_login_wrong_password(client, db, test_user):
    res = await client.post("/api/auth/login", json={
        "email": test_user.email,
        "password": "wrongpassword",
    })
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_me_unauthenticated(client):
    res = await client.get("/api/auth/me")
    assert res.status_code in (401, 403)


@pytest.mark.asyncio
async def test_me_authenticated(client, db, test_user, auth_headers):
    res = await client.get("/api/auth/me", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == test_user.email
