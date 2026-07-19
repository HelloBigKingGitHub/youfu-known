"""PDF parser (pypdf).

Returns a list of sections of the form::

    {"page": int | None, "text": str}
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)


def parse_pdf(path: str | Path) -> List[dict]:
    """Extract pages from a PDF file.

    Each page is returned as ``{"page": <int 1-based>, "text": <str>}``.
    Empty pages are skipped.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"PDF not found: {p}")

    try:
        reader = PdfReader(str(p))
    except PdfReadError as exc:
        raise RuntimeError(f"Failed to open PDF {p.name}: {exc}") from exc

    sections: List[dict] = []
    for idx, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # pragma: no cover -- malformed page
            logger.warning("Failed to extract text from page %s of %s: %s", idx, p.name, exc)
            text = ""
        text = text.strip()
        if not text:
            continue
        sections.append({"page": idx, "text": text})
    return sections