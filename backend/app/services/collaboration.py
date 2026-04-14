"""Agent collaboration framework: enables multi-agent workflows.

Supports:
- Serial pipeline: agents process sequentially (requirement → PRD → design → build → test → deploy)
- Parallel fan-out: multiple agents process sub-tasks concurrently
- Review chain: critical checkpoints require specific role approval
- Feedback loop: downstream agents can send issues back upstream
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


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
    message_type: str = "task"  # task / review / feedback / approval / rejection
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
    status: str = "active"  # active / paused / completed / failed
    context: Dict[str, Any] = {}
    created_at: str = ""

    def __init__(self, **data):
        super().__init__(**data)
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()


PIPELINE_STAGES = [
    {"id": "planning", "label": "需求规划", "role": "product-manager"},
    {"id": "architecture", "label": "架构设计", "role": "architect"},
    {"id": "development", "label": "开发实现", "role": "developer"},
    {"id": "testing", "label": "测试验证", "role": "qa-lead"},
    {"id": "reviewing", "label": "审查验收", "role": "orchestrator"},
    {"id": "deployment", "label": "部署上线", "role": "devops"},
]

STAGE_LABELS = {s["id"]: s["label"] for s in PIPELINE_STAGES}
STAGE_ROLES = {s["id"]: s["role"] for s in PIPELINE_STAGES}


def create_serial_pipeline(task_title: str, description: str = "") -> CollabSession:
    """Create a standard serial pipeline with all stages."""
    agents = [stage["role"] for stage in PIPELINE_STAGES]
    return CollabSession(
        mode=CollabMode.SERIAL,
        agents=agents,
        context={
            "task_title": task_title,
            "description": description,
            "stages": PIPELINE_STAGES,
        },
    )


def create_parallel_session(agents: List[str], task: str) -> CollabSession:
    """Create a parallel session where multiple agents work on sub-tasks."""
    return CollabSession(
        mode=CollabMode.PARALLEL,
        agents=agents,
        context={"task": task},
    )


def get_next_agent(session: CollabSession) -> Optional[str]:
    if session.mode == CollabMode.SERIAL:
        if session.current_agent_index < len(session.agents):
            return session.agents[session.current_agent_index]
    return None


def advance_session(session: CollabSession, output: str) -> CollabSession:
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

    return session


def send_feedback(session: CollabSession, from_agent: str, to_agent: str, feedback: str) -> CollabSession:
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

    return session
