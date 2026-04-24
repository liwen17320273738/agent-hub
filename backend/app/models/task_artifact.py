"""
TaskArtifact + ArtifactTypeRegistry — issuse21 Phase 2.

TaskArtifact is the v2 artifact model with versioning, status tracking,
and type registry FK. It coexists with the legacy PipelineArtifact during
the migration period.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..compat import GUID, JsonDict, utcnow_default


class ArtifactTypeRegistry(Base):
    __tablename__ = "artifact_type_registry"

    type_key: Mapped[str] = mapped_column(String(50), primary_key=True)
    category: Mapped[str] = mapped_column(String(50), default="document")
    display_name: Mapped[str] = mapped_column(String(100))
    icon: Mapped[str] = mapped_column(String(20), default="📄")
    tab_group: Mapped[str] = mapped_column(String(50), default="docs")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_builtin: Mapped[bool] = mapped_column(default=True)


BUILTIN_ARTIFACT_TYPES = [
    {"type_key": "brief",             "category": "document", "display_name": "需求简报",    "icon": "📋", "tab_group": "requirements", "sort_order": 0},
    {"type_key": "prd",               "category": "document", "display_name": "PRD",         "icon": "📝", "tab_group": "requirements", "sort_order": 1},
    {"type_key": "ui_spec",           "category": "document", "display_name": "UI 规格",     "icon": "🎨", "tab_group": "design",       "sort_order": 2},
    {"type_key": "architecture",      "category": "document", "display_name": "技术方案",    "icon": "🏗️", "tab_group": "technical",    "sort_order": 3},
    {"type_key": "implementation",    "category": "document", "display_name": "实现说明",    "icon": "💻", "tab_group": "technical",    "sort_order": 4},
    {"type_key": "test_report",       "category": "document", "display_name": "测试报告",    "icon": "🧪", "tab_group": "quality",      "sort_order": 5},
    {"type_key": "acceptance",        "category": "document", "display_name": "验收记录",    "icon": "✅", "tab_group": "delivery",     "sort_order": 6},
    {"type_key": "ops_runbook",       "category": "document", "display_name": "运维手册",    "icon": "🔧", "tab_group": "delivery",     "sort_order": 7},
    {"type_key": "code_link",         "category": "code",     "display_name": "代码工件",    "icon": "📦", "tab_group": "code",         "sort_order": 8},
    {"type_key": "screenshot",        "category": "media",    "display_name": "截图",        "icon": "📸", "tab_group": "design",       "sort_order": 9},
    {"type_key": "attachment",        "category": "file",     "display_name": "附件",        "icon": "📎", "tab_group": "misc",         "sort_order": 10},
    {"type_key": "deploy_manifest",   "category": "document", "display_name": "部署清单",    "icon": "🚀", "tab_group": "delivery",     "sort_order": 11},
]


class TaskArtifact(Base):
    __tablename__ = "task_artifacts"
    __table_args__ = (
        UniqueConstraint("task_id", "artifact_type", "version", name="uq_task_artifact_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("pipeline_tasks.id", ondelete="CASCADE"), index=True,
    )
    stage_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    artifact_type: Mapped[str] = mapped_column(
        String(50), ForeignKey("artifact_type_registry.type_key"),
    )

    title: Mapped[str] = mapped_column(String(500), default="")
    storage_path: Mapped[str] = mapped_column(String(1000), default="")
    mime_type: Mapped[str] = mapped_column(String(100), default="text/markdown")

    version: Mapped[int] = mapped_column(Integer, default=1)
    is_latest: Mapped[bool] = mapped_column(default=True)
    status: Mapped[str] = mapped_column(String(20), default="active")

    created_by_agent: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_by_user: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    content: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JsonDict(), default=dict)

    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())
    updated_at: Mapped[datetime] = mapped_column(server_default=utcnow_default(), onupdate=datetime.utcnow)
