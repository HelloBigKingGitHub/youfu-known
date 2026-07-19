"""Tests for chunk-metadata persistence + retrieval endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.jobs.ingest import run_ingest
from app.kb.models import ChunkMeta


# ---------------------------------------------------------------------------
# Storage-level tests
# ---------------------------------------------------------------------------


def _chunk(doc_id: str, kb_id: str, idx: int, text: str) -> ChunkMeta:
    return ChunkMeta(
        id=f"{doc_id}::{idx}",
        doc_id=doc_id,
        kb_id=kb_id,
        chunk_idx=idx,
        content=text,
        char_count=len(text),
        token_estimate=max(1, len(text) // 4),
        start_offset=idx * 100,
        end_offset=idx * 100 + len(text),
        created_at=datetime.utcnow(),
    )


def test_save_and_list_chunks(sqlite_storage):
    kb = sqlite_storage.create_kb(name="kb")
    doc = sqlite_storage.create_document(
        kb_id=kb.id,
        filename="a.txt",
        ext=".txt",
        size_bytes=10,
        storage_path="/tmp/a",
    )
    chunks = [
        _chunk(doc.id, kb.id, 0, "first"),
        _chunk(doc.id, kb.id, 1, "second"),
        _chunk(doc.id, kb.id, 2, "third"),
    ]
    sqlite_storage.save_chunks_batch(chunks)
    listed = sqlite_storage.list_chunks_for_doc(doc.id)
    assert [c.chunk_idx for c in listed] == [0, 1, 2]
    assert listed[1].content == "second"


def test_save_chunks_batch_is_idempotent(sqlite_storage):
    """Re-indexing the same doc should overwrite (INSERT OR REPLACE)."""
    kb = sqlite_storage.create_kb(name="kb")
    doc = sqlite_storage.create_document(
        kb_id=kb.id,
        filename="a.txt",
        ext=".txt",
        size_bytes=10,
        storage_path="/tmp/a",
    )
    sqlite_storage.save_chunks_batch([_chunk(doc.id, kb.id, 0, "v1")])
    sqlite_storage.save_chunks_batch([_chunk(doc.id, kb.id, 0, "v2-updated")])
    listed = sqlite_storage.list_chunks_for_doc(doc.id)
    assert len(listed) == 1
    assert listed[0].content == "v2-updated"


def test_list_chunks_pagination(sqlite_storage):
    kb = sqlite_storage.create_kb(name="kb")
    doc = sqlite_storage.create_document(
        kb_id=kb.id,
        filename="a.txt",
        ext=".txt",
        size_bytes=10,
        storage_path="/tmp/a",
    )
    sqlite_storage.save_chunks_batch(
        [_chunk(doc.id, kb.id, i, f"c{i}") for i in range(10)]
    )
    page = sqlite_storage.list_chunks_for_doc(doc.id, limit=3, offset=0)
    assert [c.chunk_idx for c in page] == [0, 1, 2]
    page2 = sqlite_storage.list_chunks_for_doc(doc.id, limit=3, offset=3)
    assert [c.chunk_idx for c in page2] == [3, 4, 5]


def test_get_chunk(sqlite_storage):
    kb = sqlite_storage.create_kb(name="kb")
    doc = sqlite_storage.create_document(
        kb_id=kb.id,
        filename="a.txt",
        ext=".txt",
        size_bytes=10,
        storage_path="/tmp/a",
    )
    sqlite_storage.save_chunks_batch([_chunk(doc.id, kb.id, 7, "hello world")])
    c = sqlite_storage.get_chunk(f"{doc.id}::7")
    assert c is not None
    assert c.content == "hello world"


def test_delete_chunks_for_doc(sqlite_storage):
    kb = sqlite_storage.create_kb(name="kb")
    doc = sqlite_storage.create_document(
        kb_id=kb.id,
        filename="a.txt",
        ext=".txt",
        size_bytes=10,
        storage_path="/tmp/a",
    )
    sqlite_storage.save_chunks_batch(
        [_chunk(doc.id, kb.id, i, f"c{i}") for i in range(3)]
    )
    removed = sqlite_storage.delete_chunks_for_doc(doc.id)
    assert removed == 3
    assert sqlite_storage.list_chunks_for_doc(doc.id) == []


def test_delete_document_cascades_chunks(sqlite_storage):
    """CASCADE on the FK drops chunks when the parent doc row goes."""
    kb = sqlite_storage.create_kb(name="kb")
    doc = sqlite_storage.create_document(
        kb_id=kb.id,
        filename="a.txt",
        ext=".txt",
        size_bytes=10,
        storage_path="/tmp/a",
    )
    sqlite_storage.save_chunks_batch(
        [_chunk(doc.id, kb.id, i, f"c{i}") for i in range(3)]
    )
    sqlite_storage.delete_document(doc.id)
    assert sqlite_storage.list_chunks_for_doc(doc.id) == []


# ---------------------------------------------------------------------------
# KBService ingest -> dual-write integration
# ---------------------------------------------------------------------------


def test_ingest_writes_chunks_to_sqlite(
    kb_service, sqlite_storage, sample_txt
):
    kb = kb_service.create_kb(name="kb")
    uploaded = kb_service.upload_document(
        kb_id=kb.id,
        filename=sample_txt.name,
        ext=".txt",
        content=sample_txt.read_bytes(),
    )
    doc = kb_service.ingest_document(kb.id, uploaded.doc_id)
    assert doc.chunk_count > 0

    rows = sqlite_storage.list_chunks_for_doc(doc.id)
    assert len(rows) == doc.chunk_count
    # IDs match Chroma convention
    assert rows[0].id == f"{doc.id}::0"
    assert rows[0].kb_id == kb.id
    assert rows[0].char_count > 0


def test_re_ingest_replaces_chunks(kb_service, sqlite_storage, sample_txt):
    """Re-ingest replaces chunks in place (INSERT OR REPLACE)."""
    kb = kb_service.create_kb(name="kb")
    uploaded = kb_service.upload_document(
        kb_id=kb.id,
        filename=sample_txt.name,
        ext=".txt",
        content=sample_txt.read_bytes(),
    )
    doc = kb_service.ingest_document(kb.id, uploaded.doc_id)
    before = sqlite_storage.list_chunks_for_doc(doc.id)
    assert before

    # Re-ingest the same doc. Idempotency: chunk count stays the same.
    doc2 = kb_service.ingest_document(kb.id, uploaded.doc_id)
    after = sqlite_storage.list_chunks_for_doc(doc.id)
    assert len(after) == len(before) == doc2.chunk_count


# ---------------------------------------------------------------------------
# API-level tests
# ---------------------------------------------------------------------------


def _create_kb_and_doc(client: TestClient, sample_txt, *, name: str):
    kb_id = client.post("/api/kbs", json={"name": name}).json()["data"]["id"]
    with sample_txt.open("rb") as f:
        r = client.post(
            f"/api/kbs/{kb_id}/documents",
            files=[("files", ("a.txt", f, "text/plain"))],
        )
    assert r.status_code == 201
    doc_id = r.json()["data"]["uploaded"][0]["doc_id"]
    asyncio.run(run_ingest(client.app, kb_id, doc_id))
    return kb_id, doc_id


def test_list_chunks_endpoint(
    client: TestClient, mock_embedder, sample_txt
):
    kb_id, doc_id = _create_kb_and_doc(client, sample_txt, name="chunks-list-api")
    r = client.get(f"/api/kbs/{kb_id}/documents/{doc_id}/chunks")
    assert r.status_code == 200
    rows = r.json()["data"]
    assert rows
    assert rows[0]["chunk_idx"] == 0
    assert rows[0]["doc_id"] == doc_id
    assert rows[0]["kb_id"] == kb_id
    assert rows[0]["content"]


def test_get_single_chunk_endpoint(
    client: TestClient, mock_embedder, sample_txt
):
    kb_id, doc_id = _create_kb_and_doc(client, sample_txt, name="chunks-detail-api")
    r = client.get(f"/api/kbs/{kb_id}/documents/{doc_id}/chunks")
    assert r.status_code == 200
    chunk_id = r.json()["data"][0]["id"]

    detail = client.get(f"/api/kbs/{kb_id}/documents/{doc_id}/chunks/{chunk_id}")
    assert detail.status_code == 200
    body = detail.json()["data"]
    assert body["id"] == chunk_id
    assert body["content"]


def test_chunks_endpoint_404_on_unknown_doc(client: TestClient):
    kb_id = client.post(
        "/api/kbs", json={"name": "chunks-404-unique"}
    ).json()["data"]["id"]
    r = client.get(f"/api/kbs/{kb_id}/documents/no-such-doc/chunks")
    assert r.status_code == 404


def test_chunks_endpoint_404_on_wrong_kb(
    client: TestClient, mock_embedder, sample_txt
):
    """A doc_id from one KB must not be reachable via another KB."""
    kb_a, doc_a = _create_kb_and_doc(client, sample_txt, name="chunks-wrong-kb-a")
    kb_b = client.post(
        "/api/kbs", json={"name": "chunks-wrong-kb-b"}
    ).json()["data"]["id"]
    r = client.get(f"/api/kbs/{kb_b}/documents/{doc_a}/chunks")
    assert r.status_code == 404


def test_chat_response_includes_chunk_id(
    client: TestClient, mock_retriever, mock_embedder
):
    """End-to-end: chat response carries chunk_id on each citation."""
    kb_id = client.post(
        "/api/kbs", json={"name": "chunk-id-cite"}
    ).json()["data"]["id"]
    r = client.post(f"/api/kbs/{kb_id}/chat", json={"question": "x"})
    assert r.status_code == 200
    citations = r.json()["data"]["citations"]
    assert citations
    for c in citations:
        assert c["chunk_id"]
        assert c["chunk_id"] == f"{c['doc_id']}::{c['chunk_idx']}"