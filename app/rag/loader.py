"""Document loader.

Dispatches to a parser based on file extension. The supported set is
``{.pdf, .docx, .md, .markdown, .txt, .html, .htm}``.

PDF dispatch (Phase C.1 + C.2 + C.3, INC-005 "0 改 runtime" pattern)
--------------------------------------------------------------------
``load_document`` accepts three optional kwargs that, for ``.pdf`` only,
prefer the new pipelines over the original ``parser_pdf`` (pypdf):

* ``prefer_v2`` (Phase C.1, default ``True``) — try
  ``parser_pdf_v2`` (PyMuPDF + pdfplumber) first and fall back to the
  original pypdf parser on failure.
* ``prefer_ocr`` (Phase C.2, default ``False``) — when ``True``, also
  call ``pdf_inspector`` and, if the inspector decides the PDF
  is a scan (``needs_ocr=True``), route the call through
  ``parser_pdf_ocr`` (Tesseract chi_sim + eng). v2 is still attempted
  first when ``prefer_v2=True``; OCR is only used as the fallback
  for the scan case (mirrors the ``pdf_inspector.path="ocr"`` branch
  in the spec).
* ``prefer_vision`` (Phase C.3, default ``False``) — when ``True``,
  route the call through ``parser_pdf_vision`` (Qwen-VL-Max
  multimodal LLM) for complex layout PDFs. v2 is still attempted first
  when ``prefer_v2=True``; vision is the fallback for the
  ``pdf_inspector.path="vision"`` decision
  (``text_ratio < 0.2``). Opt-in default — keeps Phase C.1+C.2
  behavior unchanged.

The legacy ``PARSERS`` dispatch is unchanged and remains the single
source of truth for non-PDF formats.

Failure modes:
- ``prefer_v2=False``  → always the original pypdf path.
- ``prefer_v2=True`` + ``parser_pdf_v2`` raises → log a warning and
  fall through to the original pypdf path. Callers never see the
  new failure mode.
- ``prefer_ocr=True`` + Tesseract unavailable or scan inference fails
  → log a warning and fall through to the original pypdf path.
- ``prefer_vision=True`` + Qwen-VL unavailable or API fails
  → log a warning and fall through to the original pypdf path.
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


def load_document(
    path: str | Path,
    *,
    prefer_v2: bool = True,
    prefer_ocr: bool = False,
    prefer_vision: bool = False,
) -> List[dict]:
    """Load ``path`` and return a list of ``{page, text}`` sections.

    Raises ``UnsupportedFormat`` when the extension has no parser, and
    ``FileNotFoundError`` when the path does not exist.

    Parameters
    ----------
    path:
        File to load.
    prefer_v2:
        PDF-only opt-in (Phase C.1). When ``True`` (default), try the
        v2 parser (PyMuPDF + pdfplumber) first and fall back to the
        original pypdf parser on failure. When ``False``, always use
        the original parser. Non-PDF formats ignore this flag.
    prefer_ocr:
        PDF-only opt-in (Phase C.2, default ``False``). When ``True``,
        call ``pdf_inspector`` after the v2 attempt; if the inspector
        decides the document is a scan (``needs_ocr=True``), route the
        call through ``parser_pdf_ocr`` (Tesseract chi_sim + eng).
        The OCR path is *only* used as the fallback for the scan case
        — v2 still gets a chance first when ``prefer_v2=True``.
        Default ``False`` keeps Phase C.1 behavior unchanged.
    prefer_vision:
        PDF-only opt-in (Phase C.3, default ``False``). When ``True``,
        route through ``parser_pdf_vision`` (Qwen-VL-Max multimodal
        LLM) for complex layout PDFs. v2 is still attempted first when
        ``prefer_v2=True``; vision is the fallback for the
        ``pdf_inspector.path="vision"`` decision
        (``text_ratio < 0.2``). Opt-in default keeps Phase C.1+C.2
        behavior unchanged.
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

    # Phase C.2: PDF OCR dispatch (opt-in). When ``prefer_ocr=True``
    # and the inspector decides the document is a scan, route through
    # ``parser_pdf_ocr`` (Tesseract chi_sim + eng). v2 above is still
    # tried first when ``prefer_v2=True``; this branch is the fallback
    # for the ``path == "ocr"`` decision in ``pdf_inspector``. Mirrors
    # INC-005 "0 改 runtime": PARSERS dict is not modified, the new
    # branch lives entirely inside ``load_document``.
    if ext == ".pdf" and prefer_ocr:
        try:
            from app.rag.pdf_inspector import inspect_pdf  # lazy import
            from app.rag.parser_pdf_ocr import (  # lazy import
                PYTESSERACT_AVAILABLE,
                parse_pdf_ocr,
            )

            if not PYTESSERACT_AVAILABLE:
                logger.warning(
                    "prefer_ocr=True but pytesseract not installed; "
                    "falling back to parser_pdf"
                )
            else:
                info = inspect_pdf(p)
                if info.get("needs_ocr"):
                    logger.info(
                        "Using OCR for %s (text_ratio=%s, path=%s)",
                        p.name,
                        info.get("text_ratio"),
                        info.get("path"),
                    )
                    sections = parse_pdf_ocr(p)
                    if sections:
                        return sections
                    logger.info(
                        "parser_pdf_ocr returned empty for %s; "
                        "falling back to parser_pdf",
                        p.name,
                    )
        except FileNotFoundError:
            raise
        except Exception as exc:
            logger.warning(
                "OCR dispatch failed for %s: %s; falling back to parser_pdf",
                p.name,
                exc,
            )

    # Phase C.3: PDF Vision dispatch (opt-in). When ``prefer_vision=True``,
    # call ``pdf_inspector`` after the OCR branch; if the inspector decides
    # the document needs vision (``needs_vision=True``, text_ratio < 0.2),
    # route the call through ``parser_pdf_vision`` (Qwen-VL-Max
    # multimodal LLM). v2 above is still tried first when
    # ``prefer_v2=True``; this branch is the fallback for the
    # ``path == "vision"`` decision in ``pdf_inspector``. Mirrors
    # INC-005 "0 改 runtime": PARSERS dict is not modified, the new
    # branch lives entirely inside ``load_document``.
    if ext == ".pdf" and prefer_vision:
        try:
            from app.rag.pdf_inspector import inspect_pdf  # lazy import
            from app.rag.parser_pdf_vision import parse_pdf_vision  # lazy import

            info = inspect_pdf(p)
            if info.get("needs_vision"):
                logger.info(
                    "Using Qwen-VL-Max for %s (text_ratio=%s, path=%s)",
                    p.name,
                    info.get("text_ratio"),
                    info.get("path"),
                )
                sections = parse_pdf_vision(p)
                if sections:
                    return sections
                logger.info(
                    "parser_pdf_vision returned empty for %s; "
                    "falling back to parser_pdf",
                    p.name,
                )
        except FileNotFoundError:
            raise
        except Exception as exc:
            logger.warning(
                "Vision dispatch failed for %s: %s; falling back to parser_pdf",
                p.name,
                exc,
            )

    parser = PARSERS.get(ext)
    if parser is None:
        raise UnsupportedFormat(f"Unsupported file extension: {ext!r} for {p.name}")
    return parser(p)


class UnsupportedFormat(ValueError):
    """Raised when no parser is registered for the file's extension."""