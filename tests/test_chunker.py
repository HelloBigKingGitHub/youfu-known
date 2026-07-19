"""Tests for the RecursiveChunker."""

from __future__ import annotations

import pytest

from app.rag.chunker import Chunk, RecursiveChunker


def _long_text(repetitions: int = 30) -> str:
    base = (
        "youfu-known 是一个本地化的个人知识库 + RAG 系统。"
        "它支持 PDF / Word / Markdown / HTML / 纯文本。"
        "Chunker 应当按段落、句号、空格递归地切分文本，"
        "相邻块之间保留 overlap 以维持上下文连贯。"
    )
    return "\n\n".join(f"段落 {i}: {base}" for i in range(repetitions))


def test_chunk_returns_at_least_one_chunk() -> None:
    chunker = RecursiveChunker(chunk_size=120, chunk_overlap=20)
    out = chunker.chunk([{"page": None, "text": _long_text()}])
    assert len(out) >= 1
    assert all(isinstance(c, Chunk) for c in out)


def test_chunks_within_size_budget() -> None:
    chunk_size = 200
    chunk_overlap = 40
    chunker = RecursiveChunker(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    out = chunker.chunk([{"page": None, "text": _long_text(repetitions=40)}])
    assert out
    for c in out:
        assert len(c.text) <= chunk_size + chunk_overlap + 5, (
            f"chunk len {len(c.text)} exceeds {chunk_size + chunk_overlap + 5}: {c.text[:80]!r}"
        )


def test_page_metadata_propagates() -> None:
    chunker = RecursiveChunker(chunk_size=80, chunk_overlap=10)
    sections = [
        {"page": 1, "text": "A" * 400},
        {"page": None, "text": "B" * 400},
    ]
    out = chunker.chunk(sections)
    page_chunks = [c for c in out if c.page == 1]
    none_chunks = [c for c in out if c.page is None]
    assert page_chunks, "page=1 chunks missing"
    assert none_chunks, "page=None chunks missing"
    assert page_chunks[0].text.startswith("[page 1]")


def test_source_offset_nonnegative_and_increasing() -> None:
    chunker = RecursiveChunker(chunk_size=100, chunk_overlap=20)
    out = chunker.chunk([{"page": 7, "text": _long_text(repetitions=10)}])
    offsets = [c.source_offset for c in out]
    assert all(o >= 0 for o in offsets)
    # Offsets should be weakly non-decreasing within the same section.
    assert offsets == sorted(offsets)


def test_empty_input_yields_no_chunks() -> None:
    chunker = RecursiveChunker(chunk_size=100, chunk_overlap=10)
    assert chunker.chunk([]) == []
    assert chunker.chunk([{"page": None, "text": "   \n  "}]) == []


def test_invalid_overlap_raises() -> None:
    with pytest.raises(ValueError):
        RecursiveChunker(chunk_size=100, chunk_overlap=100)
    with pytest.raises(ValueError):
        RecursiveChunker(chunk_size=0, chunk_overlap=0)


def test_overlap_actually_overlaps() -> None:
    """Tail of chunk N must appear as prefix of chunk N+1's body."""
    chunker = RecursiveChunker(chunk_size=120, chunk_overlap=30)
    body = "ABCDEFGHIJ" * 50  # 500 chars of recognisable repeated token
    out = chunker.chunk([{"page": None, "text": body}])
    assert len(out) >= 2
    # Strip the optional [page X] prefix when comparing.
    def strip_prefix(s: str) -> str:
        return s.split("] ", 1)[1] if s.startswith("[page ") else s

    a = strip_prefix(out[0].text)
    b = strip_prefix(out[1].text)
    tail = a[-30:]
    assert tail and tail in b, (
        f"expected tail {tail!r} of chunk0 to overlap into chunk1 ({b[:60]!r}...)"
    )


def test_short_text_fits_in_one_chunk() -> None:
    chunker = RecursiveChunker(chunk_size=300, chunk_overlap=30)
    out = chunker.chunk([{"page": None, "text": "短文本测试。"}])
    assert len(out) == 1
    assert out[0].text == "短文本测试。"
    assert out[0].source_offset == 0