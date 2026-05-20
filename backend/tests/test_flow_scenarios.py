"""Multi-step flow tests — chained API journeys without real LLM execution.

Each case simulates a slice of the product flow (需求 → 任务 → 资产/协作/可观测).
Works with ``AGENTHUB_TEST_MINIMAL_LIFESPAN=1`` (CI): stubs an agent row when the
DB seed skipped ``AgentDefinition`` rows.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.agent import AgentDefinition


async def _ensure_any_agent_id(client, db, auth_headers: dict) -> str:
    r = await client.get("/api/agents/", headers=auth_headers)
    assert r.status_code == 200, r.text
    agents = r.json()
    if agents:
        return str(agents[0]["id"])
    aid = "flow-stub-agent"
    db.add(
        AgentDefinition(
            id=aid,
            name="Flow Stub Agent",
            title="Stub",
            category="support",
        )
    )
    await db.flush()
    return aid


# ---------------------------------------------------------------------------
# 1. 需求 → 任务 → 工件骨架 + 写入 brief
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flow_requirement_to_artifact_brief(client, db, auth_headers):
    t = await client.post(
        "/api/pipeline/tasks",
        json={
            "title": "Flow: one-liner to brief",
            "description": "验收：工件 API 可写",
        },
        headers=auth_headers,
    )
    assert t.status_code == 201, t.text
    task_id = t.json()["task"]["id"]

    types = await client.get("/api/tasks/artifact-types")
    assert types.status_code == 200
    body = types.json()
    assert isinstance(body, list) and len(body) >= 8

    art = await client.post(
        f"/api/tasks/{task_id}/artifacts/brief",
        json={"title": "Brief v1", "content": "## 范围\n流程测试\n"},
        headers=auth_headers,
    )
    assert art.status_code == 201, art.text

    lst = await client.get(f"/api/tasks/{task_id}/artifacts", headers=auth_headers)
    assert lst.status_code == 200
    items = lst.json().get("artifacts", [])
    brief = next((x for x in items if x.get("type_key") == "brief"), None)
    assert brief and brief.get("has_content") is True


# ---------------------------------------------------------------------------
# 2. 阶段产出 + 质量闸 / checkpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flow_stage_output_and_quality_gate(client, db, auth_headers):
    t = await client.post(
        "/api/pipeline/tasks",
        json={"title": "Flow: stage + QG"},
        headers=auth_headers,
    )
    task_id = t.json()["task"]["id"]
    so = await client.post(
        f"/api/pipeline/tasks/{task_id}/stage-output",
        json={"stage_id": "design", "content": "## UI\n流程测试产出\n"},
        headers=auth_headers,
    )
    assert so.status_code in (200, 201), so.text

    qg = await client.get(
        f"/api/pipeline/tasks/{task_id}/quality-gate-config",
        headers=auth_headers,
    )
    cp = await client.get(
        f"/api/pipeline/tasks/{task_id}/checkpoint",
        headers=auth_headers,
    )
    assert qg.status_code in (200, 404)
    assert cp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# 3. 工作流：保存 → 读取 → 删除（不执行 run，避免真实 LLM）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flow_workflow_save_fetch_delete(client, db, auth_headers):
    doc = {
        "name": "flow-wf",
        "nodes": [
            {
                "id": "n1",
                "type": "llm",
                "data": {"label": "Ping", "prompt": "hello from flow test"},
            }
        ],
        "edges": [],
    }
    c = await client.post(
        "/api/workflows/",
        json={"name": "Flow Test WF", "description": "", "doc": doc},
        headers=auth_headers,
    )
    assert c.status_code == 201, c.text
    wf_id = c.json()["workflow"]["id"]

    g = await client.get(f"/api/workflows/{wf_id}", headers=auth_headers)
    assert g.status_code == 200
    assert g.json()["workflow"]["id"] == wf_id

    d = await client.delete(f"/api/workflows/{wf_id}", headers=auth_headers)
    assert d.status_code == 204


# ---------------------------------------------------------------------------
# 4. 工作区：列表 → 创建 → 再列表
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flow_workspace_list_create(client, db, auth_headers):
    before = await client.get("/api/workspaces/", headers=auth_headers)
    assert before.status_code == 200
    n0 = len(before.json())

    name = f"Flow WS {uuid.uuid4().hex[:8]}"
    cr = await client.post(
        "/api/workspaces/",
        json={"name": name, "description": "flow"},
        headers=auth_headers,
    )
    assert cr.status_code == 201, cr.text
    ws_id = cr.json()["id"]

    after = await client.get("/api/workspaces/", headers=auth_headers)
    assert after.status_code == 200
    assert len(after.json()) >= n0 + 1
    assert any(w.get("id") == ws_id for w in after.json())


# ---------------------------------------------------------------------------
# 5. 技能列表 + 市场目录
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flow_skills_and_marketplace_catalog(client, db, auth_headers):
    sk = await client.get("/api/skills/", headers=auth_headers)
    assert sk.status_code == 200
    mc = await client.get("/api/skills/marketplace/catalog", headers=auth_headers)
    assert mc.status_code == 200
    data = mc.json()
    assert "catalog" in data and data.get("total", 0) >= 0


# ---------------------------------------------------------------------------
# 6. 模型 live + 用量统计（不要求外网密钥；可为空）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flow_models_live_and_usage(client, db, auth_headers):
    live = await client.get("/api/models/live", headers=auth_headers)
    assert live.status_code == 200
    assert "providers" in live.json()
    usage = await client.get("/api/models/usage", headers=auth_headers)
    assert usage.status_code == 200


# ---------------------------------------------------------------------------
# 7. 对话：确保有 agent → 创建 → 列表
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flow_conversation_create_list(client, db, auth_headers):
    aid = await _ensure_any_agent_id(client, db, auth_headers)
    conv = await client.post(
        "/api/conversations/",
        json={"agent_id": aid, "title": "Flow convo"},
        headers=auth_headers,
    )
    assert conv.status_code == 201, conv.text
    lst = await client.get("/api/conversations/", headers=auth_headers)
    assert lst.status_code == 200
    assert len(lst.json()) >= 1


# ---------------------------------------------------------------------------
# 8. 凭据列表 + 调度器状态
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flow_credentials_and_scheduler(client, db, auth_headers):
    creds = await client.get("/api/credentials/", headers=auth_headers)
    assert creds.status_code == 200
    assert isinstance(creds.json(), list)

    sched = await client.get("/api/scheduler/status", headers=auth_headers)
    assert sched.status_code == 200
    st = sched.json()
    assert "running" in st and "queued" in st and "lifetime" in st


# ---------------------------------------------------------------------------
# 9. Sandbox 策略 + 规则表
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flow_sandbox_policy_and_rules(client, db, auth_headers):
    pol = await client.get("/api/sandbox/policy", headers=auth_headers)
    assert pol.status_code == 200
    rules = await client.get("/api/sandbox/rules", headers=auth_headers)
    assert rules.status_code == 200


# ---------------------------------------------------------------------------
# 10. Agent runtime 元数据
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flow_agent_runtime_endpoints(client, db, auth_headers):
    roles = await client.get("/api/agents/runtime/roles", headers=auth_headers)
    assert roles.status_code == 200
    tools = await client.get("/api/agents/runtime/tools", headers=auth_headers)
    assert tools.status_code == 200
