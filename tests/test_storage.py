"""Tests for the SQLite metadata store."""

from __future__ import annotations

import pytest

from app.kb.models import DocumentStatus
from app.kb.storage import SQLiteStorage


def test_create_and_get_kb(sqlite_storage: SQLiteStorage) -> None:
    kb = sqlite_storage.create_kb(name="测试库", description="desc")
    assert kb.id
    assert kb.name == "测试库"
    fetched = sqlite_storage.get_kb(kb.id)
    assert fetched == kb


def test_create_kb_duplicate_name_raises(sqlite_storage: SQLiteStorage) -> None:
    sqlite_storage.create_kb(name="dup")
    with pytest.raises(ValueError):
        sqlite_storage.create_kb(name="dup")


def test_list_kbs_orders_by_created(sqlite_storage: SQLiteStorage) -> None:
    a = sqlite_storage.create_kb(name="aaa")
    b = sqlite_storage.create_kb(name="bbb")
    out = sqlite_storage.list_kbs()
    ids = [k.id for k in out]
    assert ids[0] == b.id
    assert ids[1] == a.id


def test_update_kb_rename(sqlite_storage: SQLiteStorage) -> None:
    kb = sqlite_storage.create_kb(name="old")
    new = sqlite_storage.update_kb(kb.id, name="new", description="d")
    assert new is not None
    assert new.name == "new"
    assert new.description == "d"


def test_delete_kb_cascades_documents(sqlite_storage: SQLiteStorage) -> None:
    kb = sqlite_storage.create_kb(name="kb1")
    doc = sqlite_storage.create_document(
        kb_id=kb.id,
        filename="a.txt",
        ext=".txt",
        size_bytes=10,
        storage_path="/tmp/a.txt",
    )
    assert sqlite_storage.delete_kb(kb.id)
    assert sqlite_storage.get_kb(kb.id) is None
    assert sqlite_storage.get_document(doc.id) is None


def test_create_and_update_document(sqlite_storage: SQLiteStorage) -> None:
    kb = sqlite_storage.create_kb(name="kb")
    doc = sqlite_storage.create_document(
        kb_id=kb.id,
        filename="a.pdf",
        ext=".pdf",
        size_bytes=42,
        storage_path="/tmp/a.pdf",
    )
    assert doc.status == DocumentStatus.PENDING
    updated = sqlite_storage.update_document_status(
        doc.id, DocumentStatus.READY, error="", chunk_count=7
    )
    assert updated is not None
    assert updated.status == DocumentStatus.READY
    assert updated.chunk_count == 7
    assert updated.processed_at is not None


def test_list_documents_for_kb(sqlite_storage: SQLiteStorage) -> None:
    kb = sqlite_storage.create_kb(name="kb")
    sqlite_storage.create_document(
        kb_id=kb.id, filename="a.txt", ext=".txt", size_bytes=1, storage_path="/tmp/a"
    )
    sqlite_storage.create_document(
        kb_id=kb.id, filename="b.md", ext=".md", size_bytes=1, storage_path="/tmp/b"
    )
    docs = sqlite_storage.list_documents(kb.id)
    assert len(docs) == 2
    assert {d.filename for d in docs} == {"a.txt", "b.md"}


def test_delete_document(sqlite_storage: SQLiteStorage) -> None:
    kb = sqlite_storage.create_kb(name="kb")
    doc = sqlite_storage.create_document(
        kb_id=kb.id, filename="a.txt", ext=".txt", size_bytes=1, storage_path="/tmp/a"
    )
    assert sqlite_storage.delete_document(doc.id)
    assert sqlite_storage.get_document(doc.id) is None


def test_adjust_kb_counts(sqlite_storage: SQLiteStorage) -> None:
    kb = sqlite_storage.create_kb(name="kb")
    sqlite_storage.adjust_kb_counts(kb.id, doc_delta=2, chunk_delta=10)
    after = sqlite_storage.get_kb(kb.id)
    assert after is not None
    assert after.doc_count == 2
    assert after.chunk_count == 10
    sqlite_storage.adjust_kb_counts(kb.id, doc_delta=-1, chunk_delta=-3)
    after = sqlite_storage.get_kb(kb.id)
    assert after.doc_count == 1
    assert after.chunk_count == 7