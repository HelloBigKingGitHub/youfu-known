"""Pydantic models for users and the auth HTTP contract.

Mirrors the ``users`` table in :mod:`app.auth.storage` and the JSON
payloads exchanged with the HTTP layer.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    """Role hierarchy. ``admin`` > ``member``."""

    ADMIN = "admin"
    MEMBER = "member"


# ---------------------------------------------------------------------------
# Core entity
# ---------------------------------------------------------------------------


class User(BaseModel):
    """A single user account. Never exposes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: str = ""
    role: UserRole
    is_active: bool = True
    is_approved: bool = False
    created_at: datetime
    last_login_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# HTTP request bodies
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    """Body for ``POST /api/auth/register``."""

    username: str = Field(
        min_length=3,
        max_length=32,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    email: str = Field(
        default="",
        max_length=254,
        pattern=r"^$|^[\w.+-]+@[\w-]+\.[\w.-]+$",
    )
    password: str = Field(min_length=8, max_length=256)


class UserLogin(BaseModel):
    """Body for ``POST /api/auth/login``."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    """Body for ``POST /api/auth/change-password``."""

    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class UserUpdate(BaseModel):
    """Body for ``PATCH /api/admin/users/{user_id}``.

    All fields optional; ``None`` means "do not change".
    """

    is_approved: Optional[bool] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    email: Optional[str] = Field(
        default=None,
        max_length=254,
        pattern=r"^$|^[\w.+-]+@[\w-]+\.[\w.-]+$",
    )


__all__ = [
    "PasswordChange",
    "User",
    "UserCreate",
    "UserLogin",
    "UserRole",
    "UserUpdate",
]
