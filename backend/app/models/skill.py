from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Text, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..compat import JsonDict, utcnow_default


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    author: Mapped[str] = mapped_column(String(100), default="system")

    prompt_template: Mapped[str] = mapped_column(Text, default="")
    input_schema: Mapped[dict] = mapped_column(JsonDict(), default=dict)
    output_schema: Mapped[dict] = mapped_column(JsonDict(), default=dict)
    config: Mapped[dict] = mapped_column(JsonDict(), default=dict)
    tags: Mapped[list] = mapped_column(JsonDict(), default=list)

    rules: Mapped[list] = mapped_column(JsonDict(), default=list)
    hooks: Mapped[list] = mapped_column(JsonDict(), default=list)
    plugins: Mapped[list] = mapped_column(JsonDict(), default=list)
    mcp_tools: Mapped[list] = mapped_column(JsonDict(), default=list)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    install_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())
    updated_at: Mapped[datetime] = mapped_column(server_default=utcnow_default(), onupdate=datetime.utcnow)
