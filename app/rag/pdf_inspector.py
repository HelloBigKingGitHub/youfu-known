"""PDF text-vs-scan detection (decision tree).

This module inspects a PDF and decides which parsing path to take.
It is a **routing** layer only — it does not extract content. That work
is delegated to ``parser_pdf_v2`` (PyMuPDF + pdfplumber) and, in
Phase C.2, ``parser_pdf_ocr`` (Tesseract).

Design (Phase C.1)
------------------
The decision tree is intentionally simple and matches the spec
``openspec/tasks/pdf-parser-c.md``:

* ``text_ratio > 0.5``  → ``path = "text"``   (PyMuPDF + pdfplumber)
* ``text_ratio < 0.2``  → ``path = "vision"`` (Phase C.3 opt-in)
* otherwise             → ``path = "ocr"``    (Phase C.2 Tesseract)

``text_ratio`` is the average number of characters extracted from the
first three pages divided by a soft cap of 500 characters / page.
500 chars is roughly one paragraph of body text — well above what
pypdf can recover from a scanned page and well below a typical text
page (which is usually >1000 chars).

The check is deliberately **fast and pypdf-based** so it can run
before the heavier PyMuPDF/pdfplumber path without doubling cost
on a malformed or scanned PDF.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from pypdf import PdfReader

logger = logging.getLogger(__name__)


# Soft cap: a fully text-based A4 page typically yields 1500-3000 chars
# via PyMuPDF and 1000-2000 chars via pypdf. 500 is a conservative
# threshold that confidently separates "text" from "scanned/empty".
_TEXT_CHARS_PER_PAGE = 500.0

# Sample size: first N pages is enough to distinguish a long scan-only
# document (text_ratio ≈ 0 on every page) from a text document.
_SAMPLE_PAGES = 3


def inspect_pdf(path: str | Path) -> Dict[str, Any]:
    """Inspect ``path`` and return a routing decision.

    Parameters
    ----------
    path:
        Filesystem path to a PDF.

    Returns
    -------
    dict
        ``{
            "path": "text" | "ocr" | "vision",
            "page_count": int,
            "text_ratio": float,    # 0.0 - 1.0
            "has_tables": bool,     # reserved for Phase C.3
            "has_images": bool,     # reserved for Phase C.3
            "needs_ocr": bool,
            "needs_vision": bool,
        }``

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    RuntimeError
        If pypdf cannot open the file (corrupt / encrypted).
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"PDF not found: {p}")

    try:
        reader = PdfReader(str(p))
    except Exception as exc:  # pypdf raises PdfReadError or EmptyFileError
        raise RuntimeError(f"Failed to open PDF {p.name}: {exc}") from exc

    page_count = len(reader.pages)
    sample_pages = min(_SAMPLE_PAGES, page_count)

    char_count = 0
    for i in range(sample_pages):
        try:
            text = reader.pages[i].extract_text() or ""
            char_count += len(text.strip())
        except Exception as exc:  # malformed page — treat as 0 chars
            logger.debug("pypdf extract_text failed on page %s of %s: %s", i + 1, p.name, exc)

    avg_chars = char_count / sample_pages if sample_pages else 0.0
    text_ratio = min(avg_chars / _TEXT_CHARS_PER_PAGE, 1.0)

    needs_vision = text_ratio < 0.2
    needs_ocr = text_ratio < 0.5  # vision < 0.2 is a strict subset of ocr < 0.5

    if needs_vision:
        route = "vision"
    elif needs_ocr:
        route = "ocr"
    else:
        route = "text"

    return {
        "path": route,
        "page_count": page_count,
        "text_ratio": round(text_ratio, 3),
        "has_tables": False,   # Phase C.3
        "has_images": False,   # Phase C.3
        "needs_ocr": needs_ocr,
        "needs_vision": needs_vision,
    }
