from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Boolean, Float, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from ..compat import GUID, JsonDict, utcnow_default

logger = logging.getLogger(__name__)

_fernet = None


def _get_fernet():
    """Lazily init Fernet using JWT_SECRET as key material (HMAC → 32-byte key)."""
    global _fernet
    if _fernet is not None:
        return _fernet

    from ..config import settings
    secret = settings.jwt_secret
    if not secret or len(secret) < 16:
        logger.warning("[model_provider] JWT_SECRET too short for encryption — API keys stored as plaintext")
        return None

    try:
        import hashlib
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        _fernet = Fernet(key)
        return _fernet
    except ImportError:
        logger.warning("[model_provider] cryptography package not installed — API keys stored as plaintext")
        return None


def encrypt_api_key(plaintext: str) -> str:
    if not plaintext:
        return ""
    f = _get_fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    f = _get_fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except Exception:
        return ciphertext


class ModelProvider(Base):
    """Provider configuration with encrypted API keys."""
    __tablename__ = "model_providers"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    label: Mapped[str] = mapped_column(String(100))
    models_url: Mapped[str] = mapped_column(String(500), default="")
    chat_url: Mapped[str] = mapped_column(String(500), default="")
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JsonDict(), default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())
    updated_at: Mapped[datetime] = mapped_column(server_default=utcnow_default(), onupdate=datetime.utcnow)

    def set_api_key(self, plaintext: str) -> None:
        self.api_key_encrypted = encrypt_api_key(plaintext)

    def get_api_key(self) -> str:
        return decrypt_api_key(self.api_key_encrypted)


class TokenUsage(Base):
    """Track every LLM call for cost analysis."""
    __tablename__ = "token_usage"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("orgs.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    endpoint: Mapped[str] = mapped_column(String(50), default="chat")
    metadata_extra: Mapped[dict] = mapped_column(JsonDict(), default=dict)

    created_at: Mapped[datetime] = mapped_column(server_default=utcnow_default())
