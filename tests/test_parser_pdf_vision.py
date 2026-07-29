"""Tests for ``app.rag.parser_pdf_vision`` (Phase C.3: Qwen-VL-Max multimodal LLM).

Mirrors ``tests/test_parser_pdf_ocr.py`` (Phase C.2) but mocks
``QwenVLClient.avision`` instead of ``pytesseract.image_to_string``.
The Qwen-VL client is **not** exercised against a real endpoint —
``avision`` is replaced with an ``AsyncMock`` that returns deterministic
fake markdown. This keeps the suite offline-safe and CI-runnable.

Fixtures used
-------------
* ``sample_complex.pdf``  (Phase C.1) — non-trivial layout PDF that
  PyMuPDF can render to PNG. The Qwen-VL mock is keyed on this so the
  test verifies "vision path triggers + sections have markdown +
  metadata.extractor='qwen-vl-max'".

Tests (3 total — mirrors spec openspec/tasks/pdf-parser-c.md § C.3):

1. ``test_parse_complex_pdf_uses_vision`` — happy path: complex PDF →
   Qwen-VL mock → sections with markdown + correct metadata.
2. ``test_parse_vision_handles_missing_file`` — missing file →
   ``FileNotFoundError``.
3. ``test_parse_vision_handles_api_failure`` — Qwen-VL API raises →
   parser does not crash, returns empty list (per-page 防御).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to ``tests/fixtures`` (Phase C.1 PDF samples)."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def mock_vision_client() -> Iterator[MagicMock]:
    """Mock ``QwenVLClient.avision`` to return deterministic fake markdown.

    The returned MagicMock quacks like a ``QwenVLClient`` instance:
    ``.avision(image_png, prompt)`` is an ``AsyncMock`` that resolves to
    a fake markdown string. ``.MODEL`` is preserved (so the parser can
    record it in section metadata) by hooking ``__class__`` onto the
    real class.
    """
    from app.llm.qwen_vl_client import QwenVLClient

    client = MagicMock()
    # Preserve the real MODEL constant for the metadata field.
    client.__class__ = QwenVLClient  # type: ignore[assignment]
    client.avision = AsyncMock(
        return_value="# Mock Markdown\n\n- Section 1\n- Section 2"
    )
    yield client


# ---------------------------------------------------------------------------
# Tests (3 total — matches the spec § C.3 验收 list)
# ---------------------------------------------------------------------------


def test_parse_complex_pdf_uses_vision(
    mock_vision_client: MagicMock, fixtures_dir: Path
) -> None:
    """Complex PDF: Qwen-VL 路径触发, sections 含 markdown + metadata.

    Verifies the basic happy path: a complex-layout PDF is rendered
    page by page (PyMuPDF, real), fed to ``QwenVLClient.avision``
    (mocked), and the resulting sections have the shape Phase C.1
    callers expect, plus the new ``metadata.extractor='qwen-vl-max'``
    + ``metadata.model='qwen-vl-max'`` markers that downstream audit
    log code keys off.
    """
    from app.rag.parser_pdf_vision import parse_pdf_vision

    p = fixtures_dir / "sample_complex.pdf"
    if not p.exists():
        pytest.skip(f"fixture missing: {p}")

    sections = parse_pdf_vision(p, client=mock_vision_client)
    assert len(sections) >= 1, "Vision parser should yield ≥1 section"

    expected_keys = {"page", "text", "tables", "images", "metadata"}
    metadata_keys = {"extractor", "model", "dpi"}
    for s in sections:
        # Section shape (跟 Phase C.1 + C.2 同款契约).
        assert expected_keys.issubset(s.keys()), (
            f"missing keys in section: {expected_keys - set(s.keys())}"
        )
        assert metadata_keys.issubset(s["metadata"].keys()), (
            f"missing metadata keys: {metadata_keys - set(s['metadata'].keys())}"
        )
        # Vision-specific markers (跟 Phase C.3 spec 同款).
        assert s["metadata"]["extractor"] == "qwen-vl-max"
        assert s["metadata"]["model"] == "qwen-vl-max"
        assert s["metadata"]["dpi"] == 200
        # Mock markdown should appear in every page's text.
        assert "Mock Markdown" in s["text"]
        # tables/images are intentionally empty (vision handles them
        # inline in the markdown text, not as structured lists).
        assert s["tables"] == []
        assert s["images"] == []

    # The mock should have been called once per page.
    assert mock_vision_client.avision.await_count == len(sections)


def test_parse_vision_handles_missing_file() -> None:
    """File not found raises ``FileNotFoundError`` (跟 Phase C.1 + C.2 同款).

    Guards the production failure mode where the operator hands the
    parser a path that has been moved or never existed.
    """
    from app.rag.parser_pdf_vision import parse_pdf_vision

    # Build a minimal mock client — the file check happens **before**
    # any API call, so the client is never invoked.
    client = MagicMock()
    client.avision = AsyncMock(return_value="")

    with pytest.raises(FileNotFoundError):
        parse_pdf_vision("/nonexistent/youfu_known_missing.pdf", client=client)

    # And the client must not have been touched.
    assert client.avision.await_count == 0


def test_parse_vision_handles_api_failure(fixtures_dir: Path) -> None:
    """API 调用失败时, sections 可能空 (不 crash).

    Mirrors the Phase C.2 "per-page 防御" + INC-005 pattern: a single
    API failure must not abort the whole document. If every page fails,
    the parser returns an empty list (caller falls back to pypdf via
    ``load_document``).
    """
    client = MagicMock()
    # Always-raise API.
    client.avision = AsyncMock(side_effect=RuntimeError("API failed"))

    from app.rag.parser_pdf_vision import parse_pdf_vision

    p = fixtures_dir / "sample_complex.pdf"
    if not p.exists():
        pytest.skip(f"fixture missing: {p}")

    # Must not raise — the parser swallows per-page failures (跟 Phase
    # C.2 OCR 防御模式 同款).
    sections = parse_pdf_vision(p, client=client)
    assert isinstance(sections, list)
    # When every page's API call fails, sections is empty (no fake
    # markdown ever made it back).
    assert sections == []
    # The mock was awaited once per page (PyMuPDF rendered them all,
    # then each API call failed).
    assert client.avision.await_count >= 1