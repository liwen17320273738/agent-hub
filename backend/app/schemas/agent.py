from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel


class ToolBindingOut(BaseModel):
    name: str
    description: str
    permissions: List[str] = []


class AgentSkillOut(BaseModel):
    id: Any
    skill_id: str
    config: dict = {}
    enabled: bool = True
    model_config = {"from_attributes": True}


class AgentRuleOut(BaseModel):
    id: Any
    name: str
    description: str = ""
    rule_type: str
    content: str = ""
    priority: int = 0
    enabled: bool = True
    model_config = {"from_attributes": True}


class AgentHookOut(BaseModel):
    id: Any
    name: str
    hook_type: str
    handler: str = ""
    config: dict = {}
    enabled: bool = True
    model_config = {"from_attributes": True}


class AgentPluginOut(BaseModel):
    id: Any
    name: str
    plugin_type: str
    config: dict = {}
    version: str = "1.0.0"
    enabled: bool = True
    model_config = {"from_attributes": True}


class AgentMcpOut(BaseModel):
    id: Any
    name: str
    server_url: str = ""
    tools: list = []
    config: dict = {}
    enabled: bool = True
    model_config = {"from_attributes": True}


class AgentOut(BaseModel):
    id: str
    name: str
    title: str
    icon: str
    color: str
    description: str
    system_prompt: str
    quick_prompts: List[str]
    category: str
    pipeline_role: Optional[str] = None
    capabilities: dict = {}
    role_card: dict = {}
    preferred_model: Optional[str] = None
    max_tokens: int = 4096
    temperature: float = 0.7
    is_active: bool = True
    tools: List[ToolBindingOut] = []
    skills: List[AgentSkillOut] = []
    rules: List[AgentRuleOut] = []
    hooks: List[AgentHookOut] = []
    plugins: List[AgentPluginOut] = []
    mcps: List[AgentMcpOut] = []

    model_config = {"from_attributes": True}


class AgentCreate(BaseModel):
    id: str
    name: str
    title: str
    icon: str = "Robot"
    color: str = "#6366f1"
    description: str = ""
    system_prompt: str = ""
    quick_prompts: List[str] = []
    category: str = "support"
    pipeline_role: Optional[str] = None
    capabilities: dict = {}
    role_card: dict = {}
    preferred_model: Optional[str] = None
    max_tokens: int = 4096
    temperature: float = 0.7


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    quick_prompts: Optional[List[str]] = None
    category: Optional[str] = None
    pipeline_role: Optional[str] = None
    capabilities: Optional[dict] = None
    role_card: Optional[dict] = None
    preferred_model: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    is_active: Optional[bool] = None
