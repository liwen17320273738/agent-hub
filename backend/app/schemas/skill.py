from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class SkillOut(BaseModel):
    id: str
    name: str
    category: str
    description: str = ""
    version: str = "1.0.0"
    author: str = "system"
    prompt_template: str = ""
    config: dict = {}
    tags: List[str] = []
    rules: list = []
    hooks: list = []
    plugins: list = []
    mcp_tools: list = []
    trigger_stages: List[str] = []
    completion_criteria: List[str] = []
    allowed_tools: List[str] = []
    execution_mode: str = "inline"
    enabled: bool = True
    is_builtin: bool = False
    install_count: int = 0

    model_config = {"from_attributes": True}


class SkillCreate(BaseModel):
    id: str
    name: str
    category: str
    description: str = ""
    version: str = "1.0.0"
    prompt_template: str = ""
    config: dict = {}
    tags: List[str] = []
    rules: list = []
    hooks: list = []
    plugins: list = []
    mcp_tools: list = []
    trigger_stages: List[str] = []
    completion_criteria: List[str] = []
    allowed_tools: List[str] = []
    execution_mode: str = "inline"


class SkillUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    prompt_template: Optional[str] = None
    config: Optional[dict] = None
    tags: Optional[List[str]] = None
    rules: Optional[list] = None
    hooks: Optional[list] = None
    plugins: Optional[list] = None
    mcp_tools: Optional[list] = None
    trigger_stages: Optional[List[str]] = None
    completion_criteria: Optional[List[str]] = None
    allowed_tools: Optional[List[str]] = None
    execution_mode: Optional[str] = None
    enabled: Optional[bool] = None
