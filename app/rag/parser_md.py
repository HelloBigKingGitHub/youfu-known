"""Markdown parser.

Pipeline: ``markdown -> html -> bs4.get_text`` with paragraph breaks
preserved (``\n\n`` between block-level elements).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

import markdown as md_lib
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def parse_md(path: str | Path) -> List[dict]:
    """Parse a Markdown file and return one section per block element.

    ``page`` is ``None`` (MD is not paginated).
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Markdown not found: {p}")

    raw = p.read_text(encoding="utf-8")
    return parse_md_text(raw)


def parse_md_text(text: str) -> List[dict]:
    """Parse Markdown from a raw string (used by tests)."""
    if not text.strip():
        return []

    html = md_lib.markdown(
        text,
        extensions=["extra", "sane_lists", "tables", "fenced_code"],
        output_format="html",
    )
    soup = BeautifulSoup(html, "html.parser")
    sections: List[dict] = []

    # Iterate top-level blocks so paragraph/list/table boundaries stay intact.
    for block in soup.find_all(
        ["p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "ul", "ol", "table"],
        recursive=False,
    ):
        text_block = _block_text(block).strip()
        if text_block:
            sections.append({"page": None, "text": text_block})

    if not sections:
        # Fallback: grab whatever plain text is there
        fallback = soup.get_text("\n\n", strip=True)
        if fallback:
            sections.append({"page": None, "text": fallback})
    return sections


def _block_text(block) -> str:
    """Render a single block-level element as plain text."""
    name = block.name
    if name == "pre":
        # Preserve code blocks verbatim
        return block.get_text("\n", strip=False).rstrip()
    if name in {"ul", "ol"}:
        items = []
        for i, li in enumerate(block.find_all("li", recursive=False), start=1):
            marker = f"{i}. " if name == "ol" else "- "
            items.append(marker + " ".join(li.get_text(" ", strip=True).split()))
        return "\n".join(items)
    if name == "table":
        rows = []
        for tr in block.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            rows.append(" | ".join(cells))
        return "\n".join(rows)
    return block.get_text(" ", strip=True)