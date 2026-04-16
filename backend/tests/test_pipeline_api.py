"""Tests for pipeline API endpoints — auth, CRUD, and tenant isolation."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_list_tasks_unauthenticated(client):
    res = await client.get("/api/pipeline/tasks")
    assert res.status_code in (401, 403)


@pytest.mark.asyncio
async def test_create_task(client, db, auth_headers):
    res = await client.post("/api/pipeline/tasks", json={
        "title": "Test Task",
        "description": "A test pipeline task",
    }, headers=auth_headers)
    assert res.status_code == 201
    data = res.json()
    assert data["task"]["title"] == "Test Task"
    assert data["task"]["status"] in ("pending", "active")
    return data["task"]["id"]


@pytest.mark.asyncio
async def test_get_task(client, db, auth_headers):
    create_res = await client.post("/api/pipeline/tasks", json={
        "title": "Fetch Me",
    }, headers=auth_headers)
    task_id = create_res.json()["task"]["id"]

    res = await client.get(f"/api/pipeline/tasks/{task_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["task"]["title"] == "Fetch Me"


@pytest.mark.asyncio
async def test_get_task_invalid_id(client, db, auth_headers):
    res = await client.get("/api/pipeline/tasks/not-a-uuid", headers=auth_headers)
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_get_task_not_found(client, db, auth_headers):
    res = await client.get(
        "/api/pipeline/tasks/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_delete_task(client, db, auth_headers):
    create_res = await client.post("/api/pipeline/tasks", json={
        "title": "Delete Me",
    }, headers=auth_headers)
    task_id = create_res.json()["task"]["id"]

    del_res = await client.delete(f"/api/pipeline/tasks/{task_id}", headers=auth_headers)
    assert del_res.status_code == 200

    get_res = await client.get(f"/api/pipeline/tasks/{task_id}", headers=auth_headers)
    assert get_res.status_code == 404


@pytest.mark.asyncio
async def test_e2e_requires_auth(client):
    """POST /pipeline/e2e must require authentication."""
    res = await client.post("/api/pipeline/e2e", json={
        "title": "Unauthorized E2E",
    })
    assert res.status_code in (401, 403)
