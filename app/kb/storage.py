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
from app.kb.models import Document, DocumentStatus, KnowledgeBase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------


CREATE_KB_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT DEFAULT '',
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
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);
"""

CREATE_INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_documents_kb ON documents(kb_id);"


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
                    CREATE_KB_SQL + CREATE_DOC_SQL + CREATE_INDEX_SQL
                )
                conn.commit()
            self._initialized = True

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
    # Misc
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Drop & recreate tables. Test-only helper."""
        with self._lock, self._connect() as conn:
            conn.executescript("DROP TABLE IF EXISTS documents; DROP TABLE IF EXISTS knowledge_bases;")
            conn.commit()
            self._initialized = False
        self.init()

    def close(self) -> None:
        """No-op kept for API parity with future pooled backends."""
        return None


__all__ = ["SQLiteStorage"]