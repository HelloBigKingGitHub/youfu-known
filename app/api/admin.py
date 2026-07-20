"""Admin HTTP endpoints for user management.

All routes require an admin caller -- the ``require_admin`` dependency
filters non-admins out with HTTP 403 before they reach the body.

Routes:

- ``GET    /api/admin/users``              -- list every user
- ``PATCH  /api/admin/users/{user_id}``    -- flip is_approved / role / is_active
- ``DELETE /api/admin/users/{user_id}``    -- delete (cascades to their KBs)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api import ok
from app.auth.deps import require_admin
from app.auth.models import User, UserUpdate
from app.auth.service import (
    CannotDemoteSelfError,
    UserNotFoundError,
)
from app.kb.service import KBService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role.value,
        "is_active": user.is_active,
        "is_approved": user.is_approved,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": (
            user.last_login_at.isoformat() if user.last_login_at else None
        ),
    }


def _get_service(request: Request):
    svc = getattr(request.app.state, "auth_service", None)
    if svc is None:
        raise HTTPException(
            status_code=500, detail="auth service not initialised"
        )
    return svc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/users")
async def list_users(
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    """List every user account (admin only)."""
    svc = _get_service(request)
    users = svc.list_users()
    return ok([_user_payload(u) for u in users])


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdate,
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    """Approve / un-approve / change role / activate / deactivate a user."""
    svc = _get_service(request)
    try:
        updated = svc.update_user(
            acting_user_id=admin.id,
            target_user_id=user_id,
            is_approved=body.is_approved,
            role=body.role,
            is_active=body.is_active,
            email=body.email,
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CannotDemoteSelfError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(_user_payload(updated))


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    """Delete a user (cascades to their KBs / docs / chats via SQLite FKs)."""
    svc = _get_service(request)
    # Best-effort cleanup of KB upload directories + Chroma collections
    # owned by this user. FK CASCADE will handle the SQLite rows.
    kb_service: KBService | None = getattr(request.app.state, "kb_service", None)
    if kb_service is not None:
        storage = getattr(request.app.state, "storage", None)
        if storage is not None:
            from app.auth.storage import UserStore

            store = UserStore(
                request.app.state.settings, db_path=storage.db_path
            )
            visible_ids = store.list_kbs_visible_to(user_id, is_admin=True)
            # Only the KBs owned by this user (not public ones the admin
            # might be cleaning up) should be torn down.
            for kb_id in visible_ids:
                owner = store.get_kb_owner_and_visibility(kb_id)
                if owner and owner[0] == user_id:
                    try:
                        kb_service.delete_kb(kb_id)
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "failed to clean up kb %s during user delete", kb_id
                        )
    try:
        deleted = svc.delete_user(acting_user_id=admin.id, target_user_id=user_id)
    except CannotDemoteSelfError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ok({"deleted": user_id, "existed": deleted})


__all__ = ["router"]
