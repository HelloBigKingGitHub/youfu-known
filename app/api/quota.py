"""Quota HTTP endpoints.

Routes:
- ``GET    /api/users/me/quota``                       -- caller's own quota
- ``GET    /api/admin/users/{user_id}/quota``          -- admin view of one user
- ``POST   /api/admin/users/{user_id}/quota/reset``    -- admin manual reset

Envelope shape (same for both reads)::

    {
        "tokens_total": 100000,        # int; 0 means unlimited
        "tokens_used": 1234,
        "tokens_remaining": 98766,     # null when unlimited
        "period": "monthly",
        "reset_at": "2026-02-01T00:00:00" | null,
        "usage_breakdown": [
            {"date": "2026-01-15", "prompt_tokens": ..., "completion_tokens": ...,
             "total_tokens": ..., "calls": ...},
            ...
        ]
    }
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from app.admin.quota import QuotaService
from app.api import ok
from app.auth.deps import get_current_user, require_admin
from app.auth.models import User, UserRole
from app.auth.storage import UserStore

router = APIRouter(tags=["quota"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_user_store(request: Request) -> Optional[UserStore]:
    return getattr(request.app.state, "user_store", None)


def _get_quota_service(request: Request) -> Optional[QuotaService]:
    return getattr(request.app.state, "quota_service", None)


def _load_user_or_404(
    request: Request,
    user_id: str,
    acting_admin: User,
) -> User:
    """Load ``user_id`` as the admin caller, raising 404 on miss.

    A user trying to read another member's quota without admin rights
    never reaches this -- the dependency blocks them at the door.
    """
    del acting_admin
    store = _get_user_store(request)
    if store is None:
        raise HTTPException(status_code=500, detail="user_store not initialised")
    target = store.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail=f"user not found: {user_id}")
    return target


def _build_envelope(
    request: Request,
    user: User,
    *,
    days: int = 30,
) -> dict:
    """Render the unified quota envelope for ``user``."""
    quota_service = _get_quota_service(request)
    breakdown: list = []
    if quota_service is not None:
        try:
            breakdown = quota_service.get_usage_breakdown(user.id, days=days)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception(
                "Failed to load usage breakdown for %s", user.id
            )

    is_unlimited = user.quota_tokens_total <= 0
    remaining: Optional[int]
    if is_unlimited:
        remaining = None
    else:
        remaining = max(0, user.quota_tokens_total - user.quota_tokens_used)

    return {
        "tokens_total": int(user.quota_tokens_total),
        "tokens_used": int(user.quota_tokens_used),
        "tokens_remaining": remaining,
        "period": user.quota_period.value,
        "reset_at": (
            user.quota_period_reset_at.isoformat()
            if user.quota_period_reset_at
            else None
        ),
        "usage_breakdown": breakdown,
    }


# ---------------------------------------------------------------------------
# Caller's own quota
# ---------------------------------------------------------------------------


@router.get("/api/users/me/quota")
async def my_quota(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    """Return the caller's current quota state + 30-day breakdown."""
    # Auto-reset on read so the SPA always sees an up-to-date counter
    # even if no LLM call has happened since the boundary crossed.
    from datetime import datetime

    if user.role != UserRole.ADMIN:
        user.reset_quota_if_due(datetime.utcnow())
    return ok(_build_envelope(request, user))


# ---------------------------------------------------------------------------
# Admin: any user's quota
# ---------------------------------------------------------------------------


@router.get("/api/admin/users/{user_id}/quota")
async def admin_user_quota(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    """Admin view of one user's quota state + 30-day breakdown."""
    target = _load_user_or_404(request, user_id, admin)
    return ok(_build_envelope(request, target))


@router.post("/api/admin/users/{user_id}/quota/reset")
async def admin_reset_quota(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    """Zero the user's ``quota_tokens_used`` and advance the reset clock."""
    del admin
    quota_service = _get_quota_service(request)
    if quota_service is None:
        raise HTTPException(
            status_code=500, detail="quota_service not initialised"
        )
    refreshed = quota_service.reset_quota(user_id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail=f"user not found: {user_id}")
    return ok(_build_envelope(request, refreshed))


__all__ = ["router"]