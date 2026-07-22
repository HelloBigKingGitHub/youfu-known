"""Knowledge-base CRUD endpoints (``/api/kbs``).

All endpoints require an authenticated user. Reads filter by ownership
(admin sees all; member sees own + public). Writes require the caller
to be the owner or an admin.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api import ok
from app.api.request_models import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.auth.deps import get_current_user
from app.auth.models import User, UserRole
from app.deps import get_kb_service
from app.kb.service import (
    KBNotFoundError,
    KBService,
)

router = APIRouter(prefix="/api/kbs", tags=["knowledge_bases"])


# ---------------------------------------------------------------------------
# Mappers
# ---------------------------------------------------------------------------


def _kb_payload(kb) -> dict:
    """Serialise a :class:`KnowledgeBase` to a JSON-friendly dict.

    Both ``is_shared`` (the new, accurate name) and ``is_public`` (the
    deprecated alias) are returned with the same value so older
    clients keep working.
    """
    is_shared_flag = bool(getattr(kb, "is_shared", False))
    return {
        "id": kb.id,
        "name": kb.name,
        "description": kb.description,
        "owner_id": getattr(kb, "owner_id", None),
        "is_shared": is_shared_flag,
        "is_public": is_shared_flag,
        "created_at": kb.created_at.isoformat() if kb.created_at else None,
        "doc_count": kb.doc_count,
        "chunk_count": kb.chunk_count,
    }


def _doc_payload(doc) -> dict:
    """Serialise a :class:`Document` to a JSON-friendly dict."""
    return {
        "id": doc.id,
        "kb_id": doc.kb_id,
        "filename": doc.filename,
        "ext": doc.ext,
        "size_bytes": doc.size_bytes,
        "storage_path": doc.storage_path,
        "status": doc.status.value if hasattr(doc.status, "value") else doc.status,
        "error": doc.error,
        "chunk_count": doc.chunk_count,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "processed_at": (
            doc.processed_at.isoformat() if doc.processed_at else None
        ),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_kbs(
    user: User = Depends(get_current_user),
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """List knowledge bases visible to the current user."""
    is_admin = user.role == UserRole.ADMIN
    kbs = svc.list_kbs_for_user(user.id, is_admin=is_admin)
    # KBService.list_kbs returns models that include owner_id / is_public
    # only if SQLiteStorage was queried for them; in our schema they are
    # stored as separate columns and surfaced via the UserStore helper.
    # Use kb_owner_and_visibility to enrich the payload.
    return ok([_kb_payload(kb) for kb in kbs])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_kb(
    body: KnowledgeBaseCreate,
    user: User = Depends(get_current_user),
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Create a new knowledge base owned by the current user."""
    kb = svc.create_kb(
        name=body.name,
        description=body.description or "",
        owner_id=user.id,
        is_shared=False,
    )
    return ok(_kb_payload(kb))


@router.get("/{kb_id}")
async def kb_detail(
    kb_id: str,
    user: User = Depends(get_current_user),
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Return one KB along with its document list (if visible to caller)."""
    is_admin = user.role == UserRole.ADMIN
    if not svc.user_can_read_kb(kb_id, user.id, is_admin=is_admin):
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        detail = svc.get_kb_detail(kb_id)
    except KBNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # Enrich the KB payload with owner/visibility columns.
    enriched = _kb_payload(detail.kb)
    info = svc.kb_owner_and_visibility(kb_id)
    if info is not None:
        enriched["owner_id"] = info[0]
        enriched["is_shared"] = bool(info[1])
        enriched["is_public"] = bool(info[1])
    return ok(
        {
            "kb": enriched,
            "documents": [_doc_payload(d) for d in detail.documents],
        }
    )


@router.patch("/{kb_id}")
async def rename_kb(
    kb_id: str,
    body: KnowledgeBaseUpdate,
    user: User = Depends(get_current_user),
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Rename / update description / toggle ``is_shared``.

    Only the owner or an admin can mutate a KB. The body accepts
    either ``is_shared`` (preferred) or ``is_public`` (deprecated
    alias); if both are passed and disagree, ``is_shared`` wins.
    """
    is_admin = user.role == UserRole.ADMIN
    if not svc.user_can_write_kb(kb_id, user.id, is_admin=is_admin):
        raise HTTPException(status_code=403, detail="forbidden")
    is_shared_value = body.is_shared
    if is_shared_value is None:
        is_shared_value = body.is_public
    try:
        kb = svc.rename_kb(
            kb_id,
            name=body.name,
            description=body.description,
            is_shared=is_shared_value,
        )
    except KBNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(_kb_payload(kb))


@router.delete("/{kb_id}")
async def delete_kb(
    kb_id: str,
    user: User = Depends(get_current_user),
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Delete a KB (owner or admin only)."""
    is_admin = user.role == UserRole.ADMIN
    if not svc.user_can_write_kb(kb_id, user.id, is_admin=is_admin):
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        svc.delete_kb(kb_id)
    except KBNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ok({"deleted": kb_id})
