"""End-to-end tests for KBService (no LLM/Embedding network calls)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.kb.models import DocumentStatus
from app.kb.service import (
    DocumentNotFoundError,
    FileTooLargeError,
    KBNotFoundError,
    KBService,
)
from app.kb.storage import SQLiteStorage
from app.rag.embedder import Embedder
from app.rag.vectorstore import VectorStore


# NOTE: ``kb_service`` is defined in conftest.py.


def test_create_kb_creates_chroma_collection(
    kb_service: KBService, vectorstore: VectorStore
) -> None:
    kb = kb_service.create_kb(name="工作笔记", description="hi")
    assert kb.id
    assert kb.doc_count == 0
    col = vectorstore.get_collection(kb.id)
    assert col is not None
    assert col.name == f"kb_{kb.id}"


def test_create_kb_blank_name_raises(kb_service: KBService) -> None:
    with pytest.raises(ValueError):
        kb_service.create_kb(name="")


def test_list_and_detail(kb_service: KBService) -> None:
    kb_service.create_kb(name="a")
    kb_service.create_kb(name="b")
    out = kb_service.list_kbs()
    assert {k.name for k in out} == {"a", "b"}
    first = out[0]
    detail = kb_service.get_kb_detail(first.id)
    assert detail.kb.id == first.id


def test_get_kb_detail_unknown_raises(kb_service: KBService) -> None:
    with pytest.raises(KBNotFoundError):
        kb_service.get_kb_detail("nope")


def test_rename_kb(kb_service: KBService) -> None:
    kb = kb_service.create_kb(name="orig")
    renamed = kb_service.rename_kb(kb.id, name="new", description="d2")
    assert renamed.name == "new"
    assert renamed.description == "d2"


def test_delete_kb_removes_files_and_collection(
    kb_service: KBService, vectorstore: VectorStore, settings
) -> None:
    kb = kb_service.create_kb(name="tbr")
    upload_dir = settings.upload_dir_abs() / kb.id
    assert upload_dir.is_dir()
    (upload_dir / "junk.txt").write_text("x")
    vectorstore.get_or_create(kb.id, dim=4)

    assert kb_service.delete_kb(kb.id)
    assert not upload_dir.exists()
    assert vectorstore.get_collection(kb.id) is None
    with pytest.raises(KBNotFoundError):
        kb_service.get_kb_detail(kb.id)


def test_upload_document_persists_file(
    kb_service: KBService, settings, sample_txt: Path
) -> None:
    kb = kb_service.create_kb(name="kb")
    content = sample_txt.read_bytes()
    uploaded = kb_service.upload_document(
        kb_id=kb.id,
        filename=sample_txt.name,
        ext=".txt",
        content=content,
    )
    assert uploaded.filename == sample_txt.name
    assert uploaded.status == DocumentStatus.PENDING
    saved = settings.upload_dir_abs() / kb.id / f"{uploaded.doc_id}.txt"
    assert saved.is_file()
    assert saved.read_bytes() == content


def test_upload_document_unknown_kb(kb_service: KBService) -> None:
    with pytest.raises(KBNotFoundError):
        kb_service.upload_document(
            kb_id="missing", filename="x.txt", ext=".txt", content=b"abc"
        )


def test_upload_document_bad_extension(kb_service: KBService) -> None:
    kb = kb_service.create_kb(name="kb")
    with pytest.raises(Exception):
        kb_service.upload_document(
            kb_id=kb.id, filename="x.bin", ext=".bin", content=b"x"
        )


def test_ingest_document_full_pipeline(
    kb_service: KBService, vectorstore: VectorStore, sample_txt: Path
) -> None:
    kb = kb_service.create_kb(name="kb")
    uploaded = kb_service.upload_document(
        kb_id=kb.id,
        filename=sample_txt.name,
        ext=".txt",
        content=sample_txt.read_bytes(),
    )

    doc = kb_service.ingest_document(kb.id, uploaded.doc_id)
    assert doc.status == DocumentStatus.READY
    assert doc.chunk_count > 0
    assert doc.processed_at is not None

    # KB counters reflect the ingest.
    detail = kb_service.get_kb_detail(kb.id)
    assert detail.kb.doc_count == 1
    assert detail.kb.chunk_count >= doc.chunk_count

    # Chroma has at least one chunk for the doc.
    col = vectorstore.get_collection(kb.id)
    assert col is not None
    assert col.count() >= doc.chunk_count


def test_ingest_document_unknown_doc(kb_service: KBService) -> None:
    kb = kb_service.create_kb(name="kb")
    with pytest.raises(DocumentNotFoundError):
        kb_service.ingest_document(kb.id, "missing-doc")


def test_ingest_document_failure_is_recorded(
    kb_service: KBService, settings, tmp_path: Path
) -> None:
    """An empty file should yield zero sections, marking the doc failed."""
    kb = kb_service.create_kb(name="kb")
    # Write an empty txt file via upload path.
    empty_path = tmp_path / "empty.txt"
    empty_path.write_text("", encoding="utf-8")
    uploaded = kb_service.upload_document(
        kb_id=kb.id,
        filename=empty_path.name,
        ext=".txt",
        content=empty_path.read_bytes(),
    )
    with pytest.raises(RuntimeError):
        kb_service.ingest_document(kb.id, uploaded.doc_id)

    refreshed = kb_service.get_document(kb.id, uploaded.doc_id)
    assert refreshed.status == DocumentStatus.FAILED
    assert refreshed.error


def test_delete_document_removes_chunks_and_file(
    kb_service: KBService, vectorstore: VectorStore, settings, sample_txt: Path
) -> None:
    kb = kb_service.create_kb(name="kb")
    uploaded = kb_service.upload_document(
        kb_id=kb.id,
        filename=sample_txt.name,
        ext=".txt",
        content=sample_txt.read_bytes(),
    )
    kb_service.ingest_document(kb.id, uploaded.doc_id)
    saved_path = settings.upload_dir_abs() / kb.id / f"{uploaded.doc_id}.txt"

    assert kb_service.delete_document(kb.id, uploaded.doc_id)
    assert not saved_path.exists()

    # Chunks gone from Chroma.
    res = vectorstore.query(kb.id, query_embedding=[0.0] * 16, top_k=5)
    assert all(
        r["metadata"].get("doc_id") != uploaded.doc_id for r in res
    )


def test_supported_extensions(kb_service: KBService) -> None:
    exts = kb_service.supported_extensions()
    assert ".pdf" in exts
    assert ".md" in exts