"""FastAPI dependencies for auth + RBAC.

Two layers:

- :func:`get_current_user` -- extracts the JWT from the
  ``session_token`` cookie (or ``Authorization: Bearer ...`` header),
  decodes it, loads the user from storage, and returns it.
- :func:`require_admin` -- wraps :func:`get_current_user` and rejects
  non-admin callers with HTTP 403.
- :func:`require_approved` -- rejects unapproved / inactive users with
  HTTP 403 (defense in depth on top of :func:`get_current_user`).

The cookie name is ``session_token`` to match the spec's contract
(``HttpOnly``, ``Secure`` in production, ``SameSite=Lax``).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import User, UserRole
from app.auth.security import TokenError, decode_token

logger = logging.getLogger(__name__)


# ``auto_error=False`` so we can also accept cookies without the
# ``HTTPBearer`` machinery yelling first.
_bearer_scheme = HTTPBearer(auto_error=False)


_COOKIE_NAME = "session_token"


def _extract_token(request: Request) -> Optional[str]:
    """Pull a JWT from the ``session_token`` cookie first, then the
    ``Authorization: Bearer`` header.
    """
    cookie_token = request.cookies.get(_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    auth_header = request.headers.get("authorization") or request.headers.get(
        "Authorization"
    )
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header.split(None, 1)[1].strip() or None
    return None


def _load_user_from_token(request: Request, token: str) -> Optional[User]:
    """Resolve a JWT to a :class:`User`, or ``None`` on any failure."""
    from app.auth.storage import UserStore

    settings = request.app.state.settings
    secret = getattr(settings.auth, "jwt_secret", None) or ""
    if not secret:
        logger.error("auth.jwt_secret is not configured; rejecting auth")
        return None
    try:
        payload = decode_token(token, secret=secret, expected_kind="access")
    except TokenError as exc:
        logger.debug("auth token rejected: %s", exc)
        return None
    user_id = str(payload.get("sub") or "")

    # Try to use the lifespan-built UserStore first (preferred). Tests
    # that build their own storage layer set ``app.state.user_store``.
    store: Optional[UserStore] = getattr(request.app.state, "user_store", None)
    if store is None:
        from app.auth.storage import UserStore

        store = UserStore(settings)
    user = store.get_user(user_id)
    if user is None:
        return None
    if not user.is_active or not user.is_approved:
        return None
    return user


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def get_current_user(
    request: Request,
    bearer: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> User:
    """Resolve the request to a logged-in :class:`User`.

    Raises HTTP 401 if the request is unauthenticated.
    """
    # ``bearer`` is only present when the Authorization header was sent;
    # the cookie path is handled by :func:`_extract_token`.
    del bearer  # silence unused-arg lint; the helper already covers it

    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
        )
    user = _load_user_from_token(request, token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired session",
        )
    return user


def require_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Reject non-admin callers with HTTP 403."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin role required",
        )
    return user


def require_approved(
    user: User = Depends(get_current_user),
) -> User:
    """Reject inactive / unapproved users with HTTP 403.

    ``get_current_user`` already filters these out, but this dependency
    exists so future code paths (e.g. refresh on a now-disabled account)
    can be tightened without scanning callers.
    """
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="account disabled"
        )
    if not user.is_approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="account pending admin approval",
        )
    return user


__all__ = ["get_current_user", "require_admin", "require_approved"]
