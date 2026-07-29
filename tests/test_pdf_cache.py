"""Tests for ``app.rag.pdf_cache`` (Phase C.2: SQLite 旁路 cache).

Covers the four behaviours that the 32-commit DDD Theme A established
for a side-channel cache:

* **roundtrip** — ``put`` then ``get`` returns the same sections.
* **miss** — unknown file returns ``None``.
* **dedup** — same byte content (any path) shares one cache entry.
* **maintenance** — ``clear`` removes all entries, ``lru_clean`` evicts
  oldest when the size budget is exceeded.

The tests use ``tmp_path`` exclusively so no real DB file is left
behind, mirroring ``tests/test_storage.py`` style.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.pdf_cache import PdfCache, _sha256_file


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cache(tmp_path: Path) -> PdfCache:
    """PdfCache instance pointed at a fresh tmp_path db."""
    db_path = tmp_path / "cache.db"
    return PdfCache(db_path)


# ---------------------------------------------------------------------------
# Tests (5 total — matches the example code in spec § C.2)
# ---------------------------------------------------------------------------


def test_cache_put_get_roundtrip(cache: PdfCache, tmp_path: Path) -> None:
    """put + get roundtrip preserves sections byte-for-byte."""
    p = tmp_path / "test.pdf"
    p.write_bytes(b"fake pdf content for roundtrip")
    sections = [
        {
            "page": 1,
            "text": "ocr text",
            "metadata": {"extractor": "tesseract", "lang": "chi_sim+eng"},
        }
    ]

    cache.put(p, ocr_sections=sections)
    result = cache.get(p)

    assert result is not None, "expected cache hit after put"
    assert result["ocr"] == sections
    assert result["vision"] is None, "vision_sections wasn't put; should be None"


def test_cache_get_miss_returns_none(cache: PdfCache, tmp_path: Path) -> None:
    """Cache miss (unknown sha256) returns ``None``."""
    p = tmp_path / "missing.pdf"
    p.write_bytes(b"x")
    assert cache.get(p) is None


def test_cache_sha256_dedup(cache: PdfCache, tmp_path: Path) -> None:
    """Same byte content under different paths shares one cache entry."""
    p1 = tmp_path / "a.pdf"
    p2 = tmp_path / "b.pdf"
    p1.write_bytes(b"identical content for dedup check")
    p2.write_bytes(b"identical content for dedup check")

    sections = [{"page": 1, "text": "x", "metadata": {"extractor": "tesseract"}}]
    cache.put(p1, ocr_sections=sections)

    # p2 should hit p1's cache because sha256 of the content is identical.
    result = cache.get(p2)
    assert result is not None
    assert result["ocr"] == sections
    # The cache only contains a single row, not two.
    assert cache.count() == 1


def test_cache_clear(cache: PdfCache, tmp_path: Path) -> None:
    """``clear`` removes every entry."""
    p = tmp_path / "test.pdf"
    p.write_bytes(b"clear-target")
    cache.put(p, ocr_sections=[{"page": 1, "text": "x"}])
    assert cache.count() == 1

    deleted = cache.clear()
    assert deleted == 1
    assert cache.count() == 0
    assert cache.get(p) is None


def test_cache_lru_clean(cache: PdfCache, tmp_path: Path) -> None:
    """LRU clean evicts oldest entries when total size exceeds the budget.

    Uses small synthetic sizes (NOT 100 MB) to keep the test fast: each
    entry's ``size_bytes`` is the on-disk file size (we write a known
    number of bytes), and we lower the cap accordingly.
    """
    # Three ~10 KB files with **unique** byte content so each gets its
    # own sha256 (otherwise INSERT OR REPLACE collapses duplicates into
    # a single row, defeating the LRU test).
    file_size = 10 * 1024
    for i in range(3):
        p = tmp_path / f"f{i}.pdf"
        # First byte differs across files → distinct sha256.
        p.write_bytes(bytes([i]) + b"x" * (file_size - 1))
        cache.put(p, ocr_sections=[{"page": 1, "text": f"f{i}"}])
    assert cache.count() == 3

    # Cap at ~15 KB → should keep the newest entry, drop the older two.
    # (LRU walks DESC by created_at; only rows whose cumulative size
    # still fits inside the cap are kept.)
    removed = cache.lru_clean(max_size_bytes=15 * 1024)
    assert removed >= 1
    assert cache.count() <= 2
    # The most-recently-inserted file should still be in the cache.
    latest = tmp_path / "f2.pdf"
    assert cache.get(latest) is not None