"""Pydantic models for users and the auth HTTP contract.

Mirrors the ``users`` table in :mod:`app.auth.storage` and the JSON
payloads exchanged with the HTTP layer.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    """Role hierarchy. ``admin`` > ``member``."""

    ADMIN = "admin"
    MEMBER = "member"


class QuotaPeriod(str, Enum):
    """How often a user's token quota resets.

    - ``monthly`` / ``weekly`` / ``daily``  -- rolling calendar periods
      aligned to UTC (next month 1st / next Monday / next day 00:00).
    - ``none``                              -- no auto-reset; quota stays
      ``used`` for the lifetime of the user until an admin resets it.
    """

    MONTHLY = "monthly"
    WEEKLY = "weekly"
    DAILY = "daily"
    NONE = "none"


# Sentinel value returned by :meth:`User.quota_remaining` when the user
# has unlimited quota (``quota_tokens_total == 0``). Big enough that any
# realistic usage number stays comfortably under it, so callers can use
# the remaining value as a quick ceiling without an extra branch.
_UNLIMITED_TOKENS = 10**12


# ---------------------------------------------------------------------------
# Core entity
# ---------------------------------------------------------------------------


def _compute_next_reset(now: datetime, period: QuotaPeriod) -> datetime:
    """Return the next reset boundary *after* ``now`` for ``period``.

    Boundaries are aligned to UTC:

    - ``daily``   -> next day 00:00 UTC
    - ``weekly``  -> next Monday 00:00 UTC (Monday is day 0)
    - ``monthly`` -> first day of next month 00:00 UTC
    - ``none``    -> far-future sentinel (no auto-reset scheduled)
    """
    if period == QuotaPeriod.NONE:
        # Sentinel: 100 years out. The store layer treats ``None`` and
        # this the same way -- only ``reset_quota`` advances it.
        return now + timedelta(days=365 * 100)

    if period == QuotaPeriod.DAILY:
        # Tomorrow 00:00 UTC.
        tomorrow = now.date() + timedelta(days=1)
        return datetime(tomorrow.year, tomorrow.month, tomorrow.day)

    if period == QuotaPeriod.WEEKLY:
        # Next Monday 00:00 UTC. weekday(): Monday == 0 ... Sunday == 6.
        days_ahead = (7 - now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        target = now.date() + timedelta(days=days_ahead)
        return datetime(target.year, target.month, target.day)

    if period == QuotaPeriod.MONTHLY:
        if now.month == 12:
            return datetime(now.year + 1, 1, 1)
        return datetime(now.year, now.month + 1, 1)

    # Defensive: unknown period -> behave like NONE.
    return now + timedelta(days=365 * 100)


class User(BaseModel):
    """A single user account. Never exposes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: str = ""
    role: UserRole
    is_active: bool = True
    is_approved: bool = False
    created_at: datetime
    last_login_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Convenience predicates
    # ------------------------------------------------------------------

    @property
    def is_admin(self) -> bool:
        """``True`` iff the user holds the admin role.

        The spec and decorator code reach for ``user.is_admin`` as a
        quick branch; we expose it as a thin wrapper around
        ``role == UserRole.ADMIN`` so callers don't need to import
        the enum everywhere.
        """
        return self.role == UserRole.ADMIN

    # ---- Quota fields (Phase 2.1) ---------------------------------------
    # ``quota_tokens_total`` of 0 means *unlimited* -- the user is never
    # blocked by the quota decorator. The default 100k matches the spec
    # for the first member cohort; admins typically get 0.
    quota_tokens_total: int = 100_000
    quota_tokens_used: int = 0
    quota_period: QuotaPeriod = QuotaPeriod.MONTHLY
    quota_period_reset_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Quota helpers
    # ------------------------------------------------------------------

    def reset_quota_if_due(self, now: Optional[datetime] = None) -> None:
        """If ``now >= quota_period_reset_at`` and the period is set, reset.

        Idempotent: callers can invoke this on every quota check without
        worrying about double-counting. ``now`` defaults to UTC ``now``
        (naive, to match how ``storage.py`` persists datetimes).
        """
        if self.quota_period == QuotaPeriod.NONE:
            return
        if self.quota_period_reset_at is None:
            # First read after upgrade -- schedule the next boundary so
            # the next call has a concrete target.
            anchor = now or datetime.utcnow()
            self.quota_period_reset_at = _compute_next_reset(
                anchor, self.quota_period
            )
            return
        anchor = now or datetime.utcnow()
        if anchor >= self.quota_period_reset_at:
            self.quota_tokens_used = 0
            self.quota_period_reset_at = _compute_next_reset(
                anchor, self.quota_period
            )

    def quota_remaining(self) -> int:
        """Return the number of tokens still available this period.

        ``0`` (``total``) means unlimited -- return the sentinel so the
        caller can use it as a ceiling without branching.
        """
        if self.quota_tokens_total <= 0:
            return _UNLIMITED_TOKENS
        return max(0, int(self.quota_tokens_total) - int(self.quota_tokens_used))

    def quota_exceeded(self) -> bool:
        """True iff the user has a finite quota AND is at/over the cap.

        Admin callers should bypass this check via the decorator.
        """
        if self.quota_tokens_total <= 0:
            return False
        return int(self.quota_tokens_used) >= int(self.quota_tokens_total)


# ---------------------------------------------------------------------------
# HTTP request bodies
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    """Body for ``POST /api/auth/register``."""

    username: str = Field(
        min_length=3,
        max_length=32,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    email: str = Field(
        default="",
        max_length=254,
        pattern=r"^$|^[\w.+-]+@[\w-]+\.[\w.-]+$",
    )
    password: str = Field(min_length=8, max_length=256)


class UserLogin(BaseModel):
    """Body for ``POST /api/auth/login``."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    """Body for ``POST /api/auth/change-password``."""

    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class UserUpdate(BaseModel):
    """Body for ``PATCH /api/admin/users/{user_id}``.

    All fields optional; ``None`` means "do not change".
    """

    is_approved: Optional[bool] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    email: Optional[str] = Field(
        default=None,
        max_length=254,
        pattern=r"^$|^[\w.+-]+@[\w-]+\.[\w.-]+$",
    )
    quota_tokens_total: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Token quota cap. 0 means unlimited. Set to None to leave "
            "unchanged."
        ),
    )
    quota_period: Optional[QuotaPeriod] = Field(
        default=None,
        description="How often the quota resets. None leaves unchanged.",
    )


__all__ = [
    "PasswordChange",
    "QuotaPeriod",
    "User",
    "UserCreate",
    "UserLogin",
    "UserRole",
    "UserUpdate",
]