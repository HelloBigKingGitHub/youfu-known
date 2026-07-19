"""Recursive character chunker with sliding-window overlap.

Algorithm
---------
For each input section ``{page, text}``:

1. Concatenate section text and prepend a small prefix header (only when
   ``page`` is set, e.g. ``[page 3]``) so the LLM retains page context.
2. Walk separators in priority order (paragraph -> sentence -> word).
   If a segment is still longer than ``chunk_size``, recurse on it with
   the next separator.
3. Once a segment fits, emit it. Adjacent emitted chunks share an
   overlap of up to ``chunk_overlap`` characters: the tail of the
   previous chunk is prepended to the next chunk.
4. Final pass: trim chunks that accidentally grew past ``chunk_size +
   overlap`` by hard-cutting and re-prefixing the remainder.

The chunker preserves the ``page`` from the source section and tracks
the character ``source_offset`` (in original-section coordinates) for
each emitted chunk.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Sequence

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """A single emitted chunk."""

    page: int | None
    source_offset: int
    text: str


class RecursiveChunker:
    """Recursive, separator-aware character chunker with overlap."""

    def __init__(
        self,
        chunk_size: int = 600,
        chunk_overlap: int = 80,
        separators: Sequence[str] | None = None,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap must be non-negative")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be < chunk_size")

        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)
        self.separators: List[str] = list(separators) if separators else [
            "\n\n", "\n", "。", "!", "?", "！", "?", " ", "",
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chunk(self, sections: Iterable[dict]) -> List[Chunk]:
        """Chunk a sequence of ``{page, text}`` sections into :class:`Chunk`."""
        out: List[Chunk] = []
        for section in sections:
            page = section.get("page")
            text = section.get("text") or ""
            if not text.strip():
                continue
            prefix = _page_prefix(page)
            for piece in self._chunk_text(text, prefix=prefix):
                out.append(
                    Chunk(
                        page=page,
                        source_offset=piece["offset"],
                        text=piece["text"],
                    )
                )
        return out

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def _chunk_text(self, text: str, prefix: str = "") -> List[dict]:
        """Split ``text`` into chunks (each ``{offset, text}``)."""
        # 1. Try separator-aware splitting first.
        pieces = self._split_with_separators(text, self.separators)
        # 2. Merge small pieces together until they overflow chunk_size.
        merged = self._merge_with_overlap(pieces, text=text)
        # 3. Hard-cut any chunk still larger than chunk_size + overlap.
        trimmed: List[dict] = []
        for piece in merged:
            trimmed.extend(self._hard_cut(piece, text=text))
        # 4. Prefix and offset finalise.
        result: List[dict] = []
        for piece in trimmed:
            offset = piece["offset"]
            body = piece["text"]
            final_text = (prefix + body) if prefix else body
            result.append({"offset": offset, "text": final_text})
        return result

    # ------------------------------------------------------------------
    # Splitting helpers
    # ------------------------------------------------------------------

    def _split_with_separators(self, text: str, separators: Sequence[str]) -> List[dict]:
        """Recursively split ``text`` so each piece fits ``chunk_size``.

        Returns ``[{offset, text}, ...]`` where offsets are absolute
        character positions in ``text``.
        """
        if not text:
            return []

        if len(text) <= self.chunk_size:
            return [{"offset": 0, "text": text}]

        # Pick the first separator that actually occurs in the text.
        chosen_sep = ""
        chosen_parts: List[str] = []
        for sep in separators:
            if sep == "" or sep is None:
                continue
            if sep in text:
                chosen_sep = sep
                chosen_parts = text.split(sep)
                break

        if not chosen_sep:
            # No further separator helps -> base case, the caller will hard-cut.
            return [{"offset": 0, "text": text}]

        # Re-stitch the separator onto each split part so offsets stay accurate.
        pieces: List[dict] = []
        cursor = 0
        for i, part in enumerate(chosen_parts):
            start = cursor
            end = start + len(part)
            if i < len(chosen_parts) - 1:
                # Reattach the separator that was consumed by split().
                end += len(chosen_sep)
            pieces.append({"offset": start, "text": text[start:end]})
            cursor = end

        # Recurse on any piece that's still too long.
        result: List[dict] = []
        for piece in pieces:
            if len(piece["text"]) > self.chunk_size:
                result.extend(self._split_with_separators(piece["text"], separators[1:]))
            else:
                result.append(piece)
        return result

    def _merge_with_overlap(self, pieces: Sequence[dict], text: str) -> List[dict]:
        """Merge small adjacent pieces into chunks <= chunk_size with overlap."""
        merged: List[dict] = []
        buffer_text = ""
        buffer_offset = 0
        cursor = 0

        def flush() -> None:
            nonlocal buffer_text, buffer_offset
            if buffer_text:
                merged.append({"offset": buffer_offset, "text": buffer_text})
            buffer_text = ""

        for piece in pieces:
            piece_text = piece["text"]
            piece_offset = piece["offset"]

            # If the piece alone is already too large, flush the buffer first
            # and emit the piece by itself (hard-cut handled later).
            if len(piece_text) >= self.chunk_size:
                flush()
                merged.append({"offset": piece_offset, "text": piece_text})
                cursor = piece_offset + len(piece_text)
                buffer_offset = cursor
                continue

            # If appending this piece would overflow, flush and re-add overlap.
            if len(buffer_text) + len(piece_text) > self.chunk_size:
                flush()
                # Build the overlap from the tail of the just-flushed chunk.
                prev = merged[-1]["text"] if merged else ""
                overlap = prev[-self.chunk_overlap :] if self.chunk_overlap > 0 else ""
                buffer_text = overlap
                buffer_offset = (merged[-1]["offset"] + len(merged[-1]["text"]) - len(overlap)) if merged else piece_offset
                # If even with overlap the new piece overflows, we still emit it
                # but only after resetting; the hard-cut pass will trim if needed.
                if len(buffer_text) + len(piece_text) > self.chunk_size:
                    merged.append({"offset": buffer_offset, "text": buffer_text + piece_text})
                    buffer_text = ""
                    cursor = piece_offset + len(piece_text)
                    buffer_offset = cursor
                    continue

            buffer_text += piece_text
            cursor = piece_offset + len(piece_text)

        flush()
        return merged

    def _hard_cut(self, piece: dict, text: str) -> List[dict]:
        """Final safety net: cut chunks longer than chunk_size + overlap."""
        body = piece["text"]
        offset = piece["offset"]
        max_len = self.chunk_size + self.chunk_overlap
        if len(body) <= max_len:
            return [piece]

        stride = self.chunk_size  # advance by a full window to keep overlap meaningful
        out: List[dict] = []
        i = 0
        while i < len(body):
            end = min(i + max_len, len(body))
            out.append({"offset": offset + i, "text": body[i:end]})
            if end == len(body):
                break
            i += stride
        return out


def _page_prefix(page: int | None) -> str:
    """Render a short page header used to give the LLM spatial context."""
    if page is None:
        return ""
    return f"[page {page}] "