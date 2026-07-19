"""Plain-text parser.

Splits on blank lines (``\\n\\n``) and emits each non-empty block as a
section. CRLF and trailing whitespace are normalized first.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

_BLANK_LINE_RE = re.compile(r"\n\s*\n+")


def parse_txt(path: str | Path) -> List[dict]:
    """Parse a plain-text file by paragraph (blank-line separated)."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"TXT not found: {p}")
    raw = p.read_text(encoding="utf-8")
    return parse_txt_text(raw)


def parse_txt_text(text: str) -> List[dict]:
    """Parse a raw text string into sections."""
    if not text.strip():
        return []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    sections: List[dict] = []
    for block in _BLANK_LINE_RE.split(normalized):
        block = block.strip()
        if not block:
            continue
        sections.append({"page": None, "text": block})
    if not sections:
        sections.append({"page": None, "text": normalized.strip()})
    return sections