"""Tests for the ``recompute_kb_counts`` migration helper.

The helper is the canonical "make the counters honest again" pass for
KB rows whose ``doc_count`` / ``chunk_count`` drifted from reality.
Running it on startup is the safety net that keeps the UI counts in
sync with the underlying documents table.
"""

from __future__ import annotations

import pytest

from app.kb.models import DocumentStatus
from app.kb.storage import SQLiteStorage, recompute_kb_counts


def _add_doc(
    storage: SQLiteStorage, kb_id: str, chunk_count: int = 0
) -> str:
    """Insert a document row directly so we can stage counter drift
    without driving the full ingest pipeline."""
    doc = storage.create_document(
        kb_id=kb_id,
        filename="x.txt",
        ext=".txt",
        size_bytes=10,
        storage_path="/tmp/x.txt",
        status=DocumentStatus.READY,
    )
    if chunk_count:
        storage.update_document_status(
            doc.id, DocumentStatus.READY, chunk_count=chunk_count
        )
    return doc.id


def test_recompute_fixes_negative_drift(sqlite_storage: SQLiteStorage) -> None:
    """A KB whose doc_count has drifted negative is restored to the truth.

    Reproduces the production bug the spec was written to fix: counter
    adjustment with the wrong sign left ``doc_count = -2`` even though
    2 real documents existed.
    """
    kb = sqlite_storage.create_kb(name="drifted")
    # Stage 2 real documents, then poke the counter to -2 (the bug
    # the spec was written to fix). Two increments of 0 from
    # ``create_document`` keep the starting point at 0; the explicit
    # ``-2`` reproduces the observed drift.
    _add_doc(sqlite_storage, kb.id, chunk_count=3)
    _add_doc(sqlite_storage, kb.id, chunk_count=4)
    sqlite_storage.adjust_kb_counts(kb.id, doc_delta=-2, chunk_delta=-7)
    before = sqlite_storage.get_kb(kb.id)
    assert before is not None
    assert before.doc_count == -2
    # chunk_count drifts the same way: real total is 7, drifted to -7.
    assert before.chunk_count == -7

    fixed = recompute_kb_counts(sqlite_storage)
    assert fixed >= 1

    after = sqlite_storage.get_kb(kb.id)
    assert after is not None
    assert after.doc_count == 2
    assert after.chunk_count == 7


def test_recompute_handles_multiple_kbs(sqlite_storage: SQLiteStorage) -> None:
    """All KBs are recomputed in a single pass; counts match documents."""
    a = sqlite_storage.create_kb(name="ka")
    b = sqlite_storage.create_kb(name="kb")
    _add_doc(sqlite_storage, a.id, chunk_count=5)
    _add_doc(sqlite_storage, a.id, chunk_count=2)
    _add_doc(sqlite_storage, b.id, chunk_count=1)
    # Stage arbitrary drift on both KBs.
    sqlite_storage.adjust_kb_counts(a.id, doc_delta=100, chunk_delta=100)
    sqlite_storage.adjust_kb_counts(b.id, doc_delta=-50, chunk_delta=-50)

    recompute_kb_counts(sqlite_storage)

    assert sqlite_storage.get_kb(a.id).doc_count == 2
    assert sqlite_storage.get_kb(a.id).chunk_count == 7
    assert sqlite_storage.get_kb(b.id).doc_count == 1
    assert sqlite_storage.get_kb(b.id).chunk_count == 1


def test_recompute_handles_empty_kb(sqlite_storage: SQLiteStorage) -> None:
    """A KB with no documents settles to (0, 0) even after drift."""
    kb = sqlite_storage.create_kb(name="empty")
    sqlite_storage.adjust_kb_counts(kb.id, doc_delta=10, chunk_delta=99)

    recompute_kb_counts(sqlite_storage)

    after = sqlite_storage.get_kb(kb.id)
    assert after is not None
    assert after.doc_count == 0
    assert after.chunk_count == 0


def test_recompute_is_idempotent(sqlite_storage: SQLiteStorage) -> None:
    """Running the migration twice is a safe no-op the second time."""
    kb = sqlite_storage.create_kb(name="idem")
    _add_doc(sqlite_storage, kb.id, chunk_count=4)
    sqlite_storage.adjust_kb_counts(kb.id, doc_delta=1, chunk_delta=1)

    recompute_kb_counts(sqlite_storage)
    first = sqlite_storage.get_kb(kb.id)

    recompute_kb_counts(sqlite_storage)
    second = sqlite_storage.get_kb(kb.id)

    assert first is not None and second is not None
    assert first.doc_count == second.doc_count == 1
    assert first.chunk_count == second.chunk_count == 4


def test_recompute_uses_sums_when_some_chunks_zero(
    sqlite_storage: SQLiteStorage,
) -> None:
    """Documents with chunk_count=0 contribute 0, not null, to the sum."""
    kb = sqlite_storage.create_kb(name="mix")
    _add_doc(sqlite_storage, kb.id, chunk_count=0)  # PENDING-like
    _add_doc(sqlite_storage, kb.id, chunk_count=6)
    # Force the COALESCE path: poke chunk_count to NULL via a manual
    # SQL update, which mirrors what older builds could leave behind.
    with sqlite_storage._connect() as conn:  # type: ignore[attr-defined]
        conn.execute(
            "UPDATE documents SET chunk_count = NULL WHERE chunk_count = 0"
        )
        conn.commit()

    recompute_kb_counts(sqlite_storage)

    after = sqlite_storage.get_kb(kb.id)
    assert after is not None
    assert after.doc_count == 2
    assert after.chunk_count == 6
