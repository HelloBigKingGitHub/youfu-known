"""FastAPI dependency factory for user feature gates."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import Depends, HTTPException, Request

from app.feature_flags import Feature, FeatureFlagService


def get_feature_flag_service(request: Request) -> FeatureFlagService:
    """Return the process service, creating it from application settings once."""
    service = getattr(request.app.state, "feature_flag_service", None)
    if service is not None:
        return service

    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        from app.config import get_settings

        settings = get_settings()
    db_path: Path = settings.meta_db_abs()
    service = FeatureFlagService(db_path)
    request.app.state.feature_flag_service = service
    return service


def require_feature(feature: Feature) -> Callable:
    """Build a FastAPI dependency that gates one member feature."""
    from app.auth.deps import get_current_user
    from app.auth.models import User, UserRole

    def _dependency(
        request: Request,
        user: User = Depends(get_current_user),
    ) -> User:
        if user.role == UserRole.ADMIN:
            return user
        service = get_feature_flag_service(request)
        if not service.is_enabled(user.id, feature):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Feature '{feature.value}' is disabled. "
                    "Please contact admin."
                ),
            )
        return user

    return _dependency


__all__ = ["get_feature_flag_service", "require_feature"]
