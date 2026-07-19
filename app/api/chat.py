"""RAG chat endpoint (``POST /api/kbs/{kb_id}/chat``).

TODO: streaming is specified in ``openspec/spec.md`` §5.3 but is **not**
implemented in this batch -- the request contract exposes ``stream`` and
we honour ``stream=False`` only. Adding the ``text/event-stream``
response in a follow-up will require an ``AsyncIterator[bytes]`` body
(``StreamingResponse``) and a corresponding client-side fetch wrapper.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api import ok
from app.deps import get_retriever
from app.kb.models import ChatRequest, ChatResponse
from app.rag.retriever import Retriever

router = APIRouter(prefix="/api/kbs/{kb_id}", tags=["chat"])


# ---------------------------------------------------------------------------
# Mappers
# ---------------------------------------------------------------------------


def _citation_payload(c) -> dict:
    return {
        "n": c.n,
        "doc_id": c.doc_id,
        "doc_filename": c.doc_filename,
        "chunk_idx": c.chunk_idx,
        "score": c.score,
        "text": c.text,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/chat")
async def chat(
    kb_id: str,
    body: ChatRequest,
    retriever: Retriever = Depends(get_retriever),
) -> dict:
    """Answer a question against the KB.

    The non-streaming branch (``stream=false``, the default) returns a
    JSON envelope with the full ``answer`` plus the citations that
    backed it. See module docstring for the streaming TODO.
    """
    # Spec allows ``stream=true``; we refuse it politely for now so
    # callers don't get a default binary stream they aren't expecting.
    if body.stream:
        raise HTTPException(
            status_code=501,
            detail="streaming chat not implemented in this build",
        )

    if not body.question or not body.question.strip():
        # ValueError bubbles to the global handler -> uniform envelope.
        raise ValueError("question must be non-empty")

    # ``ValueError`` / ``KBNotFoundError`` bubble to the global handler
    # so the unified ``{code, message}`` envelope is used uniformly.
    result = await retriever.ask(
        kb_id=kb_id,
        question=body.question,
        top_k=body.top_k,
    )

    response = ChatResponse(
        answer=result.answer,
        citations=[_citation_payload(c) for c in result.citations],
    )
    # ``ChatResponse`` is itself already a JSON-friendly pydantic model;
    # round-tripping through ``model_dump`` keeps the wire format
    # centralised (driven by the schema).
    return ok(response.model_dump())
