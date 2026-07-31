"""Pydantic contracts for the Phase 1 admin API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class DashboardStats(BaseModel):
    kbs: dict[str, Any]
    users: dict[str, Any]
    documents: dict[str, Any]
    chunks: int
    chat_turns_24h: int
    storage_bytes: int
    llm_calls_24h: int
    uploaded_24h: int


class AdminKBView(BaseModel):
    id: str
    name: str
    owner_id: Optional[str] = None
    owner_username: Optional[str] = None
    description: str = ""
    is_shared: bool
    is_public: bool
    doc_count: int
    chunk_count: int
    created_at: datetime


class AuditEntry(BaseModel):
    id: str
    type: str
    user_id: Optional[str] = None
    username: Optional[str] = None
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SettingsPayload(BaseModel):
    model_name: Optional[str] = None
    embedding_batch_size: Optional[int] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    max_upload_size_mb: Optional[int] = None


class UserResponse(BaseModel):
    """User response (matches ``/api/auth/me`` shape, no password_hash).

    Phase 1.5 deliberately keeps the field set identical to the legacy
    :func:`app.api.admin._user_payload` so the new admin SPA can swap
    from the old router to the new one without UI changes.
    """

    id: str
    username: str
    email: str = ""
    role: str
    is_active: bool
    is_approved: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None

    @classmethod
    def from_user(cls, user: Any) -> "UserResponse":
        role = (
            user.role.value
            if hasattr(user.role, "value")
            else str(user.role)
        )
        created_at = (
            user.created_at
            if isinstance(user.created_at, datetime)
            else _parse_dt(user.created_at)
        )
        last_login_at = getattr(user, "last_login_at", None)
        if last_login_at is not None and not isinstance(
            last_login_at, datetime
        ):
            last_login_at = _parse_dt(last_login_at)
        return cls(
            id=user.id,
            username=user.username,
            email=user.email or "",
            role=role,
            is_active=bool(user.is_active),
            is_approved=bool(user.is_approved),
            created_at=created_at,
            last_login_at=last_login_at,
        )


def _parse_dt(value: Any) -> datetime:
    """Best-effort ISO-8601 parse; falls back to ``datetime.utcnow()``."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.utcnow()


__all__ = [
    "AdminKBView",
    "AuditEntry",
    "DashboardStats",
    "SettingsPayload",
    "UserResponse",
]
