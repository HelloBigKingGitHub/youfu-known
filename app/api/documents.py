"""Document upload/lookup/delete endpoints.

All paths live under ``/api/kbs/{kb_id}/documents`` and use the
:class:`app.kb.service.KBService` for storage/vector operations. The
ingest pipeline is kicked off as a fire-and-forget ``asyncio`` task via
:mod:`app.jobs.ingest`; clients poll ``/{doc_id}/status`` to learn when
the document reaches ``ready`` or ``failed``.
"""

from __future__ import annotations

import logging
import os
from typing import List

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)

from app.api import ok
from app.auth.deps import get_current_user
from app.auth.models import User, UserRole
from app.deps import get_kb_service
from app.jobs.ingest import kick_ingest
from app.kb.models import ChunkMeta
from app.kb.service import (
    DocumentNotFoundError,
    FileTooLargeError,
    KBNotFoundError,
    KBService,
    UnsupportedFormat,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/kbs/{kb_id}/documents",
    tags=["documents"],
)


# ---------------------------------------------------------------------------
# Mappers
# ---------------------------------------------------------------------------


def _doc_payload(doc) -> dict:
    return {
        "id": doc.id,
        "kb_id": doc.kb_id,
        "filename": doc.filename,
        "ext": doc.ext,
        "size_bytes": doc.size_bytes,
        "storage_path": doc.storage_path,
        "status": doc.status.value if hasattr(doc.status, "value") else doc.status,
        "error": doc.error,
        "chunk_count": doc.chunk_count,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "processed_at": (
            doc.processed_at.isoformat() if doc.processed_at else None
        ),
    }


def _uploaded_payload(uf) -> dict:
    return {
        "doc_id": uf.doc_id,
        "filename": uf.filename,
        "status": uf.status.value if hasattr(uf.status, "value") else uf.status,
    }


