"""End-to-end RAG retriever: embed question -> Chroma query -> LLM answer."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.config import Settings
from app.llm.base import ChatClient
from app.rag.embedder import Embedder
from app.rag.vectorstore import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class Citation:
    """A single source citation exposed to the HTTP layer."""

    n: int
    doc_id: str
    doc_filename: str
    chunk_idx: int
    chunk_id: str = ""  # "{doc_id}::{chunk_idx}"
    score: float = 0.0
    text: str = ""


@dataclass
class RagResult:
    """Result of a single RAG turn."""

    answer: str
    citations: List[Citation] = field(default_factory=list)


class Retriever:
    """Glue object: takes a question, returns answer + citations."""

    def __init__(
        self,
        embedder: Embedder,
        vectorstore: VectorStore,
        chat_client: ChatClient,
        settings: Settings,
    ) -> None:
        self._embedder = embedder
        self._vectorstore = vectorstore
        self._chat = chat_client
        self._settings = settings

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def ask(
        self,
        kb_id: str,
        question: str,
        top_k: Optional[int] = None,
    ) -> RagResult:
        """Answer ``question`` using the knowledge base ``kb_id``."""
        if not question or not question.strip():
            raise ValueError("question must be non-empty")
        if not kb_id:
            raise ValueError("kb_id must be non-empty")

        k = int(top_k or self._settings.rag.top_k)

        query_vec = await self._embedder.embed_query(question)
        raw_hits = self._vectorstore.query(kb_id, query_vec, top_k=k)

        citations = self._format_citations(raw_hits)
        context = self._build_context(citations)
        answer = await self._call_llm(question=question, context=context)

        return RagResult(answer=answer, citations=citations)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _format_citations(self, hits: Sequence[Mapping[str, Any]]) -> List[Citation]:
        """Convert raw Chroma hits into :class:`Citation` objects.

        Score is computed as ``1 - distance`` for cosine space
        (Chroma's distance in cosine space is in [0, 2]).
        """
        citations: List[Citation] = []
        for idx, hit in enumerate(hits, start=1):
            meta = hit.get("metadata") or {}
            distance = hit.get("distance")
            try:
                score = 1.0 - float(distance) if distance is not None else 0.0
            except (TypeError, ValueError):
                score = 0.0
            chunk_idx = int(meta.get("chunk_idx", 0) or 0)
            doc_id = str(meta.get("doc_id", ""))
            citations.append(
                Citation(
                    n=idx,
                    doc_id=doc_id,
                    doc_filename=str(meta.get("doc_filename", "")),
                    chunk_idx=chunk_idx,
                    chunk_id=f"{doc_id}::{chunk_idx}" if doc_id else "",
                    score=score,
                    text=str(hit.get("document") or ""),
                )
            )
        return citations

    def _build_context(self, citations: Sequence[Citation]) -> str:
        """Render citations into a numbered, character-bounded context block."""
        if not citations:
            return ""
        max_chars = max(0, int(self._settings.rag.max_context_chars))
        lines: List[str] = []
        budget = max_chars
        for c in citations:
            chunk = c.text or ""
            header = f"[{c.n}] {c.doc_filename}#chunk{c.chunk_idx}"
            block = f"{header}\n{chunk}".strip()
            if budget <= 0:
                break
            if len(block) > budget:
                block = block[:budget]
            lines.append(block)
            budget -= len(block) + 2  # account for trailing blank line
        return "\n\n".join(lines)

    async def _call_llm(self, question: str, context: str) -> str:
        """Send the system+user prompt to the chat client."""
        system_prompt = self._settings.rag.system_prompt
        if context:
            user_content = (
                f"【参考资料】\n{context}\n\n"
                f"【用户问题】\n{question}"
            )
        else:
            user_content = (
                "知识库中目前没有检索到任何相关资料。请直接告知用户"
                "「知识库中没有相关信息」。\n\n"
                f"【用户问题】\n{question}"
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        return await self._chat.achat(messages)