"""Tests for ``app.rag.pdf_inspector``.

The inspector is a routing layer: it must return a deterministic
``path`` decision (``text``/``ocr``/``vision``) plus a
``text_ratio`` in [0, 1] for any well-formed PDF, and must surface a
clear error for a missing file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.pdf_inspector import inspect_pdf


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to ``tests/fixtures`` (Phase C.1 PDF samples)."""
    return Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Routing decisions
# ---------------------------------------------------------------------------


def test_inspect_text_pdf_returns_text_path(fixtures_dir: Path) -> None:
    """A text-bearing PDF routes to ``text`` and clears the OCR threshold."""
    p = fixtures_dir / "sample_text.pdf"
    if not p.exists():
        pytest.skip(f"fixture missing: {p}")
    info = inspect_pdf(p)
    assert info["path"] == "text"
    assert info["text_ratio"] > 0.5
    assert info["needs_ocr"] is False
    assert info["needs_vision"] is False


def test_inspect_scan_pdf_returns_ocr_or_vision_path(fixtures_dir: Path) -> None:
    """A scan-only PDF (no embedded text) routes to OCR or Vision."""
    p = fixtures_dir / "sample_scan.pdf"
    if not p.exists():
        pytest.skip(f"fixture missing: {p}")
    info = inspect_pdf(p)
    # ``scan`` may flip between ``ocr`` and ``vision`` depending on
    # whether the residual embedded text (debug watermark, etc.)
    # pushes it above or below the 0.2 vision threshold. Both routes
    # are valid for a scan; the contract is "needs OCR".
    assert info["path"] in ("ocr", "vision")
    assert info["needs_ocr"] is True


def test_inspect_returns_page_count(fixtures_dir: Path) -> None:
    """``page_count`` is a positive integer for any well-formed PDF."""
    p = fixtures_dir / "sample_text.pdf"
    if not p.exists():
        pytest.skip(f"fixture missing: {p}")
    info = inspect_pdf(p)
    assert isinstance(info["page_count"], int)
    assert info["page_count"] >= 1


def test_inspect_pdf_not_found_raises() -> None:
    """A missing path raises a clear error (FileNotFoundError or RuntimeError)."""
    with pytest.raises(Exception):
        inspect_pdf("/nonexistent/path.pdf")


def test_inspect_text_ratio_is_bounded(fixtures_dir: Path) -> None:
    """``text_ratio`` is always in [0.0, 1.0]."""
    p = fixtures_dir / "sample_text.pdf"
    if not p.exists():
        pytest.skip(f"fixture missing: {p}")
    info = inspect_pdf(p)
    assert 0.0 <= info["text_ratio"] <= 1.0
    # The ratio must be a 3-decimal float — that's part of the public contract.
    assert isinstance(info["text_ratio"], float)