def _chunk_payload(c: ChunkMeta) -> dict:
    return {
        "id": c.id,
        "doc_id": c.doc_id,
        "kb_id": c.kb_id,
        "chunk_idx": c.chunk_idx,
        "content": c.content,
        "char_count": c.char_count,
        "token_estimate": c.token_estimate,
        "start_offset": c.start_offset,
        "end_offset": c.end_offset,
        "created_at": (
            c.created_at.isoformat() if c.created_at else None
        ),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _read_upload(file: UploadFile) -> bytes:
    """Read ``file`` with a hard cap on bytes received.

    Uploads larger than ``upload.max_file_size_mb`` raise an HTTP 413
    *before* we try to persist them. Anything smaller is fine.
    """
    # ``UploadFile.read`` is async; chunking protects us from unbounded
    # memory use on huge payloads.
    chunks: List[bytes] = []
    size = 0
    while True:
        chunk = await file.read(1024 * 1024)  # 1 MiB at a time
        if not chunk:
            break
        size += len(chunk)
        chunks.append(chunk)
    return b"".join(chunks)


def _safe_filename(filename: str) -> str:
    """Best-effort sanitisation of user-supplied filenames.

    Keeps the basename only; strips any path traversal.
    """
    # ``os.path.basename`` handles both POSIX and Windows separators.
    base = os.path.basename(filename or "")
    # Reject empty / dotfiles explicitly to keep things sane on disk.
    if not base or base in (".", ".."):
        return "upload.bin"
    return base


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_documents(
    kb_id: str,
    request: Request,
    files: List[UploadFile] = File(..., description="One or more files to upload"),
    user: User = Depends(get_current_user),
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Upload one or more files into a KB and kick off background ingest.

    The synchronous portion writes the file to ``settings.storage.upload_dir
    / {kb_id} / {doc_id}.{ext}`` and inserts a ``pending`` row per file.
    The ingest pipeline (load -> chunk -> embed -> upsert) is then
    scheduled as an :func:`asyncio.create_task` and the HTTP response
    returns immediately. Clients poll ``/{doc_id}/status`` for progress.

    Only the KB's owner or an admin can upload.
    """
    is_admin = user.role == UserRole.ADMIN
    if not svc.user_can_write_kb(kb_id, user.id, is_admin=is_admin):
        raise HTTPException(status_code=403, detail="forbidden")

    if not files:
        raise HTTPException(status_code=400, detail="no files provided")

    uploaded = []
    for file in files:
        filename = _safe_filename(file.filename or "upload.bin")
        ext = os.path.splitext(filename)[1].lower()
        if not ext:
            ext = ".txt"  # fallback for files like "README"

        content = await _read_upload(file)
        try:
            uf = svc.upload_document(
                kb_id=kb_id,
                filename=filename,
                ext=ext,
                content=content,
                owner_id=user.id,
            )
        except KBNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except UnsupportedFormat as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Fire-and-forget ingest. ``kick_ingest`` captures ``app`` by
        # closure so the background task can pull ``kb_service`` off
        # ``app.state``. The returned task is intentionally not awaited.
        kick_ingest(request.app, kb_id, uf.doc_id)
        uploaded.append(_uploaded_payload(uf))

    return ok({"uploaded": uploaded})


@router.get("")
async def list_documents(
    kb_id: str,
    user: User = Depends(get_current_user),
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """List all documents belonging to ``kb_id`` (read access required)."""
    is_admin = user.role == UserRole.ADMIN
    if not svc.user_can_read_kb(kb_id, user.id, is_admin=is_admin):
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        docs = svc.list_documents(kb_id)
    except KBNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ok([_doc_payload(d) for d in docs])


@router.get("/{doc_id}")
async def document_detail(
    kb_id: str,
    doc_id: str,
    user: User = Depends(get_current_user),
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Return the metadata + processing status of one document."""
    is_admin = user.role == UserRole.ADMIN
    if not svc.user_can_read_kb(kb_id, user.id, is_admin=is_admin):
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        doc = svc.get_document(kb_id, doc_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KBNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ok(_doc_payload(doc))


@router.get("/{doc_id}/status")
async def document_status(
    kb_id: str,
    doc_id: str,
    user: User = Depends(get_current_user),
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Lightweight status poll used by the upload UX."""
    is_admin = user.role == UserRole.ADMIN
    if not svc.user_can_read_kb(kb_id, user.id, is_admin=is_admin):
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        doc = svc.get_document(kb_id, doc_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KBNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ok(
        {
            "doc_id": doc.id,
            "status": doc.status.value if hasattr(doc.status, "value") else doc.status,
            "error": doc.error,
            "chunk_count": doc.chunk_count,
        }
    )


@router.delete("/{doc_id}")
async def delete_document(
    kb_id: str,
    doc_id: str,
    user: User = Depends(get_current_user),
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Remove a document and its associated Chroma chunks (write access)."""
    is_admin = user.role == UserRole.ADMIN
    if not svc.user_can_write_kb(kb_id, user.id, is_admin=is_admin):
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        ok_deleted = svc.delete_document(kb_id, doc_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KBNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not ok_deleted:
        raise HTTPException(status_code=404, detail=f"document not found: {doc_id}")
    return ok({"deleted": doc_id})


@router.get("/{doc_id}/chunks")
async def list_document_chunks(
    kb_id: str,
    doc_id: str,
    request: Request,
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(get_current_user),
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Return chunk metadata for a document, ordered by ``chunk_idx``.

    Debug / re-indexing helper. ``limit`` defaults to 100; ``offset``
    is a plain integer page offset (not a cursor).
    """
    is_admin = user.role == UserRole.ADMIN
    if not svc.user_can_read_kb(kb_id, user.id, is_admin=is_admin):
        raise HTTPException(status_code=403, detail="forbidden")
    # Validate that the document belongs to ``kb_id`` so callers can't
    # probe another KB's chunks by guessing doc_ids.
    try:
        svc.get_document(kb_id, doc_id)
    except (DocumentNotFoundError, KBNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise HTTPException(status_code=500, detail="storage not initialised")
    chunks = storage.list_chunks_for_doc(doc_id, limit=limit, offset=offset)
    return ok([_chunk_payload(c) for c in chunks])


@router.get("/{doc_id}/chunks/{chunk_id}")
async def get_document_chunk(
    kb_id: str,
    doc_id: str,
    chunk_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    svc: KBService = Depends(get_kb_service),
) -> dict:
    """Return a single chunk row (including its full ``content``)."""
    is_admin = user.role == UserRole.ADMIN
    if not svc.user_can_read_kb(kb_id, user.id, is_admin=is_admin):
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        svc.get_document(kb_id, doc_id)
    except (DocumentNotFoundError, KBNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise HTTPException(status_code=500, detail="storage not initialised")
    chunk = storage.get_chunk(chunk_id)
    if chunk is None or chunk.doc_id != doc_id:
        raise HTTPException(
            status_code=404, detail=f"chunk not found: {chunk_id}"
        )
    return ok(_chunk_payload(chunk))
