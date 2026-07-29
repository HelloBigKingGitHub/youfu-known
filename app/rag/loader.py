"""Document loader.

Dispatches to a parser based on file extension. The supported set is
``{.pdf, .docx, .md, .markdown, .txt, .html, .htm}``.

PDF dispatch (Phase C.1, INC-005 "0 改 runtime" pattern)
--------------------------------------------------------
``load_document`` accepts an optional ``prefer_v2`` kwarg (default
``True``) that, for ``.pdf`` only, prefers the new
``parser_pdf_v2`` (PyMuPDF + pdfplumber) over the original
``parser_pdf`` (pypdf). The legacy ``PARSERS`` dispatch is unchanged
and remains the single source of truth for non-PDF formats.

Failure modes:
- ``prefer_v2=False``  → always the original pypdf path.
- ``prefer_v2=True`` + ``parser_pdf_v2`` raises → log a warning and
  fall through to the original pypdf path. Callers never see the
  new failure mode.
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


def load_document(path: str | Path, *, prefer_v2: bool = True) -> List[dict]:
    """Load ``path`` and return a list of ``{page, text}`` sections.

    Raises ``UnsupportedFormat`` when the extension has no parser, and
    ``FileNotFoundError`` when the path does not exist.

    Parameters
    ----------
    path:
        File to load.
    prefer_v2:
        PDF-only opt-in. When ``True`` (default), try the v2 parser
        (PyMuPDF + pdfplumber) first and fall back to the original
        pypdf parser on failure. When ``False``, always use the
        original parser. Non-PDF formats ignore this flag.
    """
    p = Path(path)
    ext = detect_ext(p)

    # Phase C.1: PDF v2 dispatch (新增, 跟 INC-005 "0 改 runtime" 同款).
    # PARSERS dict above is **not** modified — this branch is a
    # bypass that lives entirely in load_document.
    if ext == ".pdf" and prefer_v2:
        try:
            from app.rag.parser_pdf_v2 import parse_pdf_v2  # lazy import

            sections = parse_pdf_v2(p)
            if sections:
                logger.info(
                    "Used parser_pdf_v2 for %s (got %d sections)", p.name, len(sections)
                )
                return sections
            logger.info(
                "parser_pdf_v2 returned empty for %s; falling back to parser_pdf",
                p.name,
            )
        except FileNotFoundError:
            # File genuinely missing — propagate so callers can surface a clear error.
            raise
        except Exception as exc:
            logger.warning(
                "parser_pdf_v2 failed for %s: %s; falling back to parser_pdf",
                p.name,
                exc,
            )

    parser = PARSERS.get(ext)
    if parser is None:
        raise UnsupportedFormat(f"Unsupported file extension: {ext!r} for {p.name}")
    return parser(p)


class UnsupportedFormat(ValueError):
    """Raised when no parser is registered for the file's extension."""