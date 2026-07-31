"""Administrator endpoints for per-user feature flags."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.admin.schemas import FeatureFlagResponse
from app.api import ok
from app.auth.deps import require_admin
from app.auth.models import User
from app.feature_flag_decorator import get_feature_flag_service
from app.feature_flags import Feature

router = APIRouter(prefix="/api/admin", tags=["admin"])


class UpdateFeatureFlagRequest(BaseModel):
    enabled: bool


@router.get("/users/{user_id}/features")
async def list_user_features(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    del admin
    service = get_feature_flag_service(request)
    flags = service.list_user_flags(user_id)
    return ok([FeatureFlagResponse.from_flag(flag) for flag in flags])


@router.put("/users/{user_id}/features/{feature}")
async def update_user_feature(
    user_id: str,
    feature: str,
    body: UpdateFeatureFlagRequest,
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    try:
        selected_feature = Feature(feature)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown feature: {feature}",
        ) from exc

    service = get_feature_flag_service(request)
    flag = service.set_flag(
        user_id,
        selected_feature,
        body.enabled,
        admin.id,
    )
    return ok(FeatureFlagResponse.from_flag(flag))


@router.get("/features")
async def list_all_features(
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    del admin
    service = get_feature_flag_service(request)
    flags = service.list_all()
    return ok([FeatureFlagResponse.from_flag(flag) for flag in flags])


__all__ = ["router"]
