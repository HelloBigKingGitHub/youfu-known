"""Users endpoint for administrators (Phase 1.5 + Phase 2.0).

Phase 1.5 shipped the bare :func:`list_users` and
:func:`delete_user` routes; Phase 2.0 layers search / filter /
pagination on top, plus a per-user ``/stats`` endpoint so the admin
SPA can show KB / document / chat counts next to the feature-flag
matrix.

Routes:

- ``GET    /api/admin/users``                  -- list + search + paginate
- ``GET    /api/admin/users/{user_id}/stats``  -- kb/doc/chat counts
- ``DELETE /api/admin/users/{user_id}``        -- delete a user (cascades)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api import ok
from app.auth.deps import require_admin
from app.auth.models import User, UserRole
from app.admin import get_storage, get_user_store
from app.admin.schemas import UserResponse

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Hard upper bound on ``limit`` — matches the spec; admin SPA also reads
# the same constant via the README.
_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50


def _coerce_bool(value: Optional[str]) -> Optional[bool]:
    """Parse a query-string boolean (``true`` / ``false`` / ``1`` / ``0``).

    Returns ``None`` for empty / missing values so the storage layer
    can distinguish "not specified" from a real False.
    """
    if value is None:
        return None
    normalised = value.strip().lower()
    if normalised in ("", "all", "any", "null"):
        return None
    if normalised in ("1", "true", "yes", "on"):
        return True
    if normalised in ("0", "false", "no", "off"):
        return False
    # Anything else — treat as "unrecognised"; let callers fail loudly.
    raise HTTPException(
        status_code=400,
        detail=(
            f"invalid boolean value: {value!r} "
            "(expected true/false/1/0 or omitted)"
        ),
    )


def _coerce_role(value: Optional[str]) -> Optional[UserRole]:
    if value is None or value.strip() in ("", "all", "any"):
        return None
    try:
        return UserRole(value.strip().lower())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"invalid role: {value!r} (expected admin/member)",
        ) from exc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/users")
async def list_users(
    request: Request,
    q: Optional[str] = Query(
        default=None,
        description="Case-insensitive substring match against username/email.",
    ),
    role: Optional[str] = Query(
        default=None,
        description="Exact role filter: admin / member (omit for all).",
    ),
    is_approved: Optional[str] = Query(
        default=None,
        description="Approval filter: true / false (omit for all).",
    ),
    is_active: Optional[str] = Query(
        default=None,
        description="Active filter: true / false (omit for all).",
    ),
    limit: int = Query(
        default=_DEFAULT_LIMIT,
        ge=1,
        le=_MAX_LIMIT,
        description=f"Page size (1..{_MAX_LIMIT}, default {_DEFAULT_LIMIT}).",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Number of rows to skip (default 0).",
    ),
    admin: User = Depends(require_admin),
) -> dict:
    """Search, filter and paginate users (admin only)."""
    del admin
    storage = get_storage(request)
    user_store = get_user_store(request, storage)

    items, total = user_store.search_users(
        q=q,
        role=_coerce_role(role),
        is_approved=_coerce_bool(is_approved),
        is_active=_coerce_bool(is_active),
        limit=limit,
        offset=offset,
    )
    return ok(
        {
            "total": int(total),
            "limit": int(limit),
            "offset": int(offset),
            "items": [
                UserResponse.from_user(u) for u in items
            ],
        }
    )


@router.get("/users/{user_id}/stats")
async def user_stats(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    """Return KB / document / chat counts owned by ``user_id``.

    Shares the same SQLite file as the auth store, so we open a
    short-lived read connection to count rows. Admins also use this
    to size the quota dashboards in a later phase.
    """
    del admin
    storage = get_storage(request)
    user_store = get_user_store(request, storage)

    if user_store.get_user(user_id) is None:
        raise HTTPException(
            status_code=404, detail=f"user not found: {user_id}"
        )

    with user_store._connect() as conn:  # type: ignore[attr-defined]
        kb_count = int(
            (
                conn.execute(
                    "SELECT COUNT(*) AS n FROM knowledge_bases "
                    "WHERE owner_id = ?",
                    (user_id,),
                ).fetchone()
                or {"n": 0}
            )["n"]
            or 0
        )
        doc_count = int(
            (
                conn.execute(
                    "SELECT COUNT(*) AS n FROM documents "
                    "WHERE owner_id = ?",
                    (user_id,),
                ).fetchone()
                or {"n": 0}
            )["n"]
            or 0
        )
        chat_count = int(
            (
                conn.execute(
                    "SELECT COUNT(*) AS n FROM chat_turns "
                    "WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                or {"n": 0}
            )["n"]
            or 0
        )

    return ok(
        {
            "user_id": user_id,
            "kb_count": kb_count,
            "doc_count": doc_count,
            "chat_count": chat_count,
        }
    )


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    """Delete a user (admin only).

    Cascades to the user's KBs via FK CASCADE plus the best-effort
    cleanup loop in :func:`app.api.admin.delete_user` (the legacy
    admin router handles the same edge cases for the
    ``app/api/admin.py`` callers while we transition over).

    Admins cannot delete themselves (INC-005 / CannotDemoteSelfError
    pattern from :mod:`app.auth.service`).
    """
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="cannot delete yourself")

    storage = get_storage(request)
    user_store = get_user_store(request, storage)

    if user_store.get_user(user_id) is None:
        raise HTTPException(
            status_code=404, detail=f"user not found: {user_id}"
        )

    user_store.delete_user(user_id)
    return ok({"deleted": user_id, "existed": True})


__all__ = ["router"]