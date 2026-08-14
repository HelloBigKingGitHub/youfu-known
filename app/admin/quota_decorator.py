"""FastAPI dependency factory for the token-quota gate.

Mirrors :func:`app.feature_flag_decorator.require_feature`: composes
on top of :func:`app.auth.deps.get_current_user` so endpoints can
stack ``Depends(require_feature(...))`` + ``Depends(enforce_quota(...))``
on the same handler signature without re-deriving the user.

Rules:
- Admins always pass; ``is_admin`` is checked off the user object the
  feature decorator already loaded.
- Non-admins have their quota reset if it's due, then the remaining
  ceiling is compared against zero. Exceeding it raises HTTP 402
  with a message that names the next reset boundary so the SPA can
  show "you'll get more tokens on ...".
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from fastapi import Depends, HTTPException, Request

from app.auth.deps import get_current_user
from app.auth.models import User, UserRole
from app.auth.storage import UserStore
from app.feature_flags import Feature


def _get_user_store(request: Request) -> UserStore | None:
    """Return the lifespan-built user_store, if any.

    The decorator works fine without it -- when the UserStore is
    unavailable we can't auto-reset a stale clock, but the
    ``quota_exceeded`` check still uses the in-memory User we already
    have so an attacker can't bypass it.
    """
    return getattr(request.app.state, "user_store", None)


def _persist_reset(user: User, store: UserStore) -> None:
    """Push the auto-reset back to the database after a period flip.

    Best-effort: a failure here means the next request will redo the
    reset, which is harmless.
    """
    try:
        store.update_user(
            user.id,
            quota_tokens_used=user.quota_tokens_used,
            quota_period_reset_at=user.quota_period_reset_at,
        )
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception(
            "enforce_quota: failed to persist reset for user %s", user.id
        )


def enforce_quota(feature: Feature) -> Callable:
    """Build a FastAPI dependency that gates ``feature`` by quota.

    Order matters when stacking with :func:`require_feature` -- the
    feature gate should run first so we don't consume a quota check on
    a request that was already blocked by a missing feature flag. Both
    decorators stash ``user`` on the FastAPI dependency resolution
    cache, so the second one to run won't re-decode the JWT.
    """

    def _dependency(
        request: Request,
        user: User = Depends(get_current_user),
    ) -> User:
        if user.role == UserRole.ADMIN:
            return user

        # Auto-reset on first read of the period so the admin SPA
        # shows a sensible ``reset_at`` immediately after the deploy.
        now = datetime.utcnow()
        if user.quota_period_reset_at is None:
            user.reset_quota_if_due(now)
            store = _get_user_store(request)
            if store is not None:
                _persist_reset(user, store)

        if user.quota_exceeded():
            reset_at = user.quota_period_reset_at
            reset_str = (
                reset_at.isoformat() if reset_at is not None else "soon"
            )
            raise HTTPException(
                status_code=402,
                detail=(
                    f"quota exceeded, reset at {reset_str}"
                ),
            )
        return user

    return _dependency


__all__ = ["enforce_quota"]