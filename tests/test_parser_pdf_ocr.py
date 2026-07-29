"""Tests for ``app.rag.parser_pdf_ocr`` (Phase C.2: Tesseract OCR for scan PDFs).

These tests use the ``sample_scan.pdf`` fixture from Phase C.1 (image-only
page) plus ``monkeypatch`` to mock ``pytesseract`` so they run even when
Tesseract is not installed on the host (CI environment).

Mocking strategy
----------------
Real ``pytesseract.image_to_string`` is replaced with a callable that
returns deterministic fake OCR text keyed on the ``lang`` parameter.
This means:

* Tests run on hosts without Tesseract installed.
* The ``PYTESSERACT_AVAILABLE`` flag is flipped on for the duration of
  the test so the parser actually runs the OCR branch.
* We still exercise the PyMuPDF rendering path (which is real and
  requires the Phase C.1 ``pymupdf`` dep) so a regression in the
  page-rendering contract surfaces immediately.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to ``tests/fixtures`` (Phase C.1 PDF samples, includes sample_scan.pdf)."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def mock_tesseract(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Mock ``pytesseract.image_to_string`` so OCR is deterministic + offline-safe.

    Flips ``PYTESSERACT_AVAILABLE=True`` for the duration of the test
    (the test might already be running on a host that has pytesseract
    installed) and replaces ``pytesseract.image_to_string`` with a
    callable that returns ``"mocked OCR text for <lang>"``.
    """
    import app.rag.parser_pdf_ocr as mod

    monkeypatch.setattr(mod, "PYTESSERACT_AVAILABLE", True)

    def _fake_image_to_string(img, lang: str = "chi_sim+eng", **_kwargs):
        # Mirror Tesseract's real return shape: a string with trailing whitespace.
        return f"mocked OCR text for {lang} "

    monkeypatch.setattr(mod.pytesseract, "image_to_string", _fake_image_to_string)
    yield


# ---------------------------------------------------------------------------
# Tests (5 total — mirrors spec openspec/tasks/pdf-parser-c.md § C.2)
# ---------------------------------------------------------------------------


def test_parse_scan_pdf_runs_ocr(
    mock_tesseract, fixtures_dir: Path
) -> None:
    """Scan PDF: OCR path triggers and returns mock-OCR sections.

    Verifies the basic happy path: a scan-only PDF is rendered page
    by page, fed to ``pytesseract.image_to_string``, and the resulting
    sections have the shape Phase C.1 callers expect.
    """
    from app.rag.parser_pdf_ocr import parse_pdf_ocr

    p = fixtures_dir / "sample_scan.pdf"
    if not p.exists():
        pytest.skip(f"fixture missing: {p}")
    sections = parse_pdf_ocr(p)
    assert len(sections) >= 1, "OCR should yield at least one section"
    for s in sections:
        assert "mocked OCR text" in s["text"]
        assert s["page"] >= 1
        assert s["tables"] == []
        assert s["images"] == []
        assert s["metadata"]["extractor"] == "tesseract"
        assert s["metadata"]["lang"] == "chi_sim+eng"
        assert s["metadata"]["dpi"] == 200


def test_parse_ocr_handles_missing_file() -> None:
    """A path that does not exist raises ``FileNotFoundError``."""
    from app.rag.parser_pdf_ocr import parse_pdf_ocr

    with pytest.raises(FileNotFoundError):
        parse_pdf_ocr("/nonexistent/youfu_known_missing.pdf")


def test_parse_ocr_handles_pytesseract_missing(
    monkeypatch: pytest.MonkeyPatch, fixtures_dir: Path
) -> None:
    """When pytesseract is unavailable, the parser raises ``RuntimeError``.

    This guards the production failure mode where the host has PyMuPDF
    but no Tesseract binary (e.g. CI / dev box without
    ``scripts/install_pi_pdf.sh``).
    """
    import app.rag.parser_pdf_ocr as mod

    monkeypatch.setattr(mod, "PYTESSERACT_AVAILABLE", False)
    from app.rag.parser_pdf_ocr import parse_pdf_ocr

    p = fixtures_dir / "sample_scan.pdf"
    if not p.exists():
        pytest.skip(f"fixture missing: {p}")
    with pytest.raises(RuntimeError, match="pytesseract"):
        parse_pdf_ocr(p)


def test_parse_ocr_lang_parameter(
    mock_tesseract, fixtures_dir: Path
) -> None:
    """The ``lang`` parameter is forwarded to pytesseract and recorded in metadata."""
    from app.rag.parser_pdf_ocr import parse_pdf_ocr

    p = fixtures_dir / "sample_scan.pdf"
    if not p.exists():
        pytest.skip(f"fixture missing: {p}")
    sections = parse_pdf_ocr(p, lang="eng")
    assert len(sections) >= 1
    for s in sections:
        assert s["metadata"]["lang"] == "eng"
        # Mock text encodes the lang so we can verify the forward.
        assert "eng" in s["text"]


def test_parse_ocr_returns_section_shape(
    mock_tesseract, fixtures_dir: Path
) -> None:
    """Section dict shape mirrors Phase C.1's parser_pdf_v2 contract.

    Critical because downstream code (``chunker``, ``retriever``,
    ``storage``) keys off these fields. Any drift here is a Phase C.1
    regression.
    """
    from app.rag.parser_pdf_ocr import parse_pdf_ocr

    p = fixtures_dir / "sample_scan.pdf"
    if not p.exists():
        pytest.skip(f"fixture missing: {p}")
    sections = parse_pdf_ocr(p)
    assert sections, "scan PDF must yield at least one section"
    expected_keys = {"page", "text", "tables", "images", "metadata"}
    metadata_keys = {"extractor", "lang", "dpi"}
    for s in sections:
        assert expected_keys.issubset(s.keys()), (
            f"missing keys in section: {expected_keys - set(s.keys())}"
        )
        assert metadata_keys.issubset(s["metadata"].keys()), (
            f"missing metadata keys: {metadata_keys - set(s['metadata'].keys())}"
        )