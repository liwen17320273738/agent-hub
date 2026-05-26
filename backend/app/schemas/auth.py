from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, field_validator

# Permissive email regex — matches the frontend regex.
# Accepts .local / .test / .dev domains that Pydantic EmailStr rejects.
_EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


def _validate_email(v: str) -> str:
    """Validate email format without rejecting local/dev domains."""
    if not v or not v.strip():
        raise ValueError('Email is required')
    v = v.strip()
    if not _EMAIL_RE.match(v):
        raise ValueError('Invalid email format')
    return v


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator('email')
    @classmethod
    def _check_email(cls, v: str) -> str:
        return _validate_email(v)


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""
    role: str = "member"

    @field_validator('email')
    @classmethod
    def _check_email(cls, v: str) -> str:
        return _validate_email(v)


class UserInfo(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: str
    org_id: uuid.UUID

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserInfo
