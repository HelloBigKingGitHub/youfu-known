"""Knowledge-base CRUD endpoints (``/api/kbs``).

All domain errors (``KBNotFoundError``, ``ValueError``) are allowed to
propagate to the global exception handlers registered in ``main.py``
so the unified ``{code, message}`` envelope is used everywhere.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api import ok
from app.api.request_models import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.deps import get_kb_service
from app.kb.service import KBService

router = APIRouter(prefix="/api/kbs", tags=["knowledge_bases"])


# ---------------------------------------------------------------------------
# Mappers
# ---------------------------------------------------------------------------


def _kb_payload(kb) -> dict:
    """Serialise a :class:`KnowledgeBase` to a JSON-friendly dict."""
    return {
        "id": kb.id,
        "name": kb.name,
        "description": kb.description,
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
async def list_kbs(svc: KBService = Depends(get_kb_service)) -> dict:
    """List all knowledge bases, newest first."""
    kbs = svc.list_kbs()
    return ok([_kb_payload(kb) for kb in kbs])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_kb(
    body: KnowledgeBaseCreate,
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Create a new knowledge base."""
    kb = svc.create_kb(name=body.name, description=body.description or "")
    return ok(_kb_payload(kb))


@router.get("/{kb_id}")
async def kb_detail(
    kb_id: str,
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Return one KB along with its document list and aggregate counts.

    ``KBNotFoundError`` is allowed to bubble up -- the global handler in
    ``main.py`` maps it to ``{code:404, message:...}``.
    """
    detail = svc.get_kb_detail(kb_id)
    return ok(
        {
            "kb": _kb_payload(detail.kb),
            "documents": [_doc_payload(d) for d in detail.documents],
        }
    )


@router.patch("/{kb_id}")
async def rename_kb(
    kb_id: str,
    body: KnowledgeBaseUpdate,
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Rename and/or update the description of a KB."""
    kb = svc.rename_kb(
        kb_id,
        name=body.name,
        description=body.description,
    )
    return ok(_kb_payload(kb))


@router.delete("/{kb_id}")
async def delete_kb(
    kb_id: str,
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Delete a KB (cascades to documents + Chroma collection)."""
    svc.delete_kb(kb_id)
    return ok({"deleted": kb_id})