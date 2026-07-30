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


__all__ = [
    "AdminKBView",
    "AuditEntry",
    "DashboardStats",
    "SettingsPayload",
]
