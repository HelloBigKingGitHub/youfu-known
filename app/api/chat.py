"""RAG chat endpoint (``POST /api/kbs/{kb_id}/chat``).

Turn persistence is performed here (synchronous, fire-and-await) so the
``chat_turns`` row is committed *before* the HTTP response leaves the
server. Failures from the LLM side are persisted as ``status='failed'``
turns so the operator can audit them.

TODO: streaming is specified in ``openspec/spec.md`` §5.3 but is **not**
implemented in this batch -- the request contract exposes ``stream`` and
we honour ``stream=False`` only. Adding the ``text/event-stream``
response in a follow-up will require an ``AsyncIterator[bytes]`` body
(``StreamingResponse``) and a corresponding client-side fetch wrapper.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api import ok
from app.auth.deps import get_current_user
from app.auth.models import User, UserRole
from app.deps import get_retriever, get_kb_service
from app.kb.models import (
    ChatRequest,
    ChatResponse,
    ChatTurn,
    Citation,
)
from app.kb.service import KBService
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
        "chunk_id": getattr(c, "chunk_id", "") or "",
        "score": c.score,
        "text": c.text,
    }


def _citation_from_dict(d: dict) -> Citation:
    """Build a :class:`Citation` from the on-the-wire dict shape.

    ``chunk_id`` may be missing in old payloads; default to the
    ``{doc_id}::{chunk_idx}`` form so the field is always populated.
    """
    doc_id = str(d.get("doc_id", ""))
    chunk_idx = int(d.get("chunk_idx", 0) or 0)
    chunk_id = str(d.get("chunk_id", "") or f"{doc_id}::{chunk_idx}")
    return Citation(
        n=int(d.get("n", 0) or 0),
        doc_id=doc_id,
        doc_filename=str(d.get("doc_filename", "")),
        chunk_idx=chunk_idx,
        chunk_id=chunk_id,
        score=float(d.get("score", 0.0) or 0.0),
        text=str(d.get("text", "")),
    )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _persist_turn(
    request: Request,
    kb_id: str,
    *,
    question: str,
    result_or_none,
    error: str,
    latency_ms: int,
    user_id: str,
) -> None:
    """Write a chat_turns row mirroring the latest ``/chat`` outcome.

    Best-effort: any failure inside the storage layer is logged and
    swallowed so it never breaks the API contract (the caller still
    gets a JSON response for a successful LLM call).

    ``user_id`` is required: per-user chat history isolation means
    a row without an owner breaks the storage layer's invariant and
    would leak into the per-user view. We surface a loud log so a
    caller that forgot to pass the user is easy to spot in
    production traces.
    """
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        return
    try:
        citations = (
            [_citation_from_dict(_citation_payload(c)) for c in result_or_none.citations]
            if result_or_none is not None
            else []
        )
        answer = result_or_none.answer if result_or_none is not None else ""
        status = "ready" if result_or_none is not None else "failed"
        # ``user_id`` is now part of the persisted row at insert time
        # (the per-user isolation model), so the post-save tagging
        # path that previously lived in the auth layer is gone. The
        # chat endpoint always passes ``user.id``; we treat empty
        # values as a programming error rather than silently stamp
        # the row to "" (which the storage layer would reject anyway).
        if not user_id:
            raise ValueError(
                "_persist_turn called without a user_id; chat history "
                "isolation requires every turn to be attributed"
            )
        turn = ChatTurn(
            id=uuid.uuid4().hex,
            kb_id=kb_id,
            question=question,
            answer=answer,
            error=error or "",
            citations=citations,
            status=status,
            user_id=user_id,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            latency_ms=int(latency_ms or 0),
        )
        storage.save_chat_turn(turn)
    except Exception:  # noqa: BLE001 -- persistence must not break chat
        import logging

        logging.getLogger(__name__).exception(
            "Failed to persist chat turn for kb=%s", kb_id
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/chat")
async def chat(
    kb_id: str,
    body: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    retriever: Retriever = Depends(get_retriever),
    kb_service: KBService = Depends(get_kb_service),
) -> dict:
    """Answer a question against the KB.

    The non-streaming branch (``stream=false``, the default) returns a
    JSON envelope with the full ``answer`` plus the citations that
    backed it. See module docstring for the streaming TODO.
    """
    is_admin = user.role == UserRole.ADMIN
    if not kb_service.user_can_read_kb(kb_id, user.id, is_admin=is_admin):
        raise HTTPException(status_code=403, detail="forbidden")

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

    start = time.monotonic()
    try:
        # ``ValueError`` / ``KBNotFoundError`` bubble to the global handler
        # so the unified ``{code, message}`` envelope is used uniformly.
        result = await retriever.ask(
            kb_id=kb_id,
            question=body.question,
            top_k=body.top_k,
        )
    except Exception as exc:
        latency = int((time.monotonic() - start) * 1000)
        _persist_turn(
            request,
            kb_id,
            question=body.question,
            result_or_none=None,
            error=str(exc),
            latency_ms=latency,
            user_id=user.id,
        )
        raise

    latency = int((time.monotonic() - start) * 1000)
    _persist_turn(
        request,
        kb_id,
        question=body.question,
        result_or_none=result,
        error="",
        latency_ms=latency,
        user_id=user.id,
    )

    response = ChatResponse(
        answer=result.answer,
        citations=[_citation_payload(c) for c in result.citations],
    )
    return ok(response.model_dump())