"""SQLite-backed metadata storage for KBs and documents.

Schema mirrors ``openspec/spec.md`` §4.1. All public methods are
synchronous; callers wrap them in threads / asyncio tasks when needed.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional

from app.config import Settings
from app.kb.models import (
    ChatTurn,
    ChunkMeta,
    Citation,
    Document,
    DocumentStatus,
    KnowledgeBase,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------


CREATE_KB_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT DEFAULT '',
    owner_id     TEXT,
    is_public    INTEGER DEFAULT 0,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    doc_count    INTEGER DEFAULT 0,
    chunk_count  INTEGER DEFAULT 0
);
"""

CREATE_DOC_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    id           TEXT PRIMARY KEY,
    kb_id        TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    ext          TEXT NOT NULL,
    size_bytes   INTEGER NOT NULL,
    storage_path TEXT NOT NULL,
    status       TEXT NOT NULL,
    error        TEXT DEFAULT '',
    chunk_count  INTEGER DEFAULT 0,
    owner_id     TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);
"""

CREATE_CHAT_TURN_SQL = """
CREATE TABLE IF NOT EXISTS chat_turns (
    id              TEXT PRIMARY KEY,
    kb_id           TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    question        TEXT NOT NULL,
    answer          TEXT NOT NULL DEFAULT '',
    error           TEXT DEFAULT '',
    citations_json  TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'ready',
    user_id         TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    latency_ms      INTEGER DEFAULT 0
);
"""

CREATE_CHUNK_SQL = """
CREATE TABLE IF NOT EXISTS chunks (
    id              TEXT PRIMARY KEY,
    doc_id          TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    kb_id           TEXT NOT NULL,
    chunk_idx       INTEGER NOT NULL,
    content         TEXT NOT NULL,
    char_count      INTEGER NOT NULL,
    token_estimate  INTEGER DEFAULT 0,
    start_offset    INTEGER DEFAULT 0,
    end_offset      INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(doc_id, chunk_idx)
);
"""

CREATE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_documents_kb ON documents(kb_id);\n"
    "CREATE INDEX IF NOT EXISTS idx_chat_turns_kb_time "
    "ON chat_turns(kb_id, created_at DESC);\n"
    "CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);\n"
    "CREATE INDEX IF NOT EXISTS idx_chunks_kb ON chunks(kb_id);\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return uuid.uuid4().hex


def _row_to_kb(row: sqlite3.Row) -> KnowledgeBase:
    created_at = row["created_at"]
    if isinstance(created_at, str):
        # SQLite stores TIMESTAMP as a string; normalise to ISO format.
        try:
            created_at = datetime.fromisoformat(created_at)
        except ValueError:
            created_at = datetime.utcnow()
    return KnowledgeBase(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        created_at=created_at,
        doc_count=int(row["doc_count"] or 0),
        chunk_count=int(row["chunk_count"] or 0),
        owner_id=row["owner_id"],
        is_public=bool(row["is_public"] or 0),
    )


def _row_to_doc(row: sqlite3.Row) -> Document:
    created_at = row["created_at"]
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at)
        except ValueError:
            created_at = datetime.utcnow()
    processed_at = row["processed_at"]
    if isinstance(processed_at, str):
        try:
            processed_at = datetime.fromisoformat(processed_at)
        except ValueError:
            processed_at = None
    return Document(
        id=row["id"],
        kb_id=row["kb_id"],
        filename=row["filename"],
        ext=row["ext"],
        size_bytes=int(row["size_bytes"] or 0),
        storage_path=row["storage_path"],
        status=DocumentStatus(row["status"]),
        error=row["error"] or "",
        chunk_count=int(row["chunk_count"] or 0),
        created_at=created_at,
        processed_at=processed_at,
    )


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


def _row_to_chat_turn(row: sqlite3.Row) -> ChatTurn:
    citations_raw = row["citations_json"] or "[]"
    try:
        citations_data = json.loads(citations_raw)
    except json.JSONDecodeError:
        citations_data = []
    citations = [Citation(**c) for c in citations_data if isinstance(c, dict)]
    return ChatTurn(
        id=row["id"],
        kb_id=row["kb_id"],
        question=row["question"],
        answer=row["answer"] or "",
        error=row["error"] or "",
        citations=citations,
        status=row["status"],
        user_id=row["user_id"],
        created_at=_parse_dt(row["created_at"]),
        latency_ms=int(row["latency_ms"] or 0),
    )


def _row_to_chunk(row: sqlite3.Row) -> ChunkMeta:
    return ChunkMeta(
        id=row["id"],
        doc_id=row["doc_id"],
        kb_id=row["kb_id"],
        chunk_idx=int(row["chunk_idx"]),
        content=row["content"],
        char_count=int(row["char_count"] or 0),
        token_estimate=int(row["token_estimate"] or 0),
        start_offset=int(row["start_offset"] or 0),
        end_offset=int(row["end_offset"] or 0),
        created_at=_parse_dt(row["created_at"]),
    )


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class SQLiteStorage:
    """Thread-safe SQLite metadata store."""

    def __init__(self, settings: Settings, db_path: Optional[Path] = None) -> None:
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
        """Create tables / indices if they don't exist (idempotent)."""
        with self._lock:
            if self._initialized:
                return
            with self._connect() as conn:
                conn.executescript(
                    CREATE_KB_SQL
                    + CREATE_DOC_SQL
                    + CREATE_CHAT_TURN_SQL
                    + CREATE_CHUNK_SQL
                    + CREATE_INDEX_SQL
                )
                self._ensure_auth_columns(conn)
                conn.commit()
            self._initialized = True

    def _ensure_auth_columns(self, conn: sqlite3.Connection) -> None:
        """Add owner / visibility / user_id columns to legacy tables.

        ``CREATE TABLE IF NOT EXISTS`` is a no-op when the table already
        exists, so DBs provisioned before the auth module shipped would
        miss the new columns. ``PRAGMA table_info`` lets us detect this
        and patch in the missing columns. Safe to re-run.
        """
        existing_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "knowledge_bases" in existing_tables:
            cols = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(knowledge_bases)"
                ).fetchall()
            }
            if "owner_id" not in cols:
                conn.execute("ALTER TABLE knowledge_bases ADD COLUMN owner_id TEXT")
            if "is_public" not in cols:
                conn.execute(
                    "ALTER TABLE knowledge_bases ADD COLUMN is_public INTEGER DEFAULT 0"
                )
        if "documents" in existing_tables:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(documents)").fetchall()
            }
            if "owner_id" not in cols:
                conn.execute("ALTER TABLE documents ADD COLUMN owner_id TEXT")
        if "chat_turns" in existing_tables:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(chat_turns)").fetchall()
            }
            if "user_id" not in cols:
                conn.execute("ALTER TABLE chat_turns ADD COLUMN user_id TEXT")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # ``check_same_thread=False`` because the service layer may dispatch
        # background work via asyncio.to_thread; we serialise writes with a lock.
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Knowledge bases
    # ------------------------------------------------------------------

    def create_kb(self, name: str, description: str = "") -> KnowledgeBase:
        self.init()
        with self._lock, self._connect() as conn:
            kb_id = _new_id()
            try:
                conn.execute(
                    "INSERT INTO knowledge_bases (id, name, description) VALUES (?, ?, ?)",
                    (kb_id, name, description or ""),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"knowledge base name already exists: {name}") from exc
            row = conn.execute(
                "SELECT * FROM knowledge_bases WHERE id = ?", (kb_id,)
            ).fetchone()
            return _row_to_kb(row)

    def list_kbs(self) -> List[KnowledgeBase]:
        self.init()
        with self._lock, self._connect() as conn:
            # ``rowid`` is a monotonically increasing implicit primary key
            # so it's a stable tiebreaker when ``created_at`` timestamps
            # collide (rows inserted in the same second).
            rows = conn.execute(
                "SELECT * FROM knowledge_bases ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
            return [_row_to_kb(r) for r in rows]

    def get_kb(self, kb_id: str) -> Optional[KnowledgeBase]:
        self.init()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_bases WHERE id = ?", (kb_id,)
            ).fetchone()
            return _row_to_kb(row) if row else None

    def update_kb(
        self,
        kb_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[KnowledgeBase]:
        self.init()
        if name is None and description is None:
            return self.get_kb(kb_id)

        fields = []
        params: list = []
        if name is not None:
            fields.append("name = ?")
            params.append(name)
        if description is not None:
            fields.append("description = ?")
            params.append(description)
        params.append(kb_id)

        with self._lock, self._connect() as conn:
            try:
                cur = conn.execute(
                    f"UPDATE knowledge_bases SET {', '.join(fields)} WHERE id = ?",
                    params,
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"knowledge base name already exists: {name}") from exc
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM knowledge_bases WHERE id = ?", (kb_id,)
            ).fetchone()
            return _row_to_kb(row)

    def delete_kb(self, kb_id: str) -> bool:
        self.init()
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM knowledge_bases WHERE id = ?", (kb_id,))
            conn.commit()
            return cur.rowcount > 0

    def adjust_kb_counts(
        self, kb_id: str, doc_delta: int = 0, chunk_delta: int = 0
    ) -> None:
        """Atomically increment / decrement counters on the KB row."""
        self.init()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE knowledge_bases SET doc_count = doc_count + ?, "
                "chunk_count = chunk_count + ? WHERE id = ?",
                (doc_delta, chunk_delta, kb_id),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def create_document(
        self,
        kb_id: str,
        filename: str,
        ext: str,
        size_bytes: int,
        storage_path: str,
        status: DocumentStatus = DocumentStatus.PENDING,
    ) -> Document:
        self.init()
        doc_id = _new_id()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO documents (id, kb_id, filename, ext, size_bytes, "
                "storage_path, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    doc_id,
                    kb_id,
                    filename,
                    ext,
                    int(size_bytes),
                    storage_path,
                    status.value,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            return _row_to_doc(row)

    def list_documents(self, kb_id: str) -> List[Document]:
        self.init()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM documents WHERE kb_id = ? ORDER BY created_at DESC",
                (kb_id,),
            ).fetchall()
            return [_row_to_doc(r) for r in rows]

    def get_document(self, doc_id: str) -> Optional[Document]:
        self.init()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            return _row_to_doc(row) if row else None

    def update_document_status(
        self,
        doc_id: str,
        status: DocumentStatus,
        error: str = "",
        chunk_count: Optional[int] = None,
    ) -> Optional[Document]:
        self.init()
        with self._lock, self._connect() as conn:
            sets = ["status = ?", "error = ?"]
            params: list = [status.value, error or ""]
            if chunk_count is not None:
                sets.append("chunk_count = ?")
                params.append(int(chunk_count))
            if status == DocumentStatus.READY:
                sets.append("processed_at = CURRENT_TIMESTAMP")
            params.append(doc_id)
            cur = conn.execute(
                f"UPDATE documents SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            return _row_to_doc(row)

    def delete_document(self, doc_id: str) -> bool:
        self.init()
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
            conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Chat turns (Q&A history)
    # ------------------------------------------------------------------

    def save_chat_turn(self, turn: ChatTurn) -> ChatTurn:
        """Persist a chat turn. Caller is expected to have set ``turn.id``."""
        self.init()
        citations_json = json.dumps(
            [c.model_dump() for c in turn.citations], ensure_ascii=False
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO chat_turns "
                "(id, kb_id, question, answer, error, citations_json, status, "
                " latency_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    turn.id,
                    turn.kb_id,
                    turn.question,
                    turn.answer,
                    turn.error or "",
                    citations_json,
                    turn.status,
                    int(turn.latency_ms or 0),
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM chat_turns WHERE id = ?", (turn.id,)
            ).fetchone()
            return _row_to_chat_turn(row)

    def list_chat_turns(self, kb_id: str, limit: int = 50) -> List[ChatTurn]:
        """List chat turns for a KB, newest first.

        ``limit`` is clamped to ``[1, 500]`` to prevent pathological
        queries from a buggy client.
        """
        self.init()
        lim = max(1, min(int(limit or 50), 500))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_turns WHERE kb_id = ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (kb_id, lim),
            ).fetchall()
            return [_row_to_chat_turn(r) for r in rows]

    def get_chat_turn(self, kb_id: str, turn_id: str) -> Optional[ChatTurn]:
        self.init()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chat_turns WHERE id = ? AND kb_id = ?",
                (turn_id, kb_id),
            ).fetchone()
            return _row_to_chat_turn(row) if row else None

    def delete_chat_turn(self, kb_id: str, turn_id: str) -> bool:
        self.init()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM chat_turns WHERE id = ? AND kb_id = ?",
                (turn_id, kb_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def clear_chat_turns(self, kb_id: str) -> int:
        """Delete every chat turn belonging to ``kb_id``.

        Returns the number of rows removed.
        """
        self.init()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM chat_turns WHERE kb_id = ?", (kb_id,)
            )
            conn.commit()
            return int(cur.rowcount or 0)

    # ------------------------------------------------------------------
    # Chunks (chunk-level metadata mirror)
    # ------------------------------------------------------------------

    def save_chunks_batch(self, chunks: List[ChunkMeta]) -> int:
        """Upsert a batch of chunk metadata rows.

        Uses ``INSERT OR REPLACE`` so re-indexing the same document
        overwrites the old chunk rows atomically. Returns the count
        inserted.
        """
        if not chunks:
            return 0
        self.init()
        rows = [
            (
                c.id,
                c.doc_id,
                c.kb_id,
                int(c.chunk_idx),
                c.content,
                int(c.char_count),
                int(c.token_estimate or 0),
                int(c.start_offset or 0),
                int(c.end_offset or 0),
            )
            for c in chunks
        ]
        with self._lock, self._connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO chunks "
                "(id, doc_id, kb_id, chunk_idx, content, char_count, "
                " token_estimate, start_offset, end_offset) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
            return len(rows)

    def delete_chunks_for_doc(self, doc_id: str) -> int:
        """Drop all chunk rows for ``doc_id``. Returns rows removed."""
        self.init()
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            conn.commit()
            return int(cur.rowcount or 0)

    def list_chunks_for_doc(
        self, doc_id: str, limit: int = 100, offset: int = 0
    ) -> List[ChunkMeta]:
        """List chunk metadata for a document, ordered by ``chunk_idx``."""
        self.init()
        lim = max(1, min(int(limit or 100), 1000))
        off = max(0, int(offset or 0))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chunks WHERE doc_id = ? "
                "ORDER BY chunk_idx ASC LIMIT ? OFFSET ?",
                (doc_id, lim, off),
            ).fetchall()
            return [_row_to_chunk(r) for r in rows]

    def get_chunk(self, chunk_id: str) -> Optional[ChunkMeta]:
        self.init()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chunks WHERE id = ?", (chunk_id,)
            ).fetchone()
            return _row_to_chunk(row) if row else None

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Drop & recreate tables. Test-only helper."""
        with self._lock, self._connect() as conn:
            conn.executescript(
                "DROP TABLE IF EXISTS chat_turns;\n"
                "DROP TABLE IF EXISTS chunks;\n"
                "DROP TABLE IF EXISTS documents;\n"
                "DROP TABLE IF EXISTS knowledge_bases;\n"
            )
            conn.commit()
            self._initialized = False
        self.init()

    def close(self) -> None:
        """No-op kept for API parity with future pooled backends."""
        return None


# ---------------------------------------------------------------------------
# Data migration helpers (idempotent; safe to call on every startup)
# ---------------------------------------------------------------------------


def recompute_kb_counts(storage: SQLiteStorage) -> int:
    """Recompute ``doc_count`` and ``chunk_count`` from the documents table.

    Counter drift can happen when ``adjust_kb_counts`` is called
    with the wrong sign or on the wrong KB, or when the storage was
    migrated from an older build that didn't track counts at all.
    Running this on startup is the canonical "make the counters
    honest again" pass.

    Idempotent: rewriting a count to the same value is a no-op.
    Returns the number of KB rows touched.
    """
    with storage._lock, storage._connect() as conn:  # type: ignore[attr-defined]
        cur = conn.execute(
            """
            UPDATE knowledge_bases SET
                doc_count = (
                    SELECT COUNT(*) FROM documents
                    WHERE documents.kb_id = knowledge_bases.id
                ),
                chunk_count = (
                    SELECT COALESCE(SUM(chunk_count), 0) FROM documents
                    WHERE documents.kb_id = knowledge_bases.id
                )
            """
        )
        conn.commit()
        return int(cur.rowcount or 0)


def assign_orphan_kbs_to_admin(
    storage: SQLiteStorage, admin_user_id: str
) -> int:
    """Migrate KBs with ``owner_id IS NULL`` to ``admin_user_id``.

    Knowledge bases created before the auth module shipped (or in
    the data-layer spec before ownership wiring) end up with no
    owner, which breaks the per-user visibility filter. Re-stamp
    them to the bootstrap admin so the rest of the system can
    resolve them.

    Idempotent: rows that already have an owner are left alone.
    Returns the number of KB rows updated.
    """
    with storage._lock, storage._connect() as conn:  # type: ignore[attr-defined]
        cur = conn.execute(
            "UPDATE knowledge_bases SET owner_id = ? "
            "WHERE owner_id IS NULL",
            (admin_user_id,),
        )
        conn.commit()
        return int(cur.rowcount or 0)


def assign_orphan_chats_to_admin(
    storage: SQLiteStorage, admin_user_id: str
) -> int:
    """Migrate chat_turns with ``user_id IS NULL`` to ``admin_user_id``.

    Same rationale as :func:`assign_orphan_kbs_to_admin`: turns
    captured before auth shipped (or before the chat layer wired
    the authenticated user through) have no user stamp, which
    blocks the per-user chat-history view.

    Idempotent. Returns the number of chat_turn rows updated.
    """
    with storage._lock, storage._connect() as conn:  # type: ignore[attr-defined]
        cur = conn.execute(
            "UPDATE chat_turns SET user_id = ? "
            "WHERE user_id IS NULL",
            (admin_user_id,),
        )
        conn.commit()
        return int(cur.rowcount or 0)


__all__ = [
    "SQLiteStorage",
    "recompute_kb_counts",
    "assign_orphan_kbs_to_admin",
    "assign_orphan_chats_to_admin",
]
