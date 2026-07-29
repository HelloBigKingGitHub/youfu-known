"""PDF multi-modal parser (Qwen-VL-Max API) for complex layout.

跟 ``parser_pdf.py`` (pypdf) + ``parser_pdf_v2.py`` (PyMuPDF) +
``parser_pdf_ocr.py`` (Tesseract) 并存, **不**替换. loader.py 加
dispatch: ``prefer_vision=True`` 时走 ``parser_pdf_vision``.

Pi 端**不**耗 CPU (网络调用), 你fu 已有 ``DASHSCOPE_API_KEY``, 0 新依赖.

设计 (Phase PDF-C.3, 跟 32 commits DDD Theme B "旁路 adapter" 同款)
-----------------------------------------------------------------
* **PyMuPDF 渲染**: 复用 Phase C.1 已装的 PyMuPDF (``fitz``), 把每页
  渲染成 PNG (默认 ``dpi=200``). Pi 4 native C, ~50ms/页.
* **Qwen-VL-Max API**: DashScope OpenAI 兼容 multimodal endpoint.
  复用现有的 ``DASHSCOPE_API_KEY`` (跟 ``DashScopeEmbeddingClient``
  同源), 0 新接入成本. 1 page ≈ 3-5s (网络, Pi 不耗 CPU).
* **section shape**: 跟 parser_pdf_v2 + parser_pdf_ocr 同款
  ``{page, text, tables, images, metadata:{extractor, model, dpi}}``,
  后续 chunker 无缝接.
* **失败模式**: PyMuPDF 抛 → ``RuntimeError`` (跟 Phase C.1 同款);
  Qwen-VL 单页失败 → log warning + 跳过该页 (跟 INC-005 "per-page
  防御" 同款).

约束 (跟 Phase C.1+C.2 一致)
---------------------------
* **0 改** ``parser_pdf.py`` / ``parser_pdf_v2.py`` / ``parser_pdf_ocr.py``
  (它们是 Hermes 类, 跟 INC-005 "0 改 runtime" 同款).
* **0 改** backend/main.py (lifespan 段不动, 留给 Phase C.4).
* 默认 **opt-in** (loader.py 加 ``prefer_vision=False`` kwarg),
  Phase C.1+C.2 行为完全不变.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Optional imports — fail gracefully when PyMuPDF is missing.
# ---------------------------------------------------------------------------

try:
    import fitz  # type: ignore[import-not-found]  # PyMuPDF

    PYMUPDF_AVAILABLE = True
except ImportError:  # pragma: no cover -- Phase C.1 required dep
    PYMUPDF_AVAILABLE = False
    fitz = None  # type: ignore[assignment]
    logger.warning(
        "PyMuPDF not installed; parser_pdf_vision will raise RuntimeError. "
        "Install with: pip install pymupdf==1.25.5"
    )


# Qwen-VL client import is optional — only required at runtime when
# actually calling the API. Tests inject a mock client directly.
try:
    from app.llm.qwen_vl_client import QwenVLClient

    QWENVL_AVAILABLE = True
except ImportError:  # pragma: no cover -- defensive
    QWENVL_AVAILABLE = False
    QwenVLClient = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Default extraction prompt (跟 spec § C.3 + Theme B "structured output" 同款)
# ---------------------------------------------------------------------------

PROMPT_EXTRACT = """Extract the page as structured markdown:
1. All text in reading order
2. Tables in markdown format
3. Chart/figure descriptions
4. Page header/footer/page numbers
Return clean markdown only, no preamble."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_pdf_vision(
    path: str | Path,
    *,
    dpi: int = 200,
    prompt: str = PROMPT_EXTRACT,
    client: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Parse ``path`` with Qwen-VL-Max multimodal LLM (复杂 layout).

    Steps:
        1. PyMuPDF 渲染每页到 PNG (默认 ``dpi=200``, ~50ms/页).
        2. Qwen-VL-Max API 接收 image + prompt, 返 markdown (~3-5s/页).
        3. 返 sections: ``[{page, text, tables:[], images:[],
            metadata:{extractor:'qwen-vl-max', model, dpi}}]``.

    Parameters
    ----------
    path:
        PDF 文件路径.
    dpi:
        渲染分辨率 (default 200). 越高越慢越准.
    prompt:
        Extraction prompt (default ``PROMPT_EXTRACT``).
    client:
        ``QwenVLClient`` 实例 (用于 test injection). 当 ``None`` 时
        自动从 ``app.config.get_settings()`` 构造.

    Returns
    -------
    list[dict]
        Sections with shape compatible with parser_pdf_v2 / parser_pdf_ocr.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    RuntimeError
        If PyMuPDF is unavailable, or if PyMuPDF fails to open the PDF
        (encrypted / corrupt).
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"PDF not found: {p}")

    if not PYMUPDF_AVAILABLE:
        raise RuntimeError(
            "PyMuPDF not installed; parser_pdf_vision requires it for "
            "page rendering. Install with: pip install pymupdf==1.25.5"
        )

    # Resolve client — test injection or lazy-init from settings.
    if client is None:
        if not QWENVL_AVAILABLE or QwenVLClient is None:
            raise RuntimeError(
                "QwenVLClient not importable; cannot call vision API. "
                "Install httpx (already required) and check app.llm.qwen_vl_client."
            )
        from app.config import get_settings

        client = QwenVLClient(get_settings())

    assert fitz is not None  # guarded by PYMUPDF_AVAILABLE check above
    try:
        doc = fitz.open(str(p))
    except Exception as exc:
        raise RuntimeError(f"Failed to open PDF {p.name}: {exc}") from exc

    sections: List[Dict[str, Any]] = []
    try:
        page_count = doc.page_count
        results = asyncio.run(
            _process_all_pages(client=client, doc=doc, dpi=dpi, prompt=prompt)
        )
        # results is a list parallel to page indices; merge into sections.
        for idx, markdown in enumerate(results, start=1):
            if markdown and markdown.strip():
                sections.append(
                    {
                        "page": idx,
                        "text": markdown.strip(),
                        "tables": [],
                        "images": [],
                        "metadata": {
                            "extractor": "qwen-vl-max",
                            "model": QwenVLClient.MODEL if QwenVLClient is not None else "qwen-vl-max",
                            "dpi": dpi,
                        },
                    }
                )
            # Page skipped (API failure) — log + skip, 不 crash.
        # Hint to readers: page_count is available on doc if callers want it.
        del page_count
    finally:
        doc.close()

    return sections


