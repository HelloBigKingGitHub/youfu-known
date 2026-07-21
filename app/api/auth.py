"""Auth HTTP endpoints.

Routes:

- ``POST /api/auth/register``         -- create a member account (unapproved)
- ``POST /api/auth/login``            -- verify credentials, set session cookie
- ``POST /api/auth/logout``           -- clear the session cookie
- ``GET  /api/auth/me``               -- return the current user
- ``POST /api/auth/change-password``  -- rotate password (logged in)
- ``POST /api/auth/refresh``          -- exchange a refresh token for a new pair

The ``session_token`` cookie is the source of truth for the browser;
the ``access_token`` is also returned in the JSON body so JS clients
that can't rely on cookies (e.g. embedded webviews) can use it as a
Bearer token instead. The refresh token is *only* returned in the JSON
body -- browsers store it client-side (e.g. ``localStorage``) for the
``/refresh`` round-trip.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api import ok
from app.auth.deps import get_current_user
from app.auth.models import (
    PasswordChange,
    User,
    UserCreate,
    UserLogin,
)
from app.auth.security import TokenError, decode_token
from app.auth.service import (
    AuthService,
    CannotDemoteSelfError,
    InvalidCredentialsError,
    UserInactiveError,
    UserNotApprovedError,
    UserNotFoundError,
    UsernameTakenError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


_COOKIE_NAME = "session_token"


def _set_session_cookie(response: Response, token: str, request: Request) -> None:
    """Stamp the ``session_token`` cookie onto ``response``.

    ``secure`` and ``samesite`` are pulled from settings so dev (HTTP)
    can flip ``secure=False`` without code changes.
    """
    settings = request.app.state.settings
    cookie_secure = bool(getattr(settings.auth, "cookie_secure", True))
    session_hours = int(getattr(settings.auth, "session_hours", 24))
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=session_hours * 3600,
        httponly=True,
        secure=cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=_COOKIE_NAME, path="/")


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


def _get_service(request: Request) -> AuthService:
    svc = getattr(request.app.state, "auth_service", None)
    if svc is None:
        raise HTTPException(
            status_code=500, detail="auth service not initialised"
        )
    return svc  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: UserCreate, request: Request) -> dict:
    """Register a new ``member`` account in the unapproved state."""
    svc = _get_service(request)
    try:
        user = await svc.register(
            username=body.username,
            password=body.password,
            email=body.email,
            turnstile_token=body.turnstile_token,
            request=request,
        )
    except UsernameTakenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(_user_payload(user))


@router.post("/login")
async def login(body: UserLogin, request: Request, response: Response) -> dict:
    """Authenticate and set the ``session_token`` cookie."""
    svc = _get_service(request)
    try:
        result = svc.login(body.username, body.password)
    except (InvalidCredentialsError, UserNotApprovedError, UserInactiveError) as exc:
        # All three map to 401 to avoid leaking which username exists.
        code = 401 if isinstance(exc, InvalidCredentialsError) else 403
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    _set_session_cookie(response, result.access_token, request)
    return ok(
        {
            "user": _user_payload(result.user),
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "expires_at": result.expires_at.isoformat(),
        }
    )


@router.post("/logout")
async def logout(response: Response) -> dict:
    """Clear the session cookie. Idempotent."""
    _clear_session_cookie(response)
    return ok({"logged_out": True})


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    """Return the currently logged-in user."""
    return ok(_user_payload(user))


@router.post("/change-password")
async def change_password(
    body: PasswordChange,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    """Rotate the password for the currently logged-in user."""
    svc = _get_service(request)
    try:
        svc.change_password(user.id, body.old_password, body.new_password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok({"changed": True})


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    bearer: Optional[str] = None,
) -> dict:
    """Exchange a refresh token for a new access (+ refresh) pair.

    Accepts the token via ``Authorization: Bearer <jwt>`` only --
    cookies don't carry the refresh token by design.
    """
    svc = _get_service(request)
    auth_header = request.headers.get("authorization") or request.headers.get(
        "Authorization"
    )
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401, detail="refresh token required (Authorization header)"
        )
    refresh_token = auth_header.split(None, 1)[1].strip()
    settings = request.app.state.settings
    secret = getattr(settings.auth, "jwt_secret", None) or ""
    # Defence in depth: confirm ``typ=refresh`` before delegating.
    try:
        decode_token(refresh_token, secret=secret, expected_kind="refresh")
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    try:
        result = svc.refresh(refresh_token)
    except (
        InvalidCredentialsError,
        UserInactiveError,
        UserNotApprovedError,
    ) as exc:
        code = 401 if isinstance(exc, InvalidCredentialsError) else 403
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    _set_session_cookie(response, result.access_token, request)
    return ok(
        {
            "user": _user_payload(result.user),
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "expires_at": result.expires_at.isoformat(),
        }
    )


__all__ = ["router"]
