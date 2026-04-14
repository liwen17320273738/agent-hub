from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Boolean, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from ..compat import GUID, JsonDict, utcnow_default


class AgentDefinition(Base):
    """Dynamic agent definitions stored in DB, not hardcoded."""
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(100))
    icon: Mapped[str] = mapped_column(String(50), default="Robot")
    color: Mapped[str] = mapped_column(String(20), default="#6366f1")
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    quick_prompts: Mapped[list] = mapped_column(JsonDict(), default=list)

    category: Mapped[str] = mapped_column(String(20), default="support")  # core / support / pipeline
    pipeline_role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Capabilities metadata
    capabilities: Mapped[dict] = mapped_column(JsonDict(), default=dict)
    # e.g. {"can_code": true, "can_design": false, "languages": ["python", "typescript"]}

    preferred_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    temperature: Mapped[float] = mapped_column(default=0.7)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())
    updated_at: Mapped[datetime] = mapped_column(server_default=utcnow_default(), onupdate=datetime.utcnow)

    skills: Mapped[list[AgentSkill]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    rules: Mapped[list[AgentRule]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    hooks: Mapped[list[AgentHook]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    plugins: Mapped[list[AgentPlugin]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    mcps: Mapped[list[AgentMcp]] = relationship(back_populates="agent", cascade="all, delete-orphan")


class AgentSkill(Base):
    __tablename__ = "agent_skills"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(100), ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[str] = mapped_column(String(100), ForeignKey("skills.id", ondelete="CASCADE"))
    config: Mapped[dict] = mapped_column(JsonDict(), default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    agent: Mapped[AgentDefinition] = relationship(back_populates="skills")


class AgentRule(Base):
    __tablename__ = "agent_rules"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(100), ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    rule_type: Mapped[str] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    agent: Mapped[AgentDefinition] = relationship(back_populates="rules")


class AgentHook(Base):
    __tablename__ = "agent_hooks"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(100), ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    hook_type: Mapped[str] = mapped_column(String(50))
    handler: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict] = mapped_column(JsonDict(), default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    agent: Mapped[AgentDefinition] = relationship(back_populates="hooks")


class AgentPlugin(Base):
    __tablename__ = "agent_plugins"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(100), ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    plugin_type: Mapped[str] = mapped_column(String(50))
    config: Mapped[dict] = mapped_column(JsonDict(), default=dict)
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    agent: Mapped[AgentDefinition] = relationship(back_populates="plugins")


class AgentMcp(Base):
    __tablename__ = "agent_mcps"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(100), ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    server_url: Mapped[str] = mapped_column(String(500), default="")
    tools: Mapped[list] = mapped_column(JsonDict(), default=list)
    config: Mapped[dict] = mapped_column(JsonDict(), default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    agent: Mapped[AgentDefinition] = relationship(back_populates="mcps")