# ---------------------------------------------------------------------------
# Async helper
# ---------------------------------------------------------------------------


async def _process_all_pages(
    *,
    client: Any,
    doc: Any,
    dpi: int,
    prompt: str,
) -> List[str]:
    """Render + call vision API for every page in ``doc``.

    Returns a list of markdown strings, one per page (empty string means
    the API call failed and the page is dropped downstream). Per-page
    failures are logged but never raise — mirrors Phase C.2 "per-page
    防御" + INC-005 pattern.
    """
    page_count = doc.page_count
    results: List[Optional[str]] = [None] * page_count

    # Sequentially: Qwen-VL has rate limits; concurrent fan-out is left to
    # the upstream KB settings (Phase C.4). One page at a time keeps the
    # client memory footprint predictable on Pi 4.
    for idx in range(1, page_count + 1):
        page = doc.load_page(idx - 1)
        try:
            pix = page.get_pixmap(dpi=dpi)  # type: ignore[attr-defined]
            png_bytes = pix.tobytes("png")
        except Exception as exc:
            logger.warning(
                "PyMuPDF render failed on page %s: %s", idx, exc
            )
            results[idx - 1] = ""
            continue

        try:
            markdown = await client.avision(png_bytes, prompt)
        except Exception as exc:
            logger.warning(
                "Qwen-VL-Max page %s failed: %s (continuing)", idx, exc
            )
            results[idx - 1] = ""
            continue

        results[idx - 1] = markdown

    # Cast None to "" defensively (only triggers if page_count was 0)
    return [r if r is not None else "" for r in results]


__all__ = [
    "parse_pdf_vision",
    "PROMPT_EXTRACT",
    "PYMUPDF_AVAILABLE",
    "QWENVL_AVAILABLE",
]