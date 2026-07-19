"""DOCX parser (python-docx).

Returns a list of sections. ``page`` is left as ``None`` because
DOCX has no native page concept.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from docx import Document
from docx.opc.exceptions import PackageNotFoundError

logger = logging.getLogger(__name__)


def parse_docx(path: str | Path) -> List[dict]:
    """Extract paragraphs from a DOCX file.

    Returns ``{"page": None, "text": <str>}`` per non-empty paragraph.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"DOCX not found: {p}")

    try:
        doc = Document(str(p))
    except PackageNotFoundError as exc:
        raise RuntimeError(f"Failed to open DOCX {p.name}: {exc}") from exc

    sections: List[dict] = []
    for para in doc.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        sections.append({"page": None, "text": text})
    return sections