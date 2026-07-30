"""Approximate activity audit feed for administrators."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.api import ok
from app.auth.deps import require_admin
from app.auth.models import User
from app.admin import get_storage

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/audit")
async def list_admin_audit(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    admin: User = Depends(require_admin),
) -> dict:
    """Return recent login and chat activity, newest first."""
    del admin
    storage = get_storage(request)
    storage.init()
    with storage._connect() as conn:  # type: ignore[attr-defined]
        rows = conn.execute(
            """
            SELECT ct.id AS id,
                   'chat' AS type,
                   ct.user_id AS user_id,
                   u.username AS username,
                   ct.kb_id AS kb_id,
                   ct.question AS question,
                   ct.status AS status,
                   ct.latency_ms AS latency_ms,
                   ct.created_at AS created_at
            FROM chat_turns AS ct
            LEFT JOIN users AS u ON u.id = ct.user_id
            UNION ALL
            SELECT 'login:' || u.id AS id,
                   'login' AS type,
                   u.id AS user_id,
                   u.username AS username,
                   NULL AS kb_id,
                   NULL AS question,
                   NULL AS status,
                   NULL AS latency_ms,
                   u.last_login_at AS created_at
            FROM users AS u
            WHERE u.last_login_at IS NOT NULL
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

    payload = []
    for row in rows:
        if row["type"] == "login":
            detail = {"ip": None}
        else:
            detail = {
                "status": row["status"] or "",
                "latency_ms": int(row["latency_ms"] or 0),
            }
        payload.append(
            {
                "id": row["id"],
                "type": row["type"],
                "user_id": row["user_id"],
                "username": row["username"],
                "kb_id": row["kb_id"],
                "question": row["question"],
                "detail": detail,
                "created_at": (
                    row["created_at"].isoformat()
                    if hasattr(row["created_at"], "isoformat")
                    else row["created_at"]
                ),
            }
        )
    return ok(payload)


__all__ = ["router"]
