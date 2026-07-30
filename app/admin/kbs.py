"""Cross-user knowledge-base management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api import ok
from app.auth.deps import require_admin
from app.auth.models import User
from app.admin import get_kb_service, get_storage
from app.kb.service import KBNotFoundError

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _list_kbs(storage) -> list[dict]:
    storage.init()
    with storage._connect() as conn:  # type: ignore[attr-defined]
        rows = conn.execute(
            """
            SELECT kb.id,
                   kb.name,
                   kb.owner_id,
                   u.username AS owner_username,
                   COALESCE(kb.is_shared, kb.is_public, 0) AS is_shared,
                   COALESCE(kb.is_public, kb.is_shared, 0) AS is_public,
                   (SELECT COUNT(*) FROM documents d WHERE d.kb_id = kb.id) AS doc_count,
                   (SELECT COUNT(*) FROM chunks c WHERE c.kb_id = kb.id) AS chunk_count,
                   kb.created_at
            FROM knowledge_bases AS kb
            LEFT JOIN users AS u ON u.id = kb.owner_id
            ORDER BY kb.created_at DESC, kb.rowid DESC
            """
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "owner_id": row["owner_id"],
            "owner_username": row["owner_username"],
            "is_shared": bool(row["is_shared"] or 0),
            "is_public": bool(row["is_public"] or 0),
            "doc_count": int(row["doc_count"] or 0),
            "chunk_count": int(row["chunk_count"] or 0),
            "created_at": _iso(row["created_at"]),
        }
        for row in rows
    ]


@router.get("/kbs")
async def list_admin_kbs(
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    """List every knowledge base, regardless of owner."""
    del admin
    return ok(_list_kbs(get_storage(request)))


@router.delete("/kbs/{kb_id}")
async def delete_admin_kb(
    kb_id: str,
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    """Force-delete any knowledge base as an administrator."""
    del admin
    service = get_kb_service(request)
    try:
        service.delete_kb(kb_id)
    except KBNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ok({"deleted": kb_id})


__all__ = ["router"]
