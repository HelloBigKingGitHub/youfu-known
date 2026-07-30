"""SQLite aggregate helpers for the Phase 1 admin dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

from app.auth.storage import UserStore
from app.kb.storage import SQLiteStorage

_DOCUMENT_STATUS_KEYS = ("ready", "processing", "failed")


def _table_columns(storage: SQLiteStorage, table: str) -> set[str]:
    with storage._connect() as conn:  # type: ignore[attr-defined]
        return {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }


def _visibility_expression(storage: SQLiteStorage) -> str:
    columns = _table_columns(storage, "knowledge_bases")
    if "is_shared" in columns and "is_public" in columns:
        return "COALESCE(is_shared, is_public, 0)"
    if "is_shared" in columns:
        return "COALESCE(is_shared, 0)"
    return "COALESCE(is_public, 0)"


def _cutoff(now: Optional[datetime] = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is not None:
        current = current.astimezone(timezone.utc).replace(tzinfo=None)
    return (current - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")


def _one(conn: Any, query: str, params: Iterable[Any] = ()) -> int:
    row = conn.execute(query, tuple(params)).fetchone()
    if row is None:
        return 0
    value = row[0]
    return int(value or 0)


def collect_dashboard_stats(
    storage: SQLiteStorage,
    user_store: UserStore,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Return the dashboard contract using authoritative SQLite counts."""
    storage.init()
    user_store.init()
    visibility = _visibility_expression(storage)
    cutoff = _cutoff(now)

    with storage._connect() as conn:  # type: ignore[attr-defined]
        kb_row = conn.execute(
            f"""
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN {visibility} = 1 THEN 1 ELSE 0 END), 0) AS shared
            FROM knowledge_bases
            """
        ).fetchone()
        kb_total = int((kb_row["total"] if kb_row else 0) or 0)
        kb_shared = int((kb_row["shared"] if kb_row else 0) or 0)

        doc_row = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN status = 'ready' THEN 1 ELSE 0 END), 0) AS ready,
                   COALESCE(SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END), 0) AS processing,
                   COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed
            FROM documents
            """
        ).fetchone()
        doc_total = int((doc_row["total"] if doc_row else 0) or 0)
        by_status = {
            key: int((doc_row[key] if doc_row else 0) or 0)
            for key in _DOCUMENT_STATUS_KEYS
        }
        chunks = _one(conn, "SELECT COUNT(*) FROM chunks")
        storage_bytes = _one(
            conn,
            "SELECT COALESCE(SUM(size_bytes), 0) FROM documents",
        )
        chat_turns_24h = _one(
            conn,
            "SELECT COUNT(*) FROM chat_turns WHERE created_at >= ?",
            (cutoff,),
        )
        uploaded_24h = _one(
            conn,
            "SELECT COUNT(*) FROM documents WHERE created_at >= ?",
            (cutoff,),
        )

    with user_store._connect() as conn:  # type: ignore[attr-defined]
        user_total = _one(conn, "SELECT COUNT(*) FROM users")
        approved = _one(
            conn,
            "SELECT COUNT(*) FROM users WHERE is_approved = 1",
        )

    return {
        "kbs": {
            "total": kb_total,
            "shared": kb_shared,
            "private": max(0, kb_total - kb_shared),
        },
        "users": {
            "total": user_total,
            "approved": approved,
            "pending": max(0, user_total - approved),
        },
        "documents": {
            "total": doc_total,
            "by_status": by_status,
        },
        "chunks": chunks,
        "chat_turns_24h": chat_turns_24h,
        "storage_bytes": storage_bytes,
        # Phase 1 has no separate LLM-call table; each persisted chat turn
        # represents one attempted LLM call.
        "llm_calls_24h": chat_turns_24h,
        "uploaded_24h": uploaded_24h,
    }


# Descriptive aliases keep the helper convenient for callers and tests.
get_dashboard_stats = collect_dashboard_stats
dashboard_stats = collect_dashboard_stats

__all__ = ["collect_dashboard_stats", "get_dashboard_stats", "dashboard_stats"]
