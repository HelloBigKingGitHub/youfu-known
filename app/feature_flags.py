"""Per-user feature flag storage and default policy."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


class Feature(str, Enum):
    """Features that can be enabled or disabled for a member."""

    KB_CHAT = "kb_chat"
    KB_CREATE = "kb_create"
    DOC_UPLOAD = "doc_upload"
    DOC_DELETE = "doc_delete"
    CHAT_HISTORY = "chat_history"


DEFAULT_USER_FEATURES: dict[Feature, bool] = {
    Feature.KB_CHAT: False,
    Feature.KB_CREATE: False,
    Feature.DOC_UPLOAD: False,
    Feature.DOC_DELETE: False,
    Feature.CHAT_HISTORY: True,
}

ADMIN_DEFAULT_FEATURES: dict[Feature, bool] = {
    feature: True for feature in Feature
}


class FeatureFlag(BaseModel):
    """A persisted feature override for one user."""

    user_id: str
    feature: str
    enabled: bool
    granted_by: Optional[str] = None
    granted_at: Optional[datetime] = None
    created_at: datetime


SCHEMA = """
CREATE TABLE IF NOT EXISTS feature_flags (
    user_id     TEXT NOT NULL,
    feature     TEXT NOT NULL,
    enabled     INTEGER NOT NULL,
    granted_by  TEXT,
    granted_at  TIMESTAMP,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, feature)
);
CREATE INDEX IF NOT EXISTS idx_feature_flags_user
    ON feature_flags(user_id);
CREATE INDEX IF NOT EXISTS idx_feature_flags_feature
    ON feature_flags(feature);
"""


class FeatureFlagService:
    """Thread-safe SQLite service for per-user feature overrides."""

    SCHEMA = SCHEMA

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self.SCHEMA)

    @staticmethod
    def _feature_value(feature: Feature | str) -> str:
        if isinstance(feature, Feature):
            return feature.value
        return Feature(feature).value

    @staticmethod
    def _parse_datetime(value: object) -> Optional[datetime]:
        if value is None or isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    @classmethod
    def _row_to_flag(cls, row: sqlite3.Row) -> FeatureFlag:
        created_at = cls._parse_datetime(row["created_at"])
        return FeatureFlag(
            user_id=row["user_id"],
            feature=row["feature"],
            enabled=bool(row["enabled"]),
            granted_by=row["granted_by"],
            granted_at=cls._parse_datetime(row["granted_at"]),
            created_at=created_at or datetime.utcnow(),
        )

    def is_enabled(self, user_id: str, feature: Feature | str) -> bool:
        """Return the override when present, otherwise the member default."""
        feature_value = self._feature_value(feature)
        with self._lock:
            row = self._conn.execute(
                "SELECT enabled FROM feature_flags "
                "WHERE user_id = ? AND feature = ?",
                (user_id, feature_value),
            ).fetchone()
        if row is not None:
            return bool(row["enabled"])
        return DEFAULT_USER_FEATURES[Feature(feature_value)]

    def set_flag(
        self,
        user_id: str,
        feature: Feature | str,
        enabled: bool,
        granted_by: Optional[str],
    ) -> FeatureFlag:
        """Insert or replace a user's feature override."""
        feature_value = self._feature_value(feature)
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO feature_flags "
                "(user_id, feature, enabled, granted_by, granted_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    feature_value,
                    1 if enabled else 0,
                    granted_by,
                    now,
                    now,
                ),
            )
            row = self._conn.execute(
                "SELECT * FROM feature_flags "
                "WHERE user_id = ? AND feature = ?",
                (user_id, feature_value),
            ).fetchone()
        assert row is not None
        return self._row_to_flag(row)

    def list_user_flags(self, user_id: str) -> list[FeatureFlag]:
        """List only persisted overrides for one user."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM feature_flags "
                "WHERE user_id = ? ORDER BY feature",
                (user_id,),
            ).fetchall()
        return [self._row_to_flag(row) for row in rows]

    def list_all(self) -> list[FeatureFlag]:
        """List all persisted overrides for the admin overview."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM feature_flags "
                "ORDER BY user_id, feature"
            ).fetchall()
        return [self._row_to_flag(row) for row in rows]


__all__ = [
    "Feature",
    "FeatureFlag",
    "FeatureFlagService",
    "DEFAULT_USER_FEATURES",
    "ADMIN_DEFAULT_FEATURES",
]
