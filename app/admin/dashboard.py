"""Dashboard endpoint for administrators."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api import ok
from app.auth.deps import require_admin
from app.auth.models import User
from app.admin import get_storage, get_user_store
from app.admin.stats import collect_dashboard_stats

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/dashboard")
async def dashboard(
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    """Return aggregate system statistics for the admin dashboard."""
    del admin
    storage = get_storage(request)
    user_store = get_user_store(request, storage)
    return ok(collect_dashboard_stats(storage, user_store))


__all__ = ["router"]
