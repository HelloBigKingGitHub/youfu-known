"""Phase 1 admin routers and shared request-state helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request

if TYPE_CHECKING:
    from app.kb.service import KBService
    from app.kb.storage import SQLiteStorage
    from app.auth.storage import UserStore

router = APIRouter()


def get_storage(request: Request) -> "SQLiteStorage":
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise HTTPException(status_code=500, detail="storage not initialised")
    return storage


def get_user_store(request: Request, storage: "SQLiteStorage") -> "UserStore":
    user_store = getattr(request.app.state, "user_store", None)
    if user_store is not None:
        return user_store

    from app.auth.storage import UserStore

    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="settings not initialised")
    fallback = UserStore(settings, db_path=storage.db_path)
    fallback.init()
    return fallback


def get_kb_service(request: Request) -> "KBService":
    service = getattr(request.app.state, "kb_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="kb service not initialised")
    return service


from app.admin import audit, dashboard, feature_flags, kbs, settings, users
from app.admin.schemas import (
    AdminKBView,
    AuditEntry,
    DashboardStats,
    FeatureFlagResponse,
    SettingsPayload,
    UserResponse,
)

router.include_router(dashboard.router)
router.include_router(kbs.router)
router.include_router(audit.router)
router.include_router(settings.router)
router.include_router(users.router)
router.include_router(feature_flags.router)

__all__ = [
    "AdminKBView",
    "AuditEntry",
    "DashboardStats",
    "FeatureFlagResponse",
    "SettingsPayload",
    "UserResponse",
    "router",
    "get_storage",
    "get_user_store",
    "get_kb_service",
]
