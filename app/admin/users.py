"""Users endpoint for administrators (Phase 1.5).

Phase 1.5 deliberately omits the PATCH /api/admin/users/{user_id}
mutation that the legacy :mod:`app.api.admin` exposes -- role
changes are deferred to Phase 2 (per the Phase 1.5 spec, only
list + delete are in scope).

Routes:

- ``GET    /api/admin/users``            -- list every user (no secrets)
- ``DELETE /api/admin/users/{user_id}``  -- delete a user (cascades to KBs)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api import ok
from app.auth.deps import require_admin
from app.auth.models import User
from app.admin import get_storage, get_user_store
from app.admin.schemas import UserResponse

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
async def list_users(
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    """List all users (admin only)."""
    del admin
    storage = get_storage(request)
    user_store = get_user_store(request, storage)

    users = user_store.list_users()
    return ok([UserResponse.from_user(u) for u in users])


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
