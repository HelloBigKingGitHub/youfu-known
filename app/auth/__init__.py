"""Authentication and RBAC module.

Public surface re-exported here so callers can ``from app.auth import ...``
without reaching into sub-modules. The dependency providers
(:func:`get_current_user`, :func:`require_admin`) are exposed so the
HTTP routers in :mod:`app.api` can wire them in via ``Depends(...)``.
"""

from __future__ import annotations

from app.auth.deps import get_current_user, require_admin, require_approved
from app.auth.models import (
    PasswordChange,
    User,
    UserCreate,
    UserLogin,
    UserRole,
    UserUpdate,
)
from app.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.auth.service import AuthService, AuthServiceError
from app.auth.storage import UserStore

__all__ = [
    "AuthService",
    "AuthServiceError",
    "PasswordChange",
    "User",
    "UserCreate",
    "UserLogin",
    "UserRole",
    "UserStore",
    "UserUpdate",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "get_current_user",
    "hash_password",
    "require_admin",
    "require_approved",
    "verify_password",
]
