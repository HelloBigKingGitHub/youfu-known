"""Asynchronous document-ingest job.

Design notes
------------
The FastAPI ``lifespan`` is what gives us access to the process-wide
singleton graph (storage, vectorstore, embedder, kb_service, retriever).
Those objects are stored on ``app.state`` and routes fetch them via the
``app.deps`` module.

For the upload path we want to:

1. Persist the file + insert a ``pending`` row synchronously (so the
   client immediately gets a ``doc_id`` it can poll).
2. Schedule the actual ``load -> chunk -> embed -> upsert`` work as a
   fire-and-forget ``asyncio`` task so the HTTP request returns fast.

That naturally splits into two callables:

- :func:`run_ingest` -- the *synchronous* core; awaits
  ``kb_service.ingest_document`` and writes a ``failed`` status on
  exception. Exposed because tests (and ``recover_interrupted``) want
  to drive it deterministically instead of via ``create_task``.
- :func:`kick_ingest` -- fire-and-forget wrapper used by the API
  route. It captures ``app`` in a closure so the background task can
  pull the live ``kb_service`` off ``app.state`` after the lifespan
  has finished initialising.

Crash recovery is handled by :func:`recover_interrupted`, which the
lifespan handler runs once at startup: it re-kicks every document that
is in ``processing`` state at boot time (the most likely cause being a
process restart in the middle of an ingest).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.kb.models import DocumentStatus

if TYPE_CHECKING:  # pragma: no cover -- import-only hints
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error → status plumbing
# ---------------------------------------------------------------------------


def _mark_failed(app: "FastAPI", kb_id: str, doc_id: str, exc: BaseException) -> None:
    """Persist the failure onto the document row.

    Kept as a top-level (rather than closure-bound) function so it can
    be called from inside :func:`run_ingest` even when the latter is
    driven synchronously by tests.
    """
    kb_service = getattr(app.state, "kb_service", None)
    if kb_service is None:
        logger.error(
            "ingest failed and no kb_service on app.state: doc=%s exc=%r",
            doc_id,
            exc,
        )
        return
    # ``KBService`` exposes its storage as ``_storage`` (the underscore
    # is intentional -- the service treats it as a private collaborator).
    storage = getattr(kb_service, "_storage", None)
    if storage is None:
        logger.error("kb_service has no _storage; cannot mark doc %s failed", doc_id)
        return
    try:
        storage.update_document_status(
            doc_id,
            DocumentStatus.FAILED,
            error=str(exc)[:500],
        )
    except Exception:  # noqa: BLE001 -- status update itself must not blow up
        logger.exception(
            "Failed to persist failure status for doc %s: %r", doc_id, exc
        )


async def run_ingest(app: "FastAPI", kb_id: str, doc_id: str) -> None:
    """Run the document-ingest pipeline for ``doc_id``.

    Looks up ``kb_service`` on ``app.state`` (set by the lifespan handler),
    calls ``kb_service.ingest_document`` and waits for completion. Any
    exception is caught: the document is marked ``failed`` and the
    exception is logged but *not* re-raised (fire-and-forget semantics).
    """
    kb_service = getattr(app.state, "kb_service", None)
    if kb_service is None:
        logger.error("run_ingest called before app.state was initialised")
        return

    try:
        # ``KBService.ingest_document`` is itself synchronous (the pipeline
        # loads/parses/chunks and finally awaits the embedder + Chroma IO
        # inside an ``asyncio.run`` of its own). Calling it with run_in_executor
        # would only add overhead so we just await it directly.
        await asyncio.to_thread(kb_service.ingest_document, kb_id, doc_id)
    except Exception as exc:  # noqa: BLE001 -- surface as failed status
        logger.exception("Ingest failed for doc %s: %s", doc_id, exc)
        _mark_failed(app, kb_id, doc_id, exc)


def kick_ingest(app: "FastAPI", kb_id: str, doc_id: str) -> asyncio.Task:
    """Schedule :func:`run_ingest` as a fire-and-forget asyncio task.

    The returned :class:`asyncio.Task` reference is convenient for tests
    that want to ``await`` the result directly, but production code is
    free to ignore it.
    """
    return asyncio.create_task(run_ingest(app, kb_id, doc_id))


# ---------------------------------------------------------------------------
# Crash recovery (lifespan startup)
# ---------------------------------------------------------------------------


def recover_interrupted(app: "FastAPI") -> int:
    """Re-kick every document stuck in ``processing`` state.

    Returns the number of re-scheduled tasks. Called once during the
    ``lifespan`` startup phase so a process restart in the middle of an
    ingest does not leave the file permanently stuck.
    """
    kb_service = getattr(app.state, "kb_service", None)
    if kb_service is None:
        return 0

    # The service keeps its storage as ``_storage`` (private by design).
    storage = getattr(kb_service, "_storage", None)
    if storage is None:
        return 0

    re_kicked = 0
    try:
        with storage._lock, storage._connect() as conn:
            rows = conn.execute(
                "SELECT id, kb_id FROM documents WHERE status = ?",
                (DocumentStatus.PROCESSING.value,),
            ).fetchall()
    except Exception:  # noqa: BLE001 -- best-effort recovery
        logger.exception("Failed to scan for interrupted ingest jobs")
        return 0

    for row in rows:
        kb_id = row["kb_id"]
        doc_id = row["id"]
        try:
            kick_ingest(app, kb_id, doc_id)
            re_kicked += 1
        except RuntimeError:
            # No running event loop (e.g. called from a sync test harness);
            # the row is simply reset to ``pending`` so a future upload
            # triggers processing.
            logger.warning(
                "Could not re-kick ingest for doc %s (no running loop); "
                "resetting to pending",
                doc_id,
            )
            storage.update_document_status(
                doc_id,
                DocumentStatus.PENDING,
                error="reset-on-recovery",
            )
    if re_kicked:
        logger.info("Recovered %d interrupted ingest job(s)", re_kicked)
    return re_kicked
