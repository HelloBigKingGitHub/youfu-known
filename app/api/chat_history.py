"""Chat history CRUD endpoints.

Mounted under the same ``/api/kbs/{kb_id}`` prefix as the live chat
endpoint. All four operations are synchronous (SQLite is local).

- ``GET    /api/kbs/{kb_id}/chats``             -- newest-first list
- ``GET    /api/kbs/{kb_id}/chats/{turn_id}``   -- single turn detail
- ``DELETE /api/kbs/{kb_id}/chats/{turn_id}``   -- single turn delete
- ``DELETE /api/kbs/{kb_id}/chats``             -- bulk delete (clear)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api import ok
from app.kb.models import ChatTurn, Citation
from app.kb.storage import SQLiteStorage

router = APIRouter(prefix="/api/kbs/{kb_id}", tags=["chat_history"])


# ---------------------------------------------------------------------------
# Mappers
# ---------------------------------------------------------------------------


def _citation_payload(c: Citation) -> dict:
    return {
        "n": c.n,
        "doc_id": c.doc_id,
        "doc_filename": c.doc_filename,
        "chunk_idx": c.chunk_idx,
        "chunk_id": c.chunk_id,
        "score": c.score,
        "text": c.text,
    }


def _turn_payload(turn: ChatTurn) -> dict:
    return {
        "id": turn.id,
        "kb_id": turn.kb_id,
        "question": turn.question,
        "answer": turn.answer,
        "error": turn.error,
        "citations": [_citation_payload(c) for c in turn.citations],
        "status": turn.status,
        "created_at": (
            turn.created_at.isoformat() if turn.created_at else None
        ),
        "latency_ms": turn.latency_ms,
    }


# ---------------------------------------------------------------------------
# Storage accessor (state-backed; falls back to lru_cache on settings)
# ---------------------------------------------------------------------------


def _get_storage(request: Request) -> SQLiteStorage:
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        # Should never happen post-lifespan, but keep the failure mode loud.
        raise HTTPException(
            status_code=500, detail="storage not initialised"
        )
    return storage  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/chats")
async def list_chat_history(
    kb_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    """List chat turns for ``kb_id``, newest first."""
    storage = _get_storage(request)
    turns = storage.list_chat_turns(kb_id, limit=limit)
    return ok([_turn_payload(t) for t in turns])


@router.get("/chats/{turn_id}")
async def get_chat_history(
    kb_id: str,
    turn_id: str,
    request: Request,
) -> dict:
    """Fetch a single chat turn with its full answer + citations."""
    storage = _get_storage(request)
    turn: Optional[ChatTurn] = storage.get_chat_turn(kb_id, turn_id)
    if turn is None:
        raise HTTPException(
            status_code=404, detail=f"chat turn not found: {turn_id}"
        )
    return ok(_turn_payload(turn))


@router.delete("/chats/{turn_id}")
async def delete_chat_history(
    kb_id: str,
    turn_id: str,
    request: Request,
) -> dict:
    """Delete a single chat turn."""
    storage = _get_storage(request)
    deleted = storage.delete_chat_turn(kb_id, turn_id)
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"chat turn not found: {turn_id}"
        )
    return ok({"deleted": turn_id})


@router.delete("/chats")
async def clear_chat_history(
    kb_id: str,
    request: Request,
) -> dict:
    """Delete every chat turn belonging to ``kb_id``.

    Used by the ChatPanel "clear" button. Counts the rows removed so
    the client can show a confirmation toast.
    """
    storage = _get_storage(request)
    removed = storage.clear_chat_turns(kb_id)
    return ok({"deleted_count": removed, "kb_id": kb_id})


__all__ = ["router"]