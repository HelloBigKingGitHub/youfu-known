"""SQLite-backed user store.

Owns the ``users`` table and the owner/visibility columns added to
existing tables (``knowledge_bases``, ``documents``, ``chat_turns``).

Schema migration is idempotent: ``init()`` inspects existing columns
via ``PRAGMA table_info`` and runs ``ALTER TABLE ... ADD COLUMN`` only
for the missing ones. That makes it safe to call against databases
provisioned by earlier builds that lacked the auth columns.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional

from app.auth.models import User, UserRole
from app.config import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------


CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    email           TEXT DEFAULT '',
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member',
    is_active       INTEGER DEFAULT 1,
    is_approved     INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at   TIMESTAMP
);
"""


CREATE_USER_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return uuid.uuid4().hex


def _parse_dt(value, fallback: Optional[datetime] = None) -> datetime:
    if value is None:
        return fallback or datetime.utcnow()
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return fallback or datetime.utcnow()
    return fallback or datetime.utcnow()


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        email=row["email"] or "",
        role=UserRole(row["role"]),
        is_active=bool(row["is_active"]),
        is_approved=bool(row["is_approved"]),
        created_at=_parse_dt(row["created_at"]),
        last_login_at=_parse_dt(row["last_login_at"]) if row["last_login_at"] else None,
    )


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class UserStore:
    """Thread-safe user store, sharing the same SQLite file as :class:`SQLiteStorage`.

    We deliberately open our own connection per call rather than share
    one with :class:`app.kb.storage.SQLiteStorage` -- SQLite serialises
    writers at the file level, so two connections in the same process
    cooperate just fine, and keeping the schemas separate at the Python
    level avoids an awkward circular dependency.
    """

    def __init__(
        self,
        settings: Settings,
        db_path: Optional[Path] = None,
    ) -> None:
        self._db_path: Path = db_path or settings.meta_db_abs()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def db_path(self) -> Path:
        return self._db_path

    def init(self) -> None:
        """Create the ``users`` table and add owner/visibility columns.

        Idempotent: safe to call on every boot and against legacy DBs
        that lack the auth columns.
        """
        with self._lock:
            if self._initialized:
                return
            with self._connect() as conn:
                conn.executescript(CREATE_USERS_SQL + CREATE_USER_INDEX_SQL)
                self._ensure_owner_columns(conn)
                conn.commit()
            self._initialized = True

    def _ensure_owner_columns(self, conn: sqlite3.Connection) -> None:
        """Add owner_id / is_public / user_id columns to existing tables.

        Uses ``PRAGMA table_info`` to detect presence so re-running the
        migration on a DB that already has them is a no-op. Skips
        silently if the target tables don't exist yet -- the KB layer
        will create them on its own ``init()``.
        """
        existing_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "knowledge_bases" in existing_tables:
            existing_kb = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(knowledge_bases)"
                ).fetchall()
            }
            if "owner_id" not in existing_kb:
                conn.execute(
                    "ALTER TABLE knowledge_bases ADD COLUMN owner_id TEXT"
                )
            if "is_public" not in existing_kb:
                conn.execute(
                    "ALTER TABLE knowledge_bases ADD COLUMN is_public INTEGER DEFAULT 0"
                )

        if "documents" in existing_tables:
            existing_doc = {
                row[1]
                for row in conn.execute("PRAGMA table_info(documents)").fetchall()
            }
            if "owner_id" not in existing_doc:
                conn.execute("ALTER TABLE documents ADD COLUMN owner_id TEXT")

        if "chat_turns" in existing_tables:
            existing_turn = {
                row[1]
                for row in conn.execute("PRAGMA table_info(chat_turns)").fetchall()
            }
            if "user_id" not in existing_turn:
                conn.execute("ALTER TABLE chat_turns ADD COLUMN user_id TEXT")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_user(
        self,
        username: str,
        password_hash: str,
        email: str = "",
        role: UserRole = UserRole.MEMBER,
        is_active: bool = True,
        is_approved: bool = False,
    ) -> User:
        """Insert a new user; raises ``ValueError`` on duplicate username."""
        self.init()
        user_id = _new_id()
        with self._lock, self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO users (id, username, email, password_hash, "
                    "role, is_active, is_approved) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        user_id,
                        username,
                        email or "",
                        password_hash,
                        role.value,
                        1 if is_active else 0,
                        1 if is_approved else 0,
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"username already exists: {username}") from exc
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            assert row is not None
            return _row_to_user(row)

    def get_user(self, user_id: str) -> Optional[User]:
        self.init()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return _row_to_user(row) if row else None

    def get_by_username(self, username: str) -> Optional[User]:
        self.init()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
            return _row_to_user(row) if row else None

    def get_password_hash(self, user_id: str) -> Optional[str]:
        """Return the bcrypt hash for ``user_id`` (or None)."""
        self.init()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return row["password_hash"] if row else None

    def list_users(self) -> List[User]:
        self.init()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY created_at ASC, rowid ASC"
            ).fetchall()
            return [_row_to_user(r) for r in rows]

    def update_user(
        self,
        user_id: str,
        *,
        password_hash: Optional[str] = None,
        is_approved: Optional[bool] = None,
        role: Optional[UserRole] = None,
        is_active: Optional[bool] = None,
        email: Optional[str] = None,
    ) -> Optional[User]:
        self.init()
        fields: list = []
        params: list = []
        if password_hash is not None:
            fields.append("password_hash = ?")
            params.append(password_hash)
        if is_approved is not None:
            fields.append("is_approved = ?")
            params.append(1 if is_approved else 0)
        if role is not None:
            fields.append("role = ?")
            params.append(role.value)
        if is_active is not None:
            fields.append("is_active = ?")
            params.append(1 if is_active else 0)
        if email is not None:
            fields.append("email = ?")
            params.append(email)
        if not fields:
            return self.get_user(user_id)

        params.append(user_id)
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                f"UPDATE users SET {', '.join(fields)} WHERE id = ?", params
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return _row_to_user(row) if row else None

    def delete_user(self, user_id: str) -> bool:
        self.init()
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
            return cur.rowcount > 0

    def touch_last_login(self, user_id: str) -> None:
        """Stamp ``last_login_at = CURRENT_TIMESTAMP`` for ``user_id``."""
        self.init()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?",
                (user_id,),
            )
            conn.commit()

    def count(self) -> int:
        """Number of users. Used to decide whether to bootstrap admin."""
        self.init()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
            return int(row["n"] if row else 0)

    # ------------------------------------------------------------------
    # Owner / visibility helpers (KB / document / chat)
    # ------------------------------------------------------------------

    def set_kb_owner(
        self, kb_id: str, owner_id: Optional[str]
    ) -> None:
        self.init()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE knowledge_bases SET owner_id = ? WHERE id = ?",
                (owner_id, kb_id),
            )
            conn.commit()

    def set_kb_visibility(self, kb_id: str, is_public: bool) -> None:
        self.init()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE knowledge_bases SET is_public = ? WHERE id = ?",
                (1 if is_public else 0, kb_id),
            )
            conn.commit()

    def get_kb_owner_and_visibility(
        self, kb_id: str
    ) -> Optional[tuple]:
        """Return ``(owner_id, is_public)`` for ``kb_id`` or None."""
        self.init()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT owner_id, is_public FROM knowledge_bases WHERE id = ?",
                (kb_id,),
            ).fetchone()
            if row is None:
                return None
            return (row["owner_id"], bool(row["is_public"]))

    def list_kbs_visible_to(self, user_id: str, is_admin: bool) -> List[str]:
        """Return kb_ids the user is allowed to see.

        Admins see all KBs; members see their own KBs plus
        ``is_public=True`` ones.
        """
        self.init()
        with self._lock, self._connect() as conn:
            if is_admin:
                rows = conn.execute(
                    "SELECT id FROM knowledge_bases ORDER BY created_at DESC, rowid DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id FROM knowledge_bases WHERE owner_id = ? OR is_public = 1 "
                    "ORDER BY created_at DESC, rowid DESC",
                    (user_id,),
                ).fetchall()
            return [r["id"] for r in rows]

    def set_document_owner(
        self, doc_id: str, owner_id: Optional[str]
    ) -> None:
        self.init()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE documents SET owner_id = ? WHERE id = ?",
                (owner_id, doc_id),
            )
            conn.commit()

    def set_chat_turn_user(self, turn_id: str, user_id: Optional[str]) -> None:
        self.init()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE chat_turns SET user_id = ? WHERE id = ?",
                (user_id, turn_id),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Drop & recreate the auth tables. Test-only helper."""
        with self._lock, self._connect() as conn:
            conn.executescript("DROP TABLE IF EXISTS users;")
            conn.commit()
            self._initialized = False
        self.init()


__all__ = ["UserStore"]
