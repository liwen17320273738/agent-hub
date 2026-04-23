"""
Credentials Vault — encrypted storage for API keys and OAuth tokens.

Uses Fernet symmetric encryption derived from JWT_SECRET.
"""
from __future__ import annotations

import hashlib
import base64
import uuid
from datetime import datetime
from typing import Optional

from cryptography.fernet import Fernet
from sqlalchemy import String, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..compat import GUID, utcnow_default
from ..config import settings


def _fernet() -> Fernet:
    raw = (settings.jwt_secret or "agent-hub-vault-fallback").encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(key)


class Credential(Base):
    __tablename__ = "credentials"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("orgs.id", ondelete="CASCADE"))
    workspace_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(50))
    credential_type: Mapped[str] = mapped_column(String(50), default="api_key")
    encrypted_value: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())
    updated_at: Mapped[datetime] = mapped_column(server_default=utcnow_default(), onupdate=datetime.utcnow)

    def set_value(self, plaintext: str) -> None:
        self.encrypted_value = _fernet().encrypt(plaintext.encode()).decode()

    def get_value(self) -> str:
        if not self.encrypted_value:
            return ""
        try:
            return _fernet().decrypt(self.encrypted_value.encode()).decode()
        except Exception:
            return ""
