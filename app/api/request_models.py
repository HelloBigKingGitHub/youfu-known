"""HTTP request-body models (independent of the storage Pydantic models).

Kept separate from :mod:`app.kb.models` so the storage-layer entities
can evolve (extra fields, sqlite row factories) without breaking the
HTTP contract.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    """Body for ``POST /api/kbs``."""

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)


class KnowledgeBaseUpdate(BaseModel):
    """Body for ``PATCH /api/kbs/{kb_id}``."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=1024)
    is_public: Optional[bool] = Field(default=None)


__all__ = ["KnowledgeBaseCreate", "KnowledgeBaseUpdate"]
