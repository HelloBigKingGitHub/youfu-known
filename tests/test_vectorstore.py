"""Tests for the VectorStore wrapper (real Chroma, tmp directory)."""

from __future__ import annotations

import uuid

import pytest

from app.rag.vectorstore import VectorStore


def _vec(seed: str, dim: int = 8) -> list[float]:
    import hashlib

    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return [((digest[i % len(digest)] / 255.0) - 0.5) * 2.0 for i in range(dim)]


def test_get_or_create_creates_collection(vectorstore: VectorStore) -> None:
    kb_id = uuid.uuid4().hex
    col = vectorstore.get_or_create(kb_id, dim=8)
    assert col.name == f"kb_{kb_id}"


def test_upsert_and_query_finds_nearest(vectorstore: VectorStore) -> None:
    kb_id = uuid.uuid4().hex
    dim = 8
    docs = [
        ("c1", "apple banana cherry"),
        ("c2", "orange grape"),
        ("c3", "spaceship launch trajectory"),
    ]
    embs = [_vec(s, dim) for _, s in docs]
    metadatas = [
        {"doc_id": "docA", "doc_filename": "a.txt", "chunk_idx": i, "chunk_total": 3}
        for i, (cid, _) in enumerate(docs)
    ]
    ids = [cid for cid, _ in docs]
    documents = [t for _, t in docs]

    vectorstore.upsert(
        kb_id,
        ids=ids,
        embeddings=embs,
        documents=documents,
        metadatas=metadatas,
    )

    res = vectorstore.query(kb_id, query_embedding=_vec("apple banana", dim), top_k=3)
    assert len(res) == 3
    # Nearest should be c1 (closest text to query).
    assert res[0]["id"] == "c1"
    assert res[0]["metadata"]["doc_filename"] == "a.txt"


def test_query_empty_collection_returns_empty(vectorstore: VectorStore) -> None:
    kb_id = uuid.uuid4().hex
    res = vectorstore.query(kb_id, query_embedding=_vec("x", 8), top_k=3)
    assert res == []


def test_delete_by_doc_removes_only_target_chunks(vectorstore: VectorStore) -> None:
    kb_id = uuid.uuid4().hex
    vectorstore.upsert(
        kb_id,
        ids=["d1::0", "d1::1", "d2::0"],
        embeddings=[_vec("a"), _vec("b"), _vec("c")],
        documents=["a", "b", "c"],
        metadatas=[
            {"doc_id": "d1", "chunk_idx": 0},
            {"doc_id": "d1", "chunk_idx": 1},
            {"doc_id": "d2", "chunk_idx": 0},
        ],
    )

    vectorstore.delete_by_doc(kb_id, "d1")
    # d2::0 should still be there.
    res = vectorstore.query(kb_id, query_embedding=_vec("c"), top_k=5)
    ids = {r["id"] for r in res}
    assert "d2::0" in ids
    assert "d1::0" not in ids
    assert "d1::1" not in ids


def test_delete_collection_is_idempotent(vectorstore: VectorStore) -> None:
    kb_id = uuid.uuid4().hex
    vectorstore.get_or_create(kb_id, dim=4)
    vectorstore.delete_collection(kb_id)
    # Calling again must not raise.
    vectorstore.delete_collection(kb_id)
    # And the collection should be gone.
    assert vectorstore.get_collection(kb_id) is None


def test_iter_ids_format() -> None:
    assert VectorStore.iter_ids("doc-1", range(3)) == [
        "doc-1::0",
        "doc-1::1",
        "doc-1::2",
    ]


def test_collection_name_format() -> None:
    assert VectorStore.collection_name("abc123") == "kb_abc123"
    with pytest.raises(ValueError):
        VectorStore.collection_name("")