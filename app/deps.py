"""FastAPI dependencies.

Three flavours of helper live here:

- :func:`get_settings`     -- re-export of ``app.config.get_settings``.
- :func:`get_kb_service_from_state` / :func:`get_retriever_from_state`
  -- pull singletons off the ``app.state`` populated by the lifespan
  handler. Routers should prefer these so we have a single source of
  truth for service instances.
- :func:`get_chat_client_lazy` / :func:`get_embedding_client_lazy` /
  :func:`get_kb_service_lazy` -- *fallback* lazy builders. They exist
  mainly for unit tests / ad-hoc scripts that wire their own ``app``
  without going through the lifespan. The ``lifespan``-based wiring is
  the authoritative source in production.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from fastapi import Request

from app.config import Settings, get_settings as _get_settings

if TYPE_CHECKING:  # pragma: no cover -- import-only hints
    from app.kb.service import KBService
    from app.llm.base import ChatClient, EmbeddingClient
    from app.rag.retriever import Retriever


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def get_settings() -> Settings:
    """FastAPI dependency shim for :func:`app.config.get_settings`."""
    return _get_settings()


# ---------------------------------------------------------------------------
# State-backed getters (preferred in production code)
# ---------------------------------------------------------------------------


def _ensure_app_state(request: Request) -> None:
    """Raise a clear error if the lifespan never populated ``app.state``."""
    if not hasattr(request.app.state, "kb_service"):
        raise RuntimeError(
            "Application state not initialised. "
            "Ensure main.py uses the lifespan-managed app factory."
        )


def get_kb_service_from_state(request: Request) -> "KBService":
    """Return the KBService singleton stored by the lifespan handler."""
    _ensure_app_state(request)
    return request.app.state.kb_service  # type: ignore[no-any-return]


def get_retriever_from_state(request: Request) -> "Retriever":
    """Return the Retriever singleton stored by the lifespan handler."""
    _ensure_app_state(request)
    return request.app.state.retriever  # type: ignore[no-any-return]


def get_chat_client_from_state(request: Request) -> "ChatClient":
    """Return the MiniMaxChatClient singleton stored by the lifespan handler."""
    _ensure_app_state(request)
    return request.app.state.chat_client  # type: ignore[no-any-return]


def get_embedding_client_from_state(request: Request) -> "EmbeddingClient":
    """Return the DashScopeEmbeddingClient singleton stored by lifespan."""
    _ensure_app_state(request)
    return request.app.state.embed_client  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Lazy builders (kept for backward compatibility / standalone scripts)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_chat_client_lazy() -> "ChatClient":
    """Lazy singleton builder for the chat client (use sparingly)."""
    from app.llm.minimax_client import MiniMaxChatClient

    return MiniMaxChatClient(get_settings())


@lru_cache(maxsize=1)
def get_embedding_client_lazy() -> "EmbeddingClient":
    """Lazy singleton builder for the embedding client (use sparingly)."""
    from app.llm.embedding_client import DashScopeEmbeddingClient

    return DashScopeEmbeddingClient(get_settings())


@lru_cache(maxsize=1)
def get_kb_service_lazy() -> "KBService":
    """Lazy singleton builder for KBService (use sparingly)."""
    from app.kb.service import KBService
    from app.kb.storage import SQLiteStorage
    from app.rag.embedder import Embedder
    from app.rag.vectorstore import VectorStore

    settings = get_settings()
    storage = SQLiteStorage(settings)
    vectorstore = VectorStore(settings)
    embedder = Embedder(get_embedding_client_lazy())
    return KBService(storage=storage, vectorstore=vectorstore, embedder=embedder, settings=settings)


# ---------------------------------------------------------------------------
# Public aliases
# ---------------------------------------------------------------------------

# ``get_kb_service`` and ``get_retriever`` are the names routers import.
get_kb_service = get_kb_service_from_state
get_retriever = get_retriever_from_state
get_chat_client = get_chat_client_from_state
get_embedding_client = get_embedding_client_from_state