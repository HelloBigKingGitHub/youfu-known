"""Tests for the Retriever (no network: both clients are fakes)."""

from __future__ import annotations

import asyncio

import pytest

from app.kb.service import KBService
from app.rag.embedder import Embedder
from app.rag.retriever import Citation, RagResult, Retriever
from app.rag.vectorstore import VectorStore


@pytest.fixture
def retriever(
    settings,
    vectorstore: VectorStore,
    fake_embedding_client,
    fake_chat_client,
) -> Retriever:
    embedder = Embedder(fake_embedding_client)
    return Retriever(
        embedder=embedder,
        vectorstore=vectorstore,
        chat_client=fake_chat_client,
        settings=settings,
    )


@pytest.fixture
def populated_kb(
    settings, kb_service: KBService, vectorstore: VectorStore, sample_txt: Path
):
    """A KB with at least one ingested doc so the retriever finds hits."""
    kb = kb_service.create_kb(name="检索测试")
    uploaded = kb_service.upload_document(
        kb_id=kb.id,
        filename=sample_txt.name,
        ext=".txt",
        content=sample_txt.read_bytes(),
    )
    doc = kb_service.ingest_document(kb.id, uploaded.doc_id)
    return kb, doc


def test_ask_returns_answer_and_citations(
    retriever: Retriever, populated_kb
) -> None:
    kb, _doc = populated_kb
    result = asyncio.run(retriever.ask(kb.id, "什么是 youfu-known?"))
    assert isinstance(result, RagResult)
    assert result.answer
    assert result.citations, "expected at least one citation"
    for c in result.citations:
        assert isinstance(c, Citation)
        assert c.n >= 1
        assert c.doc_id
        assert c.doc_filename
        assert c.text


def test_ask_empty_question_raises(retriever: Retriever) -> None:
    with pytest.raises(ValueError):
        asyncio.run(retriever.ask("any-kb", ""))


def test_ask_unknown_kb_returns_no_hits(
    retriever: Retriever, settings, sqlite_storage
) -> None:
    # Empty KB -> 0 hits -> no citations -> prompt is sent anyway.
    kb = sqlite_storage.create_kb(name="empty")
    result = asyncio.run(retriever.ask(kb.id, "anything"))
    assert result.answer
    assert result.citations == []