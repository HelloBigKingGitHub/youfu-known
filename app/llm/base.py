"""Abstract client protocols for chat and embedding backends.

The concrete classes live in :mod:`app.llm.minimax_client` and
:mod:`app.llm.embedding_client`; tests substitute mocks with
the same interfaces.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Mapping, Sequence


class ChatClient(ABC):
    """Abstract async chat-completion client."""

    @abstractmethod
    async def achat(
        self,
        messages: Sequence[Mapping[str, str]],
        **kw: Any,
    ) -> str:
        """Return the assistant's textual reply.

        Parameters
        ----------
        messages:
            OpenAI-style chat messages (e.g. ``{"role": "user", "content": "..."}``).
        **kw:
            Backend-specific options forwarded to the API
            (e.g. ``temperature``, ``max_tokens``).
        """
        raise NotImplementedError


class EmbeddingClient(ABC):
    """Abstract async embedding client."""

    @property
    @abstractmethod
    def dim(self) -> int:
        """The fixed dimensionality of returned vectors."""

    @abstractmethod
    async def aembed(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts and return their vectors.

        Implementations are responsible for any internal batching
        (e.g. respecting a provider's per-request maximum).
        """
        raise NotImplementedError

    async def aembed_iter(self, texts: Iterable[str]) -> List[List[float]]:
        """Convenience helper: embed an iterable of strings."""
        return await self.aembed(list(texts))