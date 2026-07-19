"""DashScope embedding client (Qwen3 text-embedding-v3 via OpenAI-compatible API)."""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable, List

from openai import AsyncOpenAI

from app.config import Settings
from app.llm.base import EmbeddingClient

logger = logging.getLogger(__name__)


class DashScopeEmbeddingClient(EmbeddingClient):
    """Async embedding client for DashScope's OpenAI-compatible endpoint.

    Internal logic:
    - Respects ``embedding.batch_size`` (DashScope allows at most 25 texts/req).
    - Re-chunks inputs into batches and concatenates the results.
    - Light retry on transient errors (one retry, exponential backoff).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=settings.embedding.api_key,
            base_url=settings.embedding.base_url,
            timeout=settings.embedding.timeout,
            max_retries=2,
        )
        self._model = settings.embedding.model
        # DashScope Qwen3-Embedding 硬限: 单次请求 batch size ≤ 10
        # (实际错误: "batch size is invalid, it should not be larger than 10")
        self._batch_size = max(1, min(10, int(settings.embedding.batch_size or 10)))
        self._dim = int(settings.embedding.dim)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def model(self) -> str:
        return self._model

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def batch_size(self) -> int:
        return self._batch_size

    @property
    def raw_client(self) -> AsyncOpenAI:
        return self._client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def aembed(self, texts: List[str]) -> List[List[float]]:
        """Embed ``texts``; returns vectors in the same order."""
        if not texts:
            return []

        all_vectors: List[List[float]] = []
        for batch in _chunks(texts, self._batch_size):
            vectors = await self._embed_one_batch(batch)
            all_vectors.extend(vectors)

        return all_vectors

    async def aembed_iter(self, texts: Iterable[str]) -> List[List[float]]:
        return await self.aembed(list(texts))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _embed_one_batch(self, batch: List[str]) -> List[List[float]]:
        """Embed a single batch with one retry on transient failure."""
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                resp = await self._client.embeddings.create(
                    model=self._model,
                    input=batch,
                )
                return [list(item.embedding) for item in resp.data]
            except Exception as exc:  # pragma: no cover -- network failure path
                last_exc = exc
                logger.warning(
                    "DashScope embed batch failed (attempt %d/2): %s",
                    attempt + 1,
                    exc,
                )
                if attempt == 0:
                    await asyncio.sleep(0.5 * (2**attempt))
        # Exhausted retries
        raise RuntimeError(
            f"DashScope embedding request failed after retries: {last_exc}"
        ) from last_exc


def _chunks(seq: List[str], size: int) -> Iterable[List[str]]:
    """Yield successive ``size``-element chunks from ``seq``."""
    for i in range(0, len(seq), size):
        yield seq[i : i + size]