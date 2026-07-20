"""Business logic for registration / login / password change.

Sits between the HTTP routers (:mod:`app.api.auth`,
:mod:`app.api.admin`) and the storage layer (:class:`UserStore`).

Responsibilities:
- Validation that doesn't belong in Pydantic (e.g. username
  uniqueness after the storage round-trip).
- Password hashing (calls :func:`hash_password`).
- Token minting on successful login.
- Login accounting (``touch_last_login``).
- Admin bootstrap when ``users`` is empty.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from app.auth.models import User, UserRole
from app.auth.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.auth.storage import UserStore
from app.config import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AuthServiceError(Exception):
    """Base class for auth-domain errors."""


class InvalidCredentialsError(AuthServiceError):
    """Wrong username or password. Translates to HTTP 401."""


class UserNotFoundError(AuthServiceError):
    """User id missing. Translates to HTTP 404."""


class UserNotApprovedError(AuthServiceError):
    """Account exists but admin hasn't approved it yet. 403."""


class UserInactiveError(AuthServiceError):
    """Account disabled by admin. 403."""


class UsernameTakenError(AuthServiceError):
    """Username collision on register. 409 / 400."""


class CannotDemoteSelfError(AuthServiceError):
    """Admin trying to remove their own admin role. 400."""


# ---------------------------------------------------------------------------
# Result envelopes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoginResult:
    """Returned from :meth:`AuthService.login`."""

    user: User
    access_token: str
    refresh_token: str
    expires_at: datetime


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AuthService:
    """Coordinates user CRUD + auth lifecycle."""

    def __init__(self, store: UserStore, settings: Settings) -> None:
        self._store = store
        self._settings = settings
        self._store.init()

    # ------------------------------------------------------------------
    # Admin bootstrap
    # ------------------------------------------------------------------

    def bootstrap_admin_if_empty(self) -> Optional[User]:
        """If the ``users`` table is empty, create the bootstrap admin.

        Uses ``settings.auth.admin_username`` / ``admin_password`` and
        marks the account ``is_approved=True, is_active=True``. Returns
        the created user, or ``None`` if no bootstrap was needed / no
        credentials were configured.

        The caller is expected to log the outcome so the operator sees
        what happened on first boot.
        """
        if self._store.count() > 0:
            return None
        username = self._settings.auth.admin_username
        password = self._settings.auth.admin_password
        if not username or not password:
            logger.warning(
                "users table is empty and YOUFU_ADMIN_USERNAME/PASSWORD are "
                "unset -- no bootstrap admin created. Set them in .env and "
                "restart to create the initial admin."
            )
            return None
        rounds = self._settings.auth.bcrypt_rounds
        password_hash = hash_password(password, rounds=rounds)
        user = self._store.create_user(
            username=username,
            password_hash=password_hash,
            role=UserRole.ADMIN,
            is_active=True,
            is_approved=True,
        )
        logger.info(
            "bootstrapped initial admin user '%s' (id=%s)", user.username, user.id
        )
        return user

    # ------------------------------------------------------------------
    # Registration / login / logout
    # ------------------------------------------------------------------

    def register(
        self,
        username: str,
        password: str,
        email: str = "",
    ) -> User:
        """Create a ``member`` account in the unapproved state.

        Approval is gated by an admin calling
        :meth:`update_user` with ``is_approved=True``.
        """
        username = (username or "").strip()
        if not username:
            raise ValueError("username must be non-empty")
        if not password or len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        rounds = self._settings.auth.bcrypt_rounds
        password_hash = hash_password(password, rounds=rounds)
        try:
            user = self._store.create_user(
                username=username,
                password_hash=password_hash,
                email=email or "",
                role=UserRole.MEMBER,
                is_active=True,
                is_approved=False,
            )
        except ValueError as exc:
            raise UsernameTakenError(str(exc)) from exc
        return user

    def login(self, username: str, password: str) -> LoginResult:
        """Verify credentials and mint a fresh access + refresh token."""
        user = self._store.get_by_username(username)
        if user is None:
            raise InvalidCredentialsError("invalid username or password")
        stored_hash = self._store.get_password_hash(user.id)
        if not stored_hash or not verify_password(password, stored_hash):
            raise InvalidCredentialsError("invalid username or password")
        if not user.is_active:
            raise UserInactiveError("account disabled")
        if not user.is_approved:
            raise UserNotApprovedError("account pending admin approval")

        self._store.touch_last_login(user.id)
        refreshed = self._store.get_user(user.id) or user

        secret = self._settings.auth.jwt_secret or ""
        if not secret:
            raise AuthServiceError("auth.jwt_secret not configured")

        session_hours = int(self._settings.auth.session_hours)
        refresh_days = int(self._settings.auth.refresh_days)
        access = create_access_token(
            refreshed.id,
            refreshed.role.value,
            secret=secret,
            expires_in=session_hours * 3600,
        )
        refresh = create_refresh_token(
            refreshed.id,
            secret=secret,
            expires_in=refresh_days * 24 * 3600,
        )
        expires_at = datetime.utcnow() + timedelta(hours=session_hours)
        return LoginResult(
            user=refreshed,
            access_token=access,
            refresh_token=refresh,
            expires_at=expires_at,
        )

    def refresh(self, refresh_token: str) -> LoginResult:
        """Validate a refresh token and mint a fresh access token."""
        from app.auth.security import TokenError, decode_token

        secret = self._settings.auth.jwt_secret or ""
        if not secret:
            raise AuthServiceError("auth.jwt_secret not configured")
        try:
            payload = decode_token(
                refresh_token, secret=secret, expected_kind="refresh"
            )
        except TokenError as exc:
            raise InvalidCredentialsError(str(exc)) from exc
        user_id = str(payload.get("sub") or "")
        user = self._store.get_user(user_id)
        if user is None:
            raise UserNotFoundError(f"user not found: {user_id}")
        if not user.is_active:
            raise UserInactiveError("account disabled")
        if not user.is_approved:
            raise UserNotApprovedError("account pending admin approval")

        session_hours = int(self._settings.auth.session_hours)
        access = create_access_token(
            user.id, user.role.value, secret=secret, expires_in=session_hours * 3600
        )
        refresh = create_refresh_token(
            user.id,
            secret=secret,
            expires_in=int(self._settings.auth.refresh_days) * 24 * 3600,
        )
        expires_at = datetime.utcnow() + timedelta(hours=session_hours)
        return LoginResult(
            user=user,
            access_token=access,
            refresh_token=refresh,
            expires_at=expires_at,
        )

    # ------------------------------------------------------------------
    # Password change
    # ------------------------------------------------------------------

    def change_password(self, user_id: str, old_password: str, new_password: str) -> None:
        """Rotate the user's password after verifying the old one."""
        if not new_password or len(new_password) < 8:
            raise ValueError("new password must be at least 8 characters")
        stored_hash = self._store.get_password_hash(user_id)
        if not stored_hash or not verify_password(old_password, stored_hash):
            raise InvalidCredentialsError("old password incorrect")
        rounds = self._settings.auth.bcrypt_rounds
        new_hash = hash_password(new_password, rounds=rounds)
        updated = self._store.update_user(user_id, password_hash=new_hash)
        if updated is None:
            raise UserNotFoundError(f"user not found: {user_id}")

    # ------------------------------------------------------------------
    # Admin operations
    # ------------------------------------------------------------------

    def list_users(self) -> list:
        return self._store.list_users()

    def update_user(
        self,
        acting_user_id: str,
        target_user_id: str,
        *,
        is_approved: Optional[bool] = None,
        role: Optional[UserRole] = None,
        is_active: Optional[bool] = None,
        email: Optional[str] = None,
    ) -> User:
        """Apply admin-driven mutations; refuses self-demotion."""
        target = self._store.get_user(target_user_id)
        if target is None:
            raise UserNotFoundError(f"user not found: {target_user_id}")
        if (
            target_user_id == acting_user_id
            and role is not None
            and role != UserRole.ADMIN
        ):
            raise CannotDemoteSelfError("cannot remove your own admin role")
        updated = self._store.update_user(
            target_user_id,
            is_approved=is_approved,
            role=role,
            is_active=is_active,
            email=email,
        )
        if updated is None:
            raise UserNotFoundError(f"user not found: {target_user_id}")
        return updated

    def delete_user(self, acting_user_id: str, target_user_id: str) -> bool:
        """Remove ``target_user_id``; admin cannot delete themselves."""
        if target_user_id == acting_user_id:
            raise CannotDemoteSelfError("cannot delete yourself")
        if self._store.get_user(target_user_id) is None:
            raise UserNotFoundError(f"user not found: {target_user_id}")
        return self._store.delete_user(target_user_id)


__all__ = [
    "AuthService",
    "AuthServiceError",
    "CannotDemoteSelfError",
    "InvalidCredentialsError",
    "LoginResult",
    "UserInactiveError",
    "UserNotApprovedError",
    "UserNotFoundError",
    "UsernameTakenError",
]
