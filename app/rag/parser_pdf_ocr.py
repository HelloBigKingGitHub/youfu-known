"""PDF OCR parser (Tesseract chi_sim + eng) for scan PDFs.

跟 ``parser_pdf.py`` (pypdf, 纯文本) + ``parser_pdf_v2.py`` (PyMuPDF +
pdfplumber, layout-aware) 并存, **不**替换. loader.py 加 dispatch:
``inspector.path == "ocr"`` 时, 走 ``parser_pdf_ocr`` 路径.

设计 (Phase PDF-C.2, 跟 32 commits DDD Theme B "旁路 adapter" 同款)
-----------------------------------------------------------------
* **PyMuPDF 渲染**: 复用 Phase C.1 已装的 PyMuPDF (``fitz``), 把每页
  渲染成 PNG (默认 ``dpi=200``, 越慢越准). Pi 4 native C, ~0.05s/页.
* **pytesseract OCR**: 装 Pi 上跑 ``tesseract --version`` 验. 默认
  ``lang='chi_sim+eng'`` (中文 + 英文 一次跑). Pi 4 1-3s/页.
* **section shape**: 跟 parser_pdf_v2 同款
  ``{page, text, tables, images, metadata:{extractor, lang, dpi}}``,
  后续 chunker 无缝接.
* **失败模式**: PyMuPDF 抛 → fallback ``RuntimeError`` (跟 Phase C.1
  同款); pytesseract 单页失败 → log warning + 跳过该页 (跟 INC-005
  "per-page 防御" 同款).

约束 (跟 Phase C.1 一致)
------------------------
* **0 改** ``parser_pdf.py`` / ``parser_pdf_v2.py`` (它们是 Hermes 类,
  跟 INC-005 "0 改 runtime" 同款).
* **0 改** backend/main.py (lifespan 段不动, 留给 Phase C.4).
* 默认 **opt-in** (loader.py 加 ``prefer_ocr=False`` kwarg), Phase C.1
  行为不变.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Optional imports — fail gracefully when pytesseract is missing.
# ---------------------------------------------------------------------------

try:
    import pytesseract  # type: ignore[import-not-found]
    from PIL import Image  # type: ignore[import-not-found]

    PYTESSERACT_AVAILABLE = True
except ImportError:  # pragma: no cover -- optional dep
    PYTESSERACT_AVAILABLE = False
    pytesseract = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    logger.warning(
        "pytesseract / Pillow not installed; parser_pdf_ocr will raise "
        "RuntimeError. Install with: pip install pytesseract==0.3.13 "
        "Pillow>=10.0.0"
    )


# PyMuPDF is required (Phase C.1 already installed it). We still guard
# so the module can be imported in environments that only have pypdf.
try:
    import fitz  # type: ignore[import-not-found]  # PyMuPDF

    PYMUPDF_AVAILABLE = True
except ImportError:  # pragma: no cover -- required by Phase C.1
    PYMUPDF_AVAILABLE = False
    fitz = None  # type: ignore[assignment]
    logger.warning(
        "PyMuPDF not installed; parser_pdf_ocr requires it for rendering. "
        "Install with: pip install pymupdf==1.25.5"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_pdf_ocr(
    path: str | Path,
    *,
    lang: str = "chi_sim+eng",
    dpi: int = 200,
) -> List[Dict[str, Any]]:
    """Parse ``path`` with Tesseract OCR (扫描件).

    Steps:
        1. PyMuPDF 渲染每页到 PNG (默认 ``dpi=200``).
        2. pytesseract 提取 text (``lang='chi_sim+eng'`` 默认).
        3. 返 sections: ``[{page, text, tables:[], images:[],
            metadata:{extractor:'tesseract', lang, dpi}}]``.

    Parameters
    ----------
    path:
        PDF 文件路径.
    lang:
        Tesseract lang (default ``'chi_sim+eng'`` = 中文 + 英文). 装
        Pi 时 ``apt install tesseract-ocr tesseract-ocr-chi-sim
        tesseract-ocr-eng``.
    dpi:
        渲染分辨率 (default 200). 越高越慢越准; Pi 4 推荐 200-300.

    Returns
    -------
    list[dict]
        Sections with shape compatible with parser_pdf_v2.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    RuntimeError
        If pytesseract / PyMuPDF is unavailable, or PyMuPDF fails to
        open the PDF (encrypted / corrupt).
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"PDF not found: {p}")

    if not PYTESSERACT_AVAILABLE:
        raise RuntimeError(
            "pytesseract not installed; cannot run OCR. "
            "Install with: pip install pytesseract==0.3.13 Pillow>=10.0.0 "
            "and apt install tesseract-ocr tesseract-ocr-chi-sim "
            "tesseract-ocr-eng"
        )

    if not PYMUPDF_AVAILABLE:
        raise RuntimeError(
            "PyMuPDF not installed; parser_pdf_ocr requires it for rendering."
        )

    assert fitz is not None  # guarded by PYMUPDF_AVAILABLE check above
    try:
        doc = fitz.open(str(p))
    except Exception as exc:
        raise RuntimeError(f"Failed to open PDF {p.name}: {exc}") from exc

    sections: List[Dict[str, Any]] = []
    try:
        page_count = doc.page_count
        for idx in range(1, page_count + 1):
            # PyMuPDF is untyped at the Pyright level; mirror parser_pdf_v2.
            page: Any = doc.load_page(idx - 1)

            # Render page to PNG (default dpi=200).
            try:
                pix = page.get_pixmap(dpi=dpi)  # type: ignore[attr-defined]
                assert Image is not None  # guarded by PYTESSERACT_AVAILABLE
                img = Image.frombytes(  # type: ignore[union-attr]
                    "RGB", (pix.width, pix.height), pix.samples
                )
            except Exception as exc:
                logger.warning(
                    "PyMuPDF render failed on page %s of %s: %s",
                    idx,
                    p.name,
                    exc,
                )
                continue

            # OCR (eng + chi_sim). Per-page defensive: one bad page
            # should not abort the whole document (跟 Phase C.1 + INC-005
            # "per-page 防御" 同款).
            try:
                assert pytesseract is not None
                text = pytesseract.image_to_string(img, lang=lang).strip()
            except pytesseract.TesseractError as exc:  # type: ignore[union-attr]
                logger.warning(
                    "Tesseract OCR failed on page %s of %s (lang=%s): %s",
                    idx,
                    p.name,
                    lang,
                    exc,
                )
                text = ""
            except Exception as exc:  # pragma: no cover -- defensive
                logger.warning(
                    "pytesseract.image_to_string raised on page %s of %s: %s",
                    idx,
                    p.name,
                    exc,
                )
                text = ""

            if not text:
                # Empty page — likely a blank scan page. Skip it but
                # don't fail; downstream chunker can't use empty
                # sections anyway.
                continue

            sections.append(
                {
                    "page": idx,
                    "text": text,
                    "tables": [],
                    "images": [],
                    "metadata": {
                        "extractor": "tesseract",
                        "lang": lang,
                        "dpi": dpi,
                    },
                }
            )
    finally:
        doc.close()

    return sections


__all__ = ["parse_pdf_ocr", "PYTESSERACT_AVAILABLE", "PYMUPDF_AVAILABLE"]