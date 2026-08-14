"""Per-user token quota service (Phase 2.1).

Owns the ``user_token_usage`` ledger table and provides:

- :meth:`QuotaService.record_usage` -- append a usage row and bump the
  caller's :attr:`~app.auth.models.User.quota_tokens_used` counter.
- :meth:`QuotaService.get_usage_breakdown` -- aggregate the ledger by
  calendar day so the admin UI can chart spend.
- :meth:`QuotaService.reset_quota` -- admin-initiated manual reset:
  zero ``quota_tokens_used`` and push ``quota_period_reset_at`` to the
  next boundary for the user's current period.

The decorator / dependency that consults this state lives in
:mod:`app.admin.quota_decorator`; the HTTP envelope lives in
:mod:`app.api.quota`.

Design notes:

- We deliberately keep the ledger in a *separate* SQLite file from the
  KB storage. The schema migration in :mod:`app.auth.storage` already
  added the four ``users`` quota columns to the meta DB; appending
  per-call rows there would grow the meta DB on every chat turn. The
  ledger lives next to it (same file is fine -- the meta DB already
  carries other per-user metadata) but its own table for clarity.
- :meth:`record_usage` rolls the user's period forward via
  :meth:`~app.auth.models.User.reset_quota_if_due` *before* incrementing
  ``quota_tokens_used``. That keeps the counter consistent with the
  reset boundary the decorator reads on the next request.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional

from app.auth.models import QuotaPeriod, User, _compute_next_reset
from app.auth.storage import UserStore
from app.feature_flags import Feature

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


SCHEMA = """
CREATE TABLE IF NOT EXISTS user_token_usage (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT    NOT NULL,
    endpoint          TEXT    NOT NULL,
    feature           TEXT    NOT NULL,
    prompt_tokens     INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens      INTEGER NOT NULL,
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_user_token_usage_user_created
    ON user_token_usage(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_user_token_usage_created
    ON user_token_usage(created_at);
"""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class QuotaService:
    """Thread-safe quota ledger + counter service.

    The service is created once during the FastAPI lifespan and stored
    on ``app.state.quota_service``. Routers access it through
    :func:`app.admin.quota.get_quota_service` (FastAPI dependency).
    """

    def __init__(self, user_store: UserStore, db_path: Path | str) -> None:
        self._user_store = user_store
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    # ------------------------------------------------------------------
    # Connection / internals
    # ------------------------------------------------------------------

    @contextmanager
    def _cur(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
            finally:
                cur.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_usage(
        self,
        user_id: str,
        endpoint: str,
        feature: Feature | str,
        prompt_tokens: int,
        completion_tokens: int,
        now: datetime | None = None,
    ) -> None:
        """Append a usage row and bump ``user.quota_tokens_used``.

        The increment is performed by re-loading the user from the
        store, rolling the period forward if needed, and persisting
        the new counter via ``update_user``. We keep this synchronous
        (no background flush) because losing a counter row is
        preferable to losing money on the ledger side.

        ``feature`` is stored as its enum ``.value`` so the ledger
        outlives a future enum rename.

        ``now`` overrides the ledger ``created_at`` timestamp and the
        period-reset check (defaults to ``datetime.utcnow()``); tests
        use it to seed historical rows and to fast-forward across a
        period boundary without sleeping.
        """
        feature_value = (
            feature.value if isinstance(feature, Feature) else str(feature)
        )
        total = int(prompt_tokens) + int(completion_tokens)
        effective_now = now if now is not None else datetime.utcnow()
        now_iso = effective_now.isoformat()
        with self._cur() as cur:
            cur.execute(
                "INSERT INTO user_token_usage "
                "(user_id, endpoint, feature, prompt_tokens, "
                "completion_tokens, total_tokens, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    endpoint,
                    feature_value,
                    int(prompt_tokens),
                    int(completion_tokens),
                    total,
                    now_iso,
                ),
            )

        # Bump the user's running counter. We reload + mutate + save
        # so any pending reset (period boundary crossed) is honoured
        # before the increment.
        user = self._user_store.get_user(user_id)
        if user is None:
            logger.warning(
                "record_usage: user_id=%s not found in store; "
                "ledger row written but counter not bumped",
                user_id,
            )
            return
        if user.quota_tokens_total <= 0:
            # Unlimited -- ledger still recorded for analytics, but
            # the counter is meaningless.
            return
        user.reset_quota_if_due(now=effective_now)
        new_used = int(user.quota_tokens_used) + total
        # ``reset_quota_if_due`` may have changed quota_period_reset_at
        # in memory; persist both so they're durable.
        self._user_store.update_user(
            user_id,
            quota_tokens_used=new_used,
            quota_period_reset_at=user.quota_period_reset_at,
        )

    def get_usage_breakdown(
        self,
        user_id: str,
        days: int = 30,
    ) -> List[dict]:
        """Aggregate the ledger by calendar day for ``user_id``.

        Returns ``[{date, prompt_tokens, completion_tokens,
        total_tokens, calls}]`` sorted ascending by ``date``. Days
        with zero activity are omitted; callers can fill the gaps if
        they need a continuous chart.

        ``days`` is clamped to ``[1, 365]`` to keep the SQL cheap and
        the API predictable. ``days == 0`` is treated as "no window"
        and returns every ledger row for the user -- tests rely on
        that to query historical seeded data.
        """
        with self._cur() as cur:
            if int(days) == 0:
                rows = cur.execute(
                    "SELECT date(created_at) AS day, "
                    "       COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, "
                    "       COALESCE(SUM(completion_tokens), 0) AS completion_tokens, "
                    "       COALESCE(SUM(total_tokens), 0) AS total_tokens, "
                    "       COUNT(*) AS calls "
                    "FROM user_token_usage "
                    "WHERE user_id = ? "
                    "GROUP BY date(created_at) "
                    "ORDER BY date(created_at) ASC",
                    (user_id,),
                ).fetchall()
            else:
                window = max(1, min(int(days), 365))
                rows = cur.execute(
                    "SELECT date(created_at) AS day, "
                    "       COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, "
                    "       COALESCE(SUM(completion_tokens), 0) AS completion_tokens, "
                    "       COALESCE(SUM(total_tokens), 0) AS total_tokens, "
                    "       COUNT(*) AS calls "
                    "FROM user_token_usage "
                    "WHERE user_id = ? "
                    "  AND date(created_at) >= date('now', '-' || ? || ' days') "
                    "GROUP BY date(created_at) "
                    "ORDER BY date(created_at) ASC",
                    (user_id, window),
                ).fetchall()
        return [
            {
                "date": r["day"],
                "prompt_tokens": int(r["prompt_tokens"]),
                "completion_tokens": int(r["completion_tokens"]),
                "total_tokens": int(r["total_tokens"]),
                "calls": int(r["calls"]),
            }
            for r in rows
        ]

    def reset_quota(self, user_id: str) -> Optional[User]:
        """Admin-initiated manual reset.

        Zero the counter and push ``quota_period_reset_at`` to the
        next boundary for the user's *current* ``quota_period``.

        Returns the refreshed :class:`User` (so callers can render
        the new state in the API response), or ``None`` if the user
        no longer exists.
        """
        user = self._user_store.get_user(user_id)
        if user is None:
            return None
        anchor = datetime.utcnow()
        new_reset_at = _compute_next_reset(anchor, user.quota_period)
        return self._user_store.update_user(
            user_id,
            quota_tokens_used=0,
            quota_period_reset_at=new_reset_at,
        )


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_quota_service(request) -> "QuotaService":
    """FastAPI dependency: pull the singleton off ``app.state``.

    Falls back to building one if the lifespan hasn't been wired
    (mirrors the pattern in :mod:`app.feature_flag_decorator`). The
    fallback uses the same DB path as the ``UserStore`` so the
    counter updates land in the same file.
    """
    service = getattr(request.app.state, "quota_service", None)
    if service is not None:
        return service

    settings = getattr(request.app.state, "settings", None)
    user_store = getattr(request.app.state, "user_store", None)
    if user_store is None:
        from app.config import get_settings

        if settings is None:
            settings = get_settings()
        from app.auth.storage import UserStore

        user_store = UserStore(settings)
    if settings is None:
        from app.config import get_settings

        settings = get_settings()
    service = QuotaService(
        user_store=user_store,
        db_path=user_store.db_path,
    )
    request.app.state.quota_service = service
    return service


__all__ = [
    "QuotaService",
    "SCHEMA",
    "get_quota_service",
]