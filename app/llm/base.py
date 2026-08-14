"""Abstract client protocols for chat and embedding backends.

The concrete classes live in :mod:`app.llm.minimax_client` and
:mod:`app.llm.embedding_client`; tests substitute mocks with
the same interfaces.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence


@dataclass
class ChatResponse:
    """Structured reply from a chat-completion client.

    ``content`` carries the assistant text; ``prompt_tokens`` /
    ``completion_tokens`` / ``total_tokens`` capture the provider's
    usage counters. The token counts are *additive* per call -- the
    quota service sums them to bump ``users.quota_tokens_used``.

    Using a dataclass (instead of returning a bare ``str``) lets the
    caller record usage without re-parsing the OpenAI response, and
    keeps the ``.content`` attribute access back-compatible with the
    old ``str`` return type for any caller that ignores the usage.
    """

    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatClient(ABC):
    """Abstract async chat-completion client."""

    @abstractmethod
    async def achat(
        self,
        messages: Sequence[Mapping[str, str]],
        **kw: Any,
    ) -> ChatResponse:
        """Return the assistant's reply + token usage.

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