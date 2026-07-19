"""Document loader.

Dispatches to a parser based on file extension. The supported set is
``{.pdf, .docx, .md, .markdown, .txt, .html, .htm}``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Dict, List

from app.rag import (
    parser_doc, parser_docx, parser_html, parser_md, parser_pdf, parser_txt,
)

logger = logging.getLogger(__name__)


PARSERS: Dict[str, Callable[[Path], List[dict]]] = {
    ".pdf": parser_pdf.parse_pdf,
    ".docx": parser_docx.parse_docx,
    ".doc": parser_doc.parse_doc,                # legacy MS Word (via libreoffice)
    ".md": parser_md.parse_md,
    ".markdown": parser_md.parse_md,
    ".txt": parser_txt.parse_txt,
    ".html": parser_html.parse_html,
    ".htm": parser_html.parse_html,
}


def detect_ext(path: str | Path) -> str:
    """Return the lowercased extension (including the leading dot)."""
    return Path(path).suffix.lower()


def supported_extensions() -> List[str]:
    """Return the list of supported extensions (sorted)."""
    return sorted(PARSERS.keys())


def load_document(path: str | Path) -> List[dict]:
    """Load ``path`` and return a list of ``{page, text}`` sections.

    Raises ``UnsupportedFormat`` when the extension has no parser, and
    ``FileNotFoundError`` when the path does not exist.
    """
    p = Path(path)
    ext = detect_ext(p)
    parser = PARSERS.get(ext)
    if parser is None:
        raise UnsupportedFormat(f"Unsupported file extension: {ext!r} for {p.name}")
    return parser(p)


class UnsupportedFormat(ValueError):
    """Raised when no parser is registered for the file's extension."""