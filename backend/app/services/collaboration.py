"""Agent collaboration framework: enables multi-agent workflows.

5 Core Expert Agents — 30年资深专家团队:
  👔 CEO Agent (总指挥) — 需求规划 + 评审验收
  🏗️ 架构师 Agent — 系统架构设计
  💻 开发 Agent — 全栈代码实现
  🧪 测试 Agent — 质量保障与验证
  🚀 运维 Agent — 部署上线与运维

Session state is persisted to Redis for multi-worker consistency.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ..redis_client import get_redis, cache_get, cache_set

logger = logging.getLogger(__name__)

_COLLAB_SESSION_TTL = 3600 * 24  # 24 hours


AGENT_TEAM = {
    "ceo-agent": {
        "id": "ceo-agent",
        "name": "CEO Agent（总指挥）",
        "icon": "👔",
        "expertise": "30年产品战略 + 团队管理",
        "responsibilities": ["需求分析", "PRD撰写", "项目评审", "团队协调"],
        "stages": ["planning"],
        "tier": "planning",
    },
    "designer-agent": {
        "id": "designer-agent",
        "name": "UI/UX 设计师 Agent",
        "icon": "🎨",
        "expertise": "30年设计经验，曾任 Apple、Google",
        "responsibilities": ["设计 Token", "页面布局", "组件规范", "交互流程", "无障碍"],
        "stages": ["design"],
        "tier": "execution",
    },
    "architect-agent": {
        "id": "architect-agent",
        "name": "架构师 Agent",
        "icon": "🏗️",
        "expertise": "30年系统架构设计",
        "responsibilities": ["技术选型", "系统架构", "数据模型", "API设计", "性能规划"],
        "stages": ["architecture"],
        "tier": "planning",
    },
    "developer-agent": {
        "id": "developer-agent",
        "name": "开发 Agent",
        "icon": "💻",
        "expertise": "30年全栈开发",
        "responsibilities": ["前端开发", "后端开发", "数据库实现", "API编码", "代码优化"],
        "stages": ["development"],
        "tier": "execution",
    },
    "qa-agent": {
        "id": "qa-agent",
        "name": "测试 Agent",
        "icon": "🧪",
        "expertise": "30年质量保障",
        "responsibilities": ["测试设计", "自动化测试", "安全测试", "性能测试", "回归测试"],
        "stages": ["testing"],
        "tier": "execution",
    },
    "acceptance-agent": {
        "id": "acceptance-agent",
        "name": "验收官 Agent",
        "icon": "🛂",
        "expertise": "30年项目质量管理，强证据派",
        "responsibilities": ["对照PRD验收", "证据校验", "上线前 Go/No-Go", "缺陷归类"],
        "stages": ["reviewing"],
        "tier": "planning",
    },
    "devops-agent": {
        "id": "devops-agent",
        "name": "运维 Agent",
        "icon": "🚀",
        "expertise": "30年DevOps运维",
        "responsibilities": ["CI/CD搭建", "容器化", "部署上线", "监控告警", "灾备恢复"],
        "stages": ["deployment"],
        "tier": "execution",
    },
}


class CollabMode(str, Enum):
    SERIAL = "serial"
    PARALLEL = "parallel"
    REVIEW = "review"
    FEEDBACK = "feedback"


class CollabMessage(BaseModel):
    id: str = ""
    from_agent: str
    to_agent: str
    content: str
    message_type: str = "task"
    metadata: Dict[str, Any] = {}
    created_at: str = ""

    def __init__(self, **data):
        super().__init__(**data)
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()


class CollabSession(BaseModel):
    id: str = ""
    mode: CollabMode = CollabMode.SERIAL
    agents: List[str] = []
    current_agent_index: int = 0
    messages: List[CollabMessage] = []
    status: str = "active"
    context: Dict[str, Any] = {}
    created_at: str = ""

    def __init__(self, **data):
        super().__init__(**data)
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()


PIPELINE_STAGES = [
    {"id": "planning", "label": "需求规划", "role": "product-manager", "agent": "ceo-agent"},
    {"id": "design", "label": "UI/UX 设计", "role": "designer", "agent": "designer-agent"},
    {"id": "architecture", "label": "架构设计", "role": "architect", "agent": "architect-agent"},
    {"id": "development", "label": "开发实现", "role": "developer", "agent": "developer-agent"},
    {"id": "testing", "label": "测试验证", "role": "qa-lead", "agent": "qa-agent"},
    {"id": "reviewing", "label": "审查验收", "role": "acceptance", "agent": "acceptance-agent"},
    {"id": "deployment", "label": "部署上线", "role": "devops", "agent": "devops-agent"},
]

STAGE_LABELS = {s["id"]: s["label"] for s in PIPELINE_STAGES}
STAGE_ROLES = {s["id"]: s["role"] for s in PIPELINE_STAGES}
STAGE_AGENTS = {s["id"]: s["agent"] for s in PIPELINE_STAGES}


def get_agent_for_stage(stage_id: str) -> Optional[Dict[str, Any]]:
    """Get the expert agent profile responsible for a given pipeline stage."""
    agent_id = STAGE_AGENTS.get(stage_id)
    return AGENT_TEAM.get(agent_id) if agent_id else None


def get_team_roster() -> List[Dict[str, Any]]:
    """Return the full agent team roster for display."""
    return list(AGENT_TEAM.values())


async def _save_session(session: CollabSession) -> None:
    """Persist session to Redis."""
    await cache_set(f"collab:session:{session.id}", session.model_dump(), ttl=_COLLAB_SESSION_TTL)


async def load_session(session_id: str) -> Optional[CollabSession]:
    """Load a collaboration session from Redis."""
    data = await cache_get(f"collab:session:{session_id}")
    if data is None:
        return None
    return CollabSession(**data)


async def create_serial_pipeline(task_title: str, description: str = "") -> CollabSession:
    """Create a standard serial pipeline with all stages."""
    agents = [stage["role"] for stage in PIPELINE_STAGES]
    session = CollabSession(
        mode=CollabMode.SERIAL,
        agents=agents,
        context={
            "task_title": task_title,
            "description": description,
            "stages": PIPELINE_STAGES,
        },
    )
    await _save_session(session)
    return session


async def create_parallel_session(agents: List[str], task: str) -> CollabSession:
    session = CollabSession(
        mode=CollabMode.PARALLEL,
        agents=agents,
        context={"task": task},
    )
    await _save_session(session)
    return session


def get_next_agent(session: CollabSession) -> Optional[str]:
    if session.mode == CollabMode.SERIAL:
        if session.current_agent_index < len(session.agents):
            return session.agents[session.current_agent_index]
    return None


async def advance_session(session: CollabSession, output: str) -> CollabSession:
    """Advance the session to the next stage/agent."""
    if session.mode == CollabMode.SERIAL:
        current = session.agents[session.current_agent_index] if session.current_agent_index < len(session.agents) else "unknown"
        next_idx = session.current_agent_index + 1

        if next_idx < len(session.agents):
            next_agent = session.agents[next_idx]
            msg = CollabMessage(
                from_agent=current,
                to_agent=next_agent,
                content=output,
                message_type="task",
            )
            session.messages.append(msg)
            session.current_agent_index = next_idx
        else:
            session.status = "completed"

    await _save_session(session)
    return session


async def send_feedback(session: CollabSession, from_agent: str, to_agent: str, feedback: str) -> CollabSession:
    """Send feedback from downstream agent back to upstream."""
    msg = CollabMessage(
        from_agent=from_agent,
        to_agent=to_agent,
        content=feedback,
        message_type="feedback",
    )
    session.messages.append(msg)

    target_idx = next((i for i, a in enumerate(session.agents) if a == to_agent), None)
    if target_idx is not None:
        session.current_agent_index = target_idx

    await _save_session(session)
    return session
