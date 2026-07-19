"""HTML parser (BeautifulSoup).

Strips script/style, then walks top-level body blocks; falls back to
plain text if no blocks are found.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def parse_html(path: str | Path) -> List[dict]:
    """Parse an HTML file; one section per block-level element."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"HTML not found: {p}")
    raw = p.read_text(encoding="utf-8")
    return parse_html_text(raw)


def parse_html_text(text: str) -> List[dict]:
    """Parse raw HTML and return section dicts."""
    if not text.strip():
        return []

    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    sections: List[dict] = []
    # Prefer body if present
    root = soup.body or soup
    for block in root.find_all(
        ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "pre", "blockquote", "tr", "div", "section", "article"],
        recursive=False,
    ):
        text_block = block.get_text(" ", strip=True).strip()
        if text_block:
            sections.append({"page": None, "text": text_block})

    if not sections:
        fallback = soup.get_text("\n\n", strip=True).strip()
        if fallback:
            sections.append({"page": None, "text": fallback})
    return sections