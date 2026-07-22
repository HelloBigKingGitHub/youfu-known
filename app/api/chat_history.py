"""Chat history CRUD endpoints.

Mounted under the same ``/api/kbs/{kb_id}`` prefix as the live chat
endpoint. All four operations are synchronous (SQLite is local).

Each endpoint enforces per-user isolation: chat history for a KB is
partitioned by ``user_id`` so Alice's questions on a shared KB are
not visible to Bob, and vice-versa. Admins get full visibility via
the dedicated audit endpoints under :mod:`app.api.admin`.

- ``GET    /api/kbs/{kb_id}/chats``             -- newest-first list
                                                 (current user only)
- ``GET    /api/kbs/{kb_id}/chats/{turn_id}``   -- single turn detail
                                                 (404 if owned by
                                                 another user)
- ``DELETE /api/kbs/{kb_id}/chats/{turn_id}``   -- single turn delete
- ``DELETE /api/kbs/{kb_id}/chats``             -- bulk delete (clear
                                                 only the current
                                                 user's turns)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api import ok
from app.auth.deps import get_current_user, require_admin
from app.auth.models import User, UserRole
from app.deps import get_kb_service
from app.kb.models import ChatTurn, Citation
from app.kb.service import KBService
from app.kb.storage import SQLiteStorage

router = APIRouter(prefix="/api/kbs/{kb_id}", tags=["chat_history"])
admin_audit_router = APIRouter(prefix="/api/admin", tags=["admin_audit"])


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
        "user_id": getattr(turn, "user_id", None),
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
    user: User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=500),
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """List the **current user's** chat turns for ``kb_id``, newest first.

    KB visibility (``user_can_read_kb``) is checked first to short-circuit
    non-members of a private KB; the per-user filter is then applied at
    the storage layer so users can never see each other's questions
    even on shared KBs.
    """
    is_admin = user.role == UserRole.ADMIN
    if not svc.user_can_read_kb(kb_id, user.id, is_admin=is_admin):
        raise HTTPException(status_code=403, detail="forbidden")
    storage = _get_storage(request)
    turns = storage.list_chat_turns(kb_id, limit=limit, user_id=user.id)
    return ok([_turn_payload(t) for t in turns])


@router.get("/chats/{turn_id}")
async def get_chat_history(
    kb_id: str,
    turn_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Fetch a single chat turn scoped to the current user.

    A turn that exists but belongs to a different user is treated as
    not found (HTTP 404). Avoiding 403 here closes the side-channel
    that would otherwise reveal "turn id ``X`` exists but isn't yours".
    """
    is_admin = user.role == UserRole.ADMIN
    if not svc.user_can_read_kb(kb_id, user.id, is_admin=is_admin):
        raise HTTPException(status_code=403, detail="forbidden")
    storage = _get_storage(request)
    turn: Optional[ChatTurn] = storage.get_chat_turn(
        kb_id, turn_id, user_id=user.id
    )
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
    user: User = Depends(get_current_user),
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Delete a single chat turn belonging to the current user.

    A user can delete their own turns on any KB they can READ (own,
    shared, or as admin). The per-user filter at the storage layer
    turns attempts to delete another user's row into a 404, so the
    caller cannot probe for turn ids that aren't theirs.
    """
    is_admin = user.role == UserRole.ADMIN
    if not svc.user_can_read_kb(kb_id, user.id, is_admin=is_admin):
        raise HTTPException(status_code=403, detail="forbidden")
    storage = _get_storage(request)
    deleted = storage.delete_chat_turn(kb_id, turn_id, user_id=user.id)
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"chat turn not found: {turn_id}"
        )
    return ok({"deleted": turn_id})


@router.delete("/chats")
async def clear_chat_history(
    kb_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Clear the current user's chat turns under ``kb_id``.

    Only the caller's turns are removed -- other users' history on
    the same shared KB is untouched. The READ check is enough here:
    anyone who can read a shared KB can scrub their own history
    without disturbing anyone else.
    """
    is_admin = user.role == UserRole.ADMIN
    if not svc.user_can_read_kb(kb_id, user.id, is_admin=is_admin):
        raise HTTPException(status_code=403, detail="forbidden")
    storage = _get_storage(request)
    removed = storage.clear_chat_turns(kb_id, user_id=user.id)
    return ok({"deleted_count": removed, "kb_id": kb_id})


__all__ = ["router", "admin_audit_router"]


# ---------------------------------------------------------------------------
# Admin audit endpoints
#
# These are mounted under ``/api/admin`` rather than ``/api/kbs`` so the
# existing route shapes aren't perturbed; they power the per-user and
# per-KB audit views used by the admin console.
# ---------------------------------------------------------------------------


@admin_audit_router.get("/kbs/{kb_id}/chats")
async def admin_list_kb_chats(
    kb_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    """List every user's chat turns for ``kb_id`` (admin audit only).

    Returns the same payload shape as the per-user endpoint, plus the
    ``user_id`` of the author so the admin can attribute turns
    across users in a shared KB.
    """
    storage = _get_storage(request)
    turns = storage.list_chat_turns(kb_id, limit=limit)
    return ok([_turn_payload(t) for t in turns])


@admin_audit_router.get("/users/{user_id}/chats")
async def admin_list_user_chats(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    """List every chat turn authored by ``user_id`` across all KBs.

    Used by the admin audit dashboard to inspect a user's history at
    a glance (e.g. when triaging an abuse report).
    """
    storage = _get_storage(request)
    turns = storage.list_chat_turns_for_user(user_id, limit=limit)
    return ok([_turn_payload(t) for t in turns])