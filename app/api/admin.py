"""Admin HTTP endpoints for user management.

All routes require an admin caller -- the ``require_admin`` dependency
filters non-admins out with HTTP 403 before they reach the body.

Routes:

- ``GET    /api/admin/users``              -- list every user
- ``PATCH  /api/admin/users/{user_id}``    -- flip is_approved / role / is_active
                                             + auto-grant feature flags
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
from app.feature_flag_decorator import get_feature_flag_service
from app.feature_flags import (
    ADMIN_DEFAULT_FEATURES,
    DEFAULT_USER_FEATURES,
    Feature,
)
from app.kb.service import KBService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Members who are approved get a baseline set of features turned on so
# they can actually use the product.  ``DOC_DELETE`` stays off — admins
# decide whether to grant it explicitly (per the Phase Feature Flags
# spec). When the user is un-approved all features are flipped off.
APPROVED_MEMBER_FEATURES: dict[Feature, bool] = {
    Feature.KB_CHAT: True,
    Feature.KB_CREATE: True,
    Feature.DOC_UPLOAD: True,
    Feature.DOC_DELETE: False,
    Feature.CHAT_HISTORY: True,
}


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


def _apply_auto_features(
    request: Request,
    acting_admin_id: str,
    target_user_id: str,
    *,
    previous_approved: bool,
    previous_role,
    new_approved: bool,
    new_role,
) -> None:
    """Sync the ``feature_flags`` table with the approval / role changes.

    Rules (per Phase 2.0 spec):

    - ``is_approved`` ``False -> True`` : enable ``KB_CHAT`` /
      ``KB_CREATE`` / ``DOC_UPLOAD`` / ``CHAT_HISTORY``;
      ``DOC_DELETE`` stays off.
    - ``is_approved`` ``True -> False`` : disable **all** features
      (member gets a full lockdown; mirrors Phase 1.5 ``is_active``
      semantics).
    - ``role`` becomes ``admin``       : enable all features.
    - ``role`` becomes ``member``      : fall back to the member
      default (``CHAT_HISTORY`` on, others off).

    We always overwrite the persisted overrides so the storage layer
    is the source of truth; the runtime default in
    :func:`FeatureFlagService.is_enabled` stays the fallback for
    users without overrides (e.g. freshly registered members).
    """
    service = get_feature_flag_service(request)

    # Compute the target set using the *new* state of the user. We
    # don't diff here because the spec asks for an idempotent sync.
    target: dict[Feature, bool]
    if new_role == "admin":
        target = dict(ADMIN_DEFAULT_FEATURES)
    elif new_approved:
        target = dict(APPROVED_MEMBER_FEATURES)
    else:
        # Locked-down unapproved member: every feature off.
        target = {feature: False for feature in Feature}

    for feature, enabled in target.items():
        try:
            service.set_flag(
                target_user_id,
                feature,
                enabled,
                granted_by=acting_admin_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to auto-set feature %s for user %s",
                feature.value,
                target_user_id,
            )
            # Continue with the rest; partial state is still better
            # than failing the whole admin action.

    logger.info(
        "auto-features for user %s by admin %s: role=%s approved=%s -> %s",
        target_user_id,
        acting_admin_id,
        new_role,
        new_approved,
        {f.value: target[f] for f in Feature},
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdate,
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    """Approve / un-approve / change role / activate / deactivate a user.

    When ``is_approved`` or ``role`` change, the
    :class:`FeatureFlagService` is reconciled so the user's
    feature overrides reflect the new state. See
    :func:`_apply_auto_features` for the policy table.
    """
    svc = _get_service(request)

    # Guard: admins cannot un-approve themselves (INC-005 / Phase 2.0
    # auto-feature rule). Without this guard the admin would lose all
    # their own features mid-session and lose access to the panel.
    if user_id == admin.id and body.is_approved is False:
        raise HTTPException(
            status_code=400,
            detail="cannot un-approve your own admin account",
        )

    # Look up the pre-mutation state so we can decide whether the
    # auto-feature sync should run.
    pre = svc.list_users()
    target_before = next((u for u in pre if u.id == user_id), None)
    if target_before is None:
        # Mirror the eventual 404 so the caller doesn't see two error
        # codes depending on which path failed first.
        raise HTTPException(
            status_code=404, detail=f"user not found: {user_id}"
        )

    previous_approved = target_before.is_approved
    previous_role = target_before.role

    try:
        updated = svc.update_user(
            acting_user_id=admin.id,
            target_user_id=user_id,
            is_approved=body.is_approved,
            role=body.role,
            is_active=body.is_active,
            email=body.email,
            quota_tokens_total=body.quota_tokens_total,
            quota_period=body.quota_period,
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CannotDemoteSelfError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Decide whether the feature flags need a sync. The sync fires if
    # ``is_approved`` flipped OR ``role`` flipped — even if the caller
    # only asked for one, we want the storage to reflect the new
    # combined state.
    is_approved_changed = (
        body.is_approved is not None
        and body.is_approved != previous_approved
    )
    role_changed = (
        body.role is not None and body.role != previous_role
    )

    if is_approved_changed or role_changed:
        # Self-demotion guard: only relevant when role changes to a
        # non-admin value. ``update_user`` already raises
        # CannotDemoteSelfError when ``role != ADMIN``, so reaching
        # this point means the role transition is permitted.
        _apply_auto_features(
            request,
            acting_admin_id=admin.id,
            target_user_id=user_id,
            previous_approved=previous_approved,
            previous_role=previous_role,
            new_approved=updated.is_approved,
            new_role=updated.role,
        )

    return ok(_user_payload(updated))


__all__ = ["router"]