"""Pydantic models shared between the service layer and the HTTP layer.

These mirror the SQLite schema in ``openspec/spec.md`` §4.1 and the
response shape in §5.3 / §5.4.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DocumentStatus(str, Enum):
    """Document lifecycle states."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Core entities
# ---------------------------------------------------------------------------


class KnowledgeBase(BaseModel):
    """A single knowledge base."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str = ""
    created_at: datetime
    doc_count: int = 0
    chunk_count: int = 0
    owner_id: Optional[str] = None
    is_shared: bool = False
    # Deprecated alias kept for backwards-compatible API responses.
    # Always mirrors ``is_shared``; new clients should read ``is_shared``.
    is_public: Optional[bool] = None


class Document(BaseModel):
    """Metadata for a single uploaded document."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    kb_id: str
    filename: str
    ext: str
    size_bytes: int
    storage_path: str
    status: DocumentStatus
    error: str = ""
    chunk_count: int = 0
    created_at: datetime
    processed_at: Optional[datetime] = None


class UploadedFile(BaseModel):
    """Per-file summary returned from an upload."""

    doc_id: str
    filename: str
    status: DocumentStatus


class KBDetail(BaseModel):
    """Knowledge base plus its documents and aggregate stats."""

    kb: KnowledgeBase
    documents: List[Document] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Chat request / response
# ---------------------------------------------------------------------------


class Citation(BaseModel):
    """Source citation carried in the chat response."""

    n: int
    doc_id: str
    doc_filename: str
    chunk_idx: int
    chunk_id: str = ""  # "{doc_id}::{chunk_idx}", convenience for clients
    score: float
    text: str


class ChatRequest(BaseModel):
    """Body of ``POST /api/kbs/{kb_id}/chat``."""

    question: str = Field(min_length=1)
    top_k: Optional[int] = Field(default=None, ge=1, le=50)
    stream: bool = False


class ChatResponse(BaseModel):
    """``data`` payload of a non-streaming chat response."""

    answer: str
    citations: List[Citation] = Field(default_factory=list)


class ChatTurn(BaseModel):
    """Persisted chat turn (one Q + A pair) belonging to a KB.

    Mirrors the ``chat_turns`` table. ``citations`` is stored as JSON
    inside ``citations_json`` so we don't need a separate join table.

    ``user_id`` is the authenticated user that asked the question. The
    chat history endpoint filters on it so that turns are isolated per
    user; the orphan-row lifecycle migration stamps any pre-existing
    NULLs onto the bootstrap admin.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    kb_id: str
    question: str
    answer: str = ""
    error: str = ""
    citations: List[Citation] = Field(default_factory=list)
    status: str  # "ready" | "failed"
    user_id: str
    created_at: datetime
    latency_ms: int = 0


class ChunkMeta(BaseModel):
    """Persisted chunk metadata (mirrors the ``chunks`` table).

    The matching Chroma id is ``"{doc_id}::{chunk_idx}"``; we use the
    same string as the primary key here so lookups by Chroma id are
    trivial.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str  # "{doc_id}::{chunk_idx}"
    doc_id: str
    kb_id: str
    chunk_idx: int
    content: str
    char_count: int
    token_estimate: int = 0
    start_offset: int = 0
    end_offset: int = 0
    created_at: datetime


# ---------------------------------------------------------------------------
# Generic envelope
# ---------------------------------------------------------------------------


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Uniform JSON envelope: success -> ``{code:0, data:...}``."""

    code: int = 0
    data: Optional[T] = None
    message: Optional[str] = None

    @classmethod
    def ok(cls, data: T) -> "ApiResponse[T]":
        return cls(code=0, data=data, message=None)

    @classmethod
    def fail(cls, code: int, message: str) -> "ApiResponse[Any]":
        return cls(code=code, data=None, message=message)


# ---------------------------------------------------------------------------
# Re-exports
# ---------------------------------------------------------------------------

__all__ = [
    "DocumentStatus",
    "KnowledgeBase",
    "Document",
    "UploadedFile",
    "KBDetail",
    "Citation",
    "ChatRequest",
    "ChatResponse",
    "ChatTurn",
    "ChunkMeta",
    "ApiResponse",
]