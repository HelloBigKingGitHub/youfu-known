"""Tests for Pydantic models (round-trip and validation)."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.kb.models import (
    ApiResponse,
    ChatRequest,
    ChatResponse,
    Citation,
    Document,
    DocumentStatus,
    KBDetail,
    KnowledgeBase,
    UploadedFile,
)


def test_knowledge_base_round_trip() -> None:
    kb = KnowledgeBase(
        id="abc",
        name="测试",
        description="desc",
        created_at=datetime(2026, 1, 2, 3, 4, 5),
        doc_count=3,
        chunk_count=12,
    )
    payload = kb.model_dump()
    assert payload["name"] == "测试"
    assert payload["doc_count"] == 3

    # Round-trip via JSON.
    json_str = kb.model_dump_json()
    restored = KnowledgeBase.model_validate_json(json_str)
    assert restored == kb


def test_document_status_enum_values() -> None:
    assert DocumentStatus.PENDING.value == "pending"
    assert DocumentStatus.PROCESSING.value == "processing"
    assert DocumentStatus.READY.value == "ready"
    assert DocumentStatus.FAILED.value == "failed"


def test_document_requires_known_status() -> None:
    with pytest.raises(ValidationError):
        Document(
            id="d",
            kb_id="k",
            filename="x.txt",
            ext=".txt",
            size_bytes=10,
            storage_path="/tmp/x.txt",
            status="bogus",  # type: ignore[arg-type]
            created_at=datetime.now(),
        )


def test_chat_request_validation() -> None:
    # Empty question must fail.
    with pytest.raises(ValidationError):
        ChatRequest(question="")

    # top_k bounds
    with pytest.raises(ValidationError):
        ChatRequest(question="ok", top_k=0)
    with pytest.raises(ValidationError):
        ChatRequest(question="ok", top_k=999)

    req = ChatRequest(question="hi", top_k=3, stream=False)
    assert req.top_k == 3
    assert req.stream is False


def test_chat_response_round_trip() -> None:
    resp = ChatResponse(
        answer="回答 [1]",
        citations=[
            Citation(
                n=1,
                doc_id="d1",
                doc_filename="a.md",
                chunk_idx=3,
                score=0.9,
                text="片段文本",
            )
        ],
    )
    again = ChatResponse.model_validate_json(resp.model_dump_json())
    assert again.answer == resp.answer
    assert again.citations[0].doc_filename == "a.md"


def test_api_response_ok_and_fail() -> None:
    ok = ApiResponse[int].ok(42)
    assert ok.code == 0
    assert ok.data == 42
    assert ok.message is None

    fail = ApiResponse[str].fail(404, "not found")
    assert fail.code == 404
    assert fail.data is None
    assert fail.message == "not found"


def test_uploaded_file_round_trip() -> None:
    uf = UploadedFile(
        doc_id="d1", filename="a.pdf", status=DocumentStatus.PENDING
    )
    again = UploadedFile.model_validate_json(uf.model_dump_json())
    assert again == uf


def test_kb_detail_round_trip() -> None:
    detail = KBDetail(
        kb=KnowledgeBase(
            id="kb",
            name="kb",
            created_at=datetime.now(),
        ),
        documents=[
            Document(
                id="d",
                kb_id="kb",
                filename="a.txt",
                ext=".txt",
                size_bytes=10,
                storage_path="/tmp/a.txt",
                status=DocumentStatus.READY,
                created_at=datetime.now(),
                chunk_count=4,
            )
        ],
    )
    again = KBDetail.model_validate_json(detail.model_dump_json())
    assert again.kb.id == "kb"
    assert again.documents[0].chunk_count == 4
    assert again.documents[0].status == DocumentStatus.READY