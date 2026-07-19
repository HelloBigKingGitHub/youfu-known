"""High-level Embedder wrapping an :class:`EmbeddingClient`.

Two entry points:

- :meth:`Embedder.embed_chunks` -- batch-embed a sequence of chunks.
- :meth:`Embedder.embed_query`  -- embed a single user question.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from app.llm.base import EmbeddingClient

logger = logging.getLogger(__name__)


@dataclass
class _Chunk:
    """Lightweight carrier (we accept either :class:`Chunk` or dicts)."""

    text: str

    @classmethod
    def from_any(cls, obj) -> "_Chunk":
        if hasattr(obj, "text"):
            return cls(text=str(obj.text))
        if isinstance(obj, dict) and "text" in obj:
            return cls(text=str(obj["text"]))
        raise TypeError(f"Cannot extract text from {type(obj).__name__}")


class Embedder:
    """Wrap an :class:`EmbeddingClient` with chunk/query convenience methods."""

    def __init__(self, embedding_client: EmbeddingClient) -> None:
        self._client = embedding_client

    @property
    def dim(self) -> int:
        return self._client.dim

    @property
    def client(self) -> EmbeddingClient:
        return self._client

    async def embed_chunks(self, chunks: Sequence | Iterable) -> List[List[float]]:
        """Embed a list of chunks; returns one vector per chunk (same order)."""
        chunks_list = list(chunks)
        if not chunks_list:
            return []
        texts = [_Chunk.from_any(c).text for c in chunks_list]
        return await self._client.aembed(texts)

    async def embed_query(self, text: str) -> List[float]:
        """Embed a single user query and return its vector."""
        if not text or not text.strip():
            raise ValueError("Query text must be non-empty")
        vectors = await self._client.aembed([text])
        return vectors[0]