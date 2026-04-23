"""
Share-token service — HMAC-SHA256 signed tokens for public task sharing.

Token format: base64url( task_id | expires_epoch | hmac )
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from typing import Optional

from ..config import settings


def _secret() -> bytes:
    raw = settings.jwt_secret or "agent-hub-share-fallback"
    return hashlib.sha256(f"share:{raw}".encode()).digest()


def create_share_token(task_id: str, ttl_days: int = 7) -> str:
    expires = int(time.time()) + ttl_days * 86400
    payload = f"{task_id}|{expires}".encode()
    sig = hmac.new(_secret(), payload, hashlib.sha256).digest()[:16]
    raw = payload + b"|" + sig
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def verify_share_token(token: str) -> Optional[str]:
    """Return task_id if valid and not expired, else None."""
    try:
        padding = 4 - len(token) % 4
        if padding != 4:
            token += "=" * padding
        raw = base64.urlsafe_b64decode(token)
        parts = raw.rsplit(b"|", 1)
        if len(parts) != 2:
            return None
        payload, sig = parts
        expected = hmac.new(_secret(), payload, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        decoded = payload.decode()
        task_id, expires_str = decoded.rsplit("|", 1)
        if int(expires_str) < int(time.time()):
            return None
        return task_id
    except Exception:
        return None
