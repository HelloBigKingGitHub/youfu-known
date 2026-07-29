"""PDF parser v2 (PyMuPDF + pdfplumber, layout-aware).

This parser co-exists with the original ``parser_pdf.py`` (pypdf,
text-only). It is **not** a replacement — the loader uses a
``prefer_v2`` dispatch: PyMuPDF first, then pdfplumber for table
enrichment, then pypdf as a last-resort fallback. This mirrors the
"旁路 adapter" (bypass adapter) pattern from the 32-commit DDD effort
and INC-005: 0 changes to existing runtime paths.

Extraction strategy
-------------------
1. **PyMuPDF** (``fitz``) — primary, layout-aware text + image
   bounding boxes. Native C, fast on Raspberry Pi 4.
2. **pdfplumber** — second pass, enriches each page section with
   ``extract_tables()`` results. PyMuPDF alone does not expose
   table structure.
3. **pypdf** — final fallback if both PyMuPDF and pdfplumber are
   missing or fail. Produces the same ``{page, text}`` shape as
   ``parser_pdf.parse_pdf``.

Output shape
------------
Each page becomes::

    {
        "page": int,               # 1-based
        "text": str,               # main text
        "tables": list[list[list[str]]],   # pdfplumber tables
        "images": list[dict],      # PyMuPDF image bboxes
        "metadata": {
            "extractor": "pymupdf" | "pymupdf+pdfplumber" | "pypdf_fallback",
        },
    }

The ``metadata.extractor`` field is the audit trail callers use to
decide whether the result came from the new pipeline or the legacy
fallback.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from pypdf import PdfReader

logger = logging.getLogger(__name__)


try:
    import fitz  # type: ignore[import-not-found]  # PyMuPDF

    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    fitz = None  # type: ignore[assignment]
    logger.warning(
        "PyMuPDF not installed; parser_pdf_v2 will fall back to pypdf. "
        "Install with: pip install pymupdf==1.25.5"
    )


try:
    import pdfplumber  # type: ignore[import-not-found]

    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    pdfplumber = None  # type: ignore[assignment]
    logger.warning(
        "pdfplumber not installed; table extraction disabled. "
        "Install with: pip install pdfplumber==0.11.4"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_pdf_v2(path: str | Path) -> List[Dict[str, Any]]:
    """Parse ``path`` with the v2 (PyMuPDF + pdfplumber) pipeline.

    Returns a list of page sections. The list may be empty (e.g. for a
    scanned PDF with no embedded text — Phase C.2 will populate this
    via Tesseract).

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"PDF not found: {p}")

    if PYMUPDF_AVAILABLE:
        try:
            sections = _parse_with_pymupdf(p)
        except Exception as exc:
            logger.warning(
                "PyMuPDF parse failed for %s: %s; falling back to pypdf",
                p.name,
                exc,
            )
            return _parse_with_pypdf_fallback(p)

        # Second pass: enrich with tables if pdfplumber is available.
        if PDFPLUMBER_AVAILABLE:
            _enrich_with_tables(p, sections)

        return sections

    # PyMuPDF missing — straight to legacy fallback.
    return _parse_with_pypdf_fallback(p)


# ---------------------------------------------------------------------------
# PyMuPDF path
# ---------------------------------------------------------------------------


def _parse_with_pymupdf(p: Path) -> List[Dict[str, Any]]:
    """Extract text + image bboxes with PyMuPDF."""
    assert fitz is not None  # guarded by caller
    doc = fitz.open(str(p))
    sections: List[Dict[str, Any]] = []
    try:
        # PyMuPDF Document is not iterable in a generic-typed way; use load_page.
        page_count = doc.page_count
        for idx in range(1, page_count + 1):
            page = doc.load_page(idx - 1)
            # sort=True preserves the natural reading order across columns.
            text = (page.get_text("text", sort=True) or "").strip()
            images = _extract_image_bboxes(page)
            if text or images:
                sections.append(
                    {
                        "page": idx,
                        "text": text,
                        "tables": [],
                        "images": images,
                        "metadata": {"extractor": "pymupdf"},
                    }
                )
    finally:
        doc.close()
    return sections


def _extract_image_bboxes(page: Any) -> List[Dict[str, Any]]:
    """Return image bounding-box dicts for a single PyMuPDF page."""
    images: List[Dict[str, Any]] = []
    try:
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                bbox = page.get_image_bbox(img)
            except Exception as exc:  # pragma: no cover -- PyMuPDF edge cases
                logger.debug("get_image_bbox failed for xref=%s: %s", xref, exc)
                continue
            images.append(
                {
                    "xref": xref,
                    "bbox": [float(bbox.x0), float(bbox.y0), float(bbox.x1), float(bbox.y1)],
                }
            )
    except Exception as exc:  # pragma: no cover -- defensive
        logger.debug("get_images failed on page: %s", exc)
    return images


# ---------------------------------------------------------------------------
# pdfplumber enrichment
# ---------------------------------------------------------------------------


def _enrich_with_tables(p: Path, sections: List[Dict[str, Any]]) -> None:
    """Merge pdfplumber tables into ``sections`` (in-place).

    Only pages that already have a section are enriched; if pdfplumber
    finds more pages than PyMuPDF did (rare — typically an OCR ghost
    layer), the extra pages are ignored.
    """
    assert pdfplumber is not None  # guarded by caller
    try:
        with pdfplumber.open(str(p)) as pdf:
            for idx, page in enumerate(pdf.pages, start=1):
                if idx > len(sections):
                    break
                try:
                    tables = page.extract_tables() or []
                except Exception as exc:  # pragma: no cover -- pdfplumber edge cases
                    logger.warning(
                        "pdfplumber table extraction failed on page %s of %s: %s",
                        idx,
                        p.name,
                        exc,
                    )
                    continue
                if tables:
                    sections[idx - 1]["tables"] = tables
                    sections[idx - 1]["metadata"]["extractor"] = "pymupdf+pdfplumber"
    except Exception as exc:  # pragma: no cover -- defensive
        logger.warning("pdfplumber.open failed for %s: %s", p.name, exc)


# ---------------------------------------------------------------------------
# Legacy pypdf fallback
# ---------------------------------------------------------------------------


def _parse_with_pypdf_fallback(p: Path) -> List[Dict[str, Any]]:
    """Replicate ``parser_pdf.parse_pdf`` output with v2 metadata.

    This is the path taken when PyMuPDF is unavailable. The output
    shape matches the v2 contract (``text``, ``tables``, ``images``,
    ``metadata``) so callers don't have to branch.

    Behavioural parity with ``parser_pdf.parse_pdf`` is preserved:
    a file that pypdf cannot open (corrupt / encrypted / not a PDF
    at all) raises ``RuntimeError`` rather than returning an empty
    list. Per-page extraction errors are still caught and logged
    individually so that one bad page does not abort the whole
    document.
    """
    try:
        reader = PdfReader(str(p))
    except Exception as exc:
        raise RuntimeError(f"Failed to open PDF {p.name}: {exc}") from exc

    sections: List[Dict[str, Any]] = []
    for idx, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # pragma: no cover -- malformed page
            logger.warning(
                "pypdf extract_text failed on page %s of %s: %s", idx, p.name, exc
            )
            text = ""
        text = text.strip()
        if not text:
            continue
        sections.append(
            {
                "page": idx,
                "text": text,
                "tables": [],
                "images": [],
                "metadata": {"extractor": "pypdf_fallback"},
            }
        )
    return sections
