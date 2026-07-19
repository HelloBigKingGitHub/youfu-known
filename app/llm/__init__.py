"""LLM client subpackage.

Exposes thin async wrappers around OpenAI-compatible HTTP APIs.
"""

from app.llm.base import ChatClient, EmbeddingClient
from app.llm.embedding_client import DashScopeEmbeddingClient
from app.llm.minimax_client import MiniMaxChatClient

__all__ = [
    "ChatClient",
    "EmbeddingClient",
    "MiniMaxChatClient",
    "DashScopeEmbeddingClient",
]