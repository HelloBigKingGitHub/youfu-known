"""KBService: business orchestration of knowledge bases & documents.

Coordinates SQLite metadata, Chroma vector store, the embedder, and
the document-ingest pipeline. All methods are synchronous; the
asyncio wrapper / FastAPI router layer is added in a later batch.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from app.config import Settings
from app.kb.models import (
    ChunkMeta,
    Document,
    DocumentStatus,
    KBDetail,
    KnowledgeBase,
    UploadedFile,
)
from app.kb.storage import SQLiteStorage
from app.rag.chunker import Chunk, RecursiveChunker
from app.rag.embedder import Embedder
from app.rag.loader import UnsupportedFormat, load_document
from app.rag.vectorstore import VectorStore

logger = logging.getLogger(__name__)


class KBServiceError(Exception):
    """Base class for KBService errors."""


class KBNotFoundError(KBServiceError):
    pass


class DocumentNotFoundError(KBServiceError):
    pass


class FileTooLargeError(KBServiceError):
    pass


class KBService:
    """High-level operations for KBs and their documents."""

    def __init__(
        self,
        storage: SQLiteStorage,
        vectorstore: VectorStore,
        embedder: Embedder,
        settings: Settings,
    ) -> None:
        self._storage = storage
        self._vectorstore = vectorstore
        self._embedder = embedder
        self._settings = settings
        self._storage.init()
        # Build a chunker from the same RAG config used at query time.
        self._chunker = RecursiveChunker(
            chunk_size=settings.rag.chunk_size,
            chunk_overlap=settings.rag.chunk_overlap,
            separators=settings.rag.separators,
        )

    # ------------------------------------------------------------------
    # Knowledge-base CRUD
    # ------------------------------------------------------------------

    def create_kb(
        self,
        name: str,
        description: str = "",
        owner_id: Optional[str] = None,
        is_public: bool = False,
    ) -> KnowledgeBase:
        name = (name or "").strip()
        if not name:
            raise ValueError("name must be non-empty")
        kb = self._storage.create_kb(name=name, description=description or "")
        # Stamp ownership + visibility via the user store (owns the auth
        # schema migrations). Doing it through SQLiteStorage would work
        # too, but keeping it here avoids a circular import.
        self._stamp_kb_ownership(kb.id, owner_id, is_public)
        # Pre-create the empty Chroma collection so upload later is fast.
        self._vectorstore.get_or_create(kb.id, dim=self._embedder.dim)
        # Pre-create the per-KB upload directory so cleanup is straightforward.
        self._upload_dir_for_kb(kb.id).mkdir(parents=True, exist_ok=True)
        # Re-read so the returned KB carries the owner / public flags.
        refreshed = self._storage.get_kb(kb.id)
        return refreshed or kb

    def _stamp_kb_ownership(
        self, kb_id: str, owner_id: Optional[str], is_public: bool
    ) -> None:
        """Write owner_id + is_public straight to the SQLite row.

        Uses the storage's own connection (no extra UserStore instance)
        to keep the path zero-allocation in the hot create path.
        """
        with self._storage._connect() as conn:  # type: ignore[attr-defined]
            conn.execute(
                "UPDATE knowledge_bases SET owner_id = ?, is_public = ? WHERE id = ?",
                (owner_id, 1 if is_public else 0, kb_id),
            )
            conn.commit()

    def list_kbs(self) -> List[KnowledgeBase]:
        return self._storage.list_kbs()

    def list_kbs_for_user(
        self, user_id: str, is_admin: bool
    ) -> List[KnowledgeBase]:
        """Return KBs the user is allowed to see.

        Admins see all; members see their own KBs plus any
        ``is_public=True`` KB.
        """
        all_kbs = self._storage.list_kbs()
        if is_admin:
            return all_kbs
        visible_ids = self._kb_visibility_filter(user_id)
        return [kb for kb in all_kbs if kb.id in visible_ids]

    def _kb_visibility_filter(self, user_id: str) -> set:
        """``set[kb_id]`` of KBs the user is allowed to see."""
        with self._storage._connect() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                "SELECT id FROM knowledge_bases "
                "WHERE owner_id = ? OR is_public = 1",
                (user_id,),
            ).fetchall()
            return {r["id"] for r in rows}

    def get_kb_detail(self, kb_id: str) -> KBDetail:
        kb = self._storage.get_kb(kb_id)
        if kb is None:
            raise KBNotFoundError(f"knowledge base not found: {kb_id}")
        docs = self._storage.list_documents(kb_id)
        return KBDetail(kb=kb, documents=docs)

    def kb_owner_and_visibility(
        self, kb_id: str
    ) -> Optional[tuple]:
        """Return ``(owner_id, is_public)`` for ``kb_id`` (or None)."""
        with self._storage._connect() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT owner_id, is_public FROM knowledge_bases WHERE id = ?",
                (kb_id,),
            ).fetchone()
            if row is None:
                return None
            return (row["owner_id"], bool(row["is_public"]))

    def user_can_read_kb(
        self, kb_id: str, user_id: str, is_admin: bool
    ) -> bool:
        if is_admin:
            return True
        info = self.kb_owner_and_visibility(kb_id)
        if info is None:
            return False
        owner_id, is_public = info
        return is_public or owner_id == user_id

    def user_can_write_kb(
        self, kb_id: str, user_id: str, is_admin: bool
    ) -> bool:
        if is_admin:
            return True
        info = self.kb_owner_and_visibility(kb_id)
        if info is None:
            return False
        owner_id, _ = info
        return owner_id == user_id

    def rename_kb(
        self,
        kb_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_public: Optional[bool] = None,
    ) -> KnowledgeBase:
        kb = self._storage.update_kb(kb_id, name=name, description=description)
        if kb is None:
            raise KBNotFoundError(f"knowledge base not found: {kb_id}")
        if is_public is not None:
            with self._storage._connect() as conn:  # type: ignore[attr-defined]
                conn.execute(
                    "UPDATE knowledge_bases SET is_public = ? WHERE id = ?",
                    (1 if is_public else 0, kb_id),
                )
                conn.commit()
            kb = self._storage.get_kb(kb_id) or kb
        return kb

    def delete_kb(self, kb_id: str) -> bool:
        kb = self._storage.get_kb(kb_id)
        if kb is None:
            raise KBNotFoundError(f"knowledge base not found: {kb_id}")
        # 1. Remove all on-disk uploaded files for this KB.
        upload_dir = self._upload_dir_for_kb(kb_id)
        if upload_dir.exists():
            try:
                shutil.rmtree(upload_dir)
            except OSError as exc:
                logger.warning("Failed to remove upload dir %s: %s", upload_dir, exc)
        # 2. Drop the Chroma collection.
        self._vectorstore.delete_collection(kb_id)
        # 3. Remove KB row (cascades to documents).
        return self._storage.delete_kb(kb_id)

    # ------------------------------------------------------------------
    # Document upload
    # ------------------------------------------------------------------

    def upload_document(
        self,
        kb_id: str,
        filename: str,
        ext: str,
        content: bytes,
        owner_id: Optional[str] = None,
    ) -> UploadedFile:
        """Persist an uploaded file and register it as ``pending``.

        ``ext`` must include the leading dot and match an entry in
        ``upload.allowed_extensions``.
        """
        kb = self._storage.get_kb(kb_id)
        if kb is None:
            raise KBNotFoundError(f"knowledge base not found: {kb_id}")

        ext = (ext or "").lower()
        if ext not in self._settings.upload.allowed_extensions:
            raise UnsupportedFormat(f"Extension {ext!r} not allowed")

        max_bytes = int(self._settings.upload.max_file_size_mb) * 1024 * 1024
        if len(content) > max_bytes:
            raise FileTooLargeError(
                f"File {filename!r} exceeds {self._settings.upload.max_file_size_mb} MB"
            )

        # Allocate a doc_id first so we can derive the storage path.
        preview_doc = self._storage.create_document(
            kb_id=kb_id,
            filename=filename,
            ext=ext,
            size_bytes=len(content),
            storage_path="",  # filled in below
            status=DocumentStatus.PENDING,
        )
        storage_path = self._build_storage_path(kb_id, preview_doc.id, ext)
        # Write file
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(content)

        # Patch the storage_path + owner_id columns (status stays pending).
        with self._storage._connect() as conn:  # type: ignore[attr-defined]
            conn.execute(
                "UPDATE documents SET storage_path = ?, owner_id = ? WHERE id = ?",
                (str(storage_path), owner_id, preview_doc.id),
            )
            conn.commit()

        # Bump doc_count exactly once, at upload time. Doing it here (rather
        # than at ingest success) means a re-ingest of the same doc cannot
        # double-count, and the invariant ``doc_count == # of documents in
        # kb`` holds without tracking ``was_ready``. The chunk count is
        # still adjusted by the ingest pipeline so failed parses don't
        # inflate it.
        self._storage.adjust_kb_counts(kb_id, doc_delta=1, chunk_delta=0)

        return UploadedFile(
            doc_id=preview_doc.id,
            filename=filename,
            status=DocumentStatus.PENDING,
        )

    # ------------------------------------------------------------------
    # Document ingest (load -> chunk -> embed -> upsert)
    # ------------------------------------------------------------------

    def ingest_document(self, kb_id: str, doc_id: str) -> Document:
        """Synchronous ingest pipeline. Updates document status as it goes.

        Steps (per ``openspec/spec.md`` §6):
        1. load  (extension-aware parser)
        2. chunk (RecursiveChunker, sliding overlap)
        3. embed (EmbeddingClient, batch <= 25)
        4. upsert (Chroma collection)
        5. mark ready and bump chunk_count by the delta

        On any failure: ``status=failed``, ``error=<message>``,
        KB counters stay untouched. Other documents are unaffected.

        Note: ``doc_count`` is incremented at upload time, not here, so
        re-ingest of an already-counted doc cannot double-count.
        """
        doc = self._storage.get_document(doc_id)
        if doc is None or doc.kb_id != kb_id:
            raise DocumentNotFoundError(
                f"document {doc_id} not found in kb {kb_id}"
            )

        # Capture the previous chunk_count BEFORE we mark PROCESSING so
        # a re-ingest that yields a different chunk_total can adjust the
        # counter by the delta (not the absolute new total).
        prev_chunk_count = int(doc.chunk_count or 0)

        self._storage.update_document_status(
            doc_id, DocumentStatus.PROCESSING, error=""
        )

        try:
            sections = load_document(doc.storage_path)
            if not sections:
                raise RuntimeError("No text could be extracted from the document")

            chunks = self._chunker.chunk(sections)
            if not chunks:
                raise RuntimeError("Chunker produced 0 chunks")

            # Run embedding + upsert in an asyncio loop because
            # AsyncOpenAI requires an event loop.
            import asyncio

            embeddings = asyncio.run(self._embedder.embed_chunks(chunks))
            if len(embeddings) != len(chunks):
                raise RuntimeError(
                    f"Embedding count mismatch: got {len(embeddings)}, expected {len(chunks)}"
                )

            chunk_total = len(chunks)
            ids = self._vectorstore.iter_ids(doc_id, range(chunk_total))
            documents = [c.text for c in chunks]
            metadatas = [
                {
                    "kb_id": kb_id,
                    "doc_id": doc_id,
                    "doc_filename": doc.filename,
                    "chunk_idx": i,
                    "chunk_total": chunk_total,
                    "page": chunks[i].page,
                    "source_offset": chunks[i].source_offset,
                }
                for i in range(chunk_total)
            ]

            self._vectorstore.upsert(
                kb_id,
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )

            # Mirror chunk metadata into SQLite so callers can list /
            # inspect chunks without round-tripping Chroma. ``INSERT OR
            # REPLACE`` makes re-ingest of the same document idempotent.
            chunk_metas: List[ChunkMeta] = []
            running_offset = 0
            for i, chunk in enumerate(chunks):
                text = chunk.text or ""
                cid = ids[i]
                start = int(getattr(chunk, "source_offset", 0) or 0)
                # ``end_offset`` is approximated as the running cursor
                # after the chunk text plus any prefix; this gives the
                # caller a usable range for highlighting / debugging.
                end = start + len(text)
                chunk_metas.append(
                    ChunkMeta(
                        id=cid,
                        doc_id=doc_id,
                        kb_id=kb_id,
                        chunk_idx=i,
                        content=text,
                        char_count=len(text),
                        start_offset=start,
                        end_offset=end,
                        created_at=datetime.utcnow(),
                    )
                )
                running_offset = end
            self._storage.save_chunks_batch(chunk_metas)

            self._storage.update_document_status(
                doc_id,
                DocumentStatus.READY,
                error="",
                chunk_count=chunk_total,
            )
            # Adjust chunk_count by the *delta* so re-ingest that yields a
            # different chunk_total doesn't drift the counter.
            chunk_delta = chunk_total - prev_chunk_count
            self._storage.adjust_kb_counts(
                kb_id, doc_delta=0, chunk_delta=chunk_delta
            )

        except Exception as exc:  # noqa: BLE001 -- surface the message to the UI
            logger.exception("Ingest failed for document %s: %s", doc_id, exc)
            self._storage.update_document_status(
                doc_id, DocumentStatus.FAILED, error=str(exc)[:500]
            )
            raise

        # ``doc_count`` is bumped at upload time, so re-ingest of an
        # already-counted doc is a no-op for that counter. The
        # ``chunk_count`` delta above handles re-ingest of a doc whose
        # chunk count changed between runs.
        refreshed = self._storage.get_document(doc_id)
        assert refreshed is not None
        return refreshed

    # ------------------------------------------------------------------
    # Document lookup / delete
    # ------------------------------------------------------------------

    def list_documents(self, kb_id: str) -> List[Document]:
        kb = self._storage.get_kb(kb_id)
        if kb is None:
            raise KBNotFoundError(f"knowledge base not found: {kb_id}")
        return self._storage.list_documents(kb_id)

    def get_document(self, kb_id: str, doc_id: str) -> Document:
        doc = self._storage.get_document(doc_id)
        if doc is None or doc.kb_id != kb_id:
            raise DocumentNotFoundError(
                f"document {doc_id} not found in kb {kb_id}"
            )
        return doc

    def delete_document(self, kb_id: str, doc_id: str) -> bool:
        doc = self._storage.get_document(doc_id)
        if doc is None or doc.kb_id != kb_id:
            raise DocumentNotFoundError(
                f"document {doc_id} not found in kb {kb_id}"
            )
        # Best-effort: remove vector chunks first.
        self._vectorstore.delete_by_doc(kb_id, doc_id)
        # Mirror chunk deletion into SQLite so the metadata table stays
        # in sync with Chroma. CASCADE on the FK would also handle this,
        # but a manual drop is friendlier to ``adjust_kb_counts`` below.
        self._storage.delete_chunks_for_doc(doc_id)
        # Decrement KB counters (clamped at zero).
        deleted = self._storage.delete_document(doc_id)
        if deleted:
            self._storage.adjust_kb_counts(kb_id, doc_delta=-1, chunk_delta=-doc.chunk_count)
        # Remove the underlying file.
        try:
            p = Path(doc.storage_path)
            if p.is_file():
                p.unlink()
        except OSError as exc:
            logger.warning("Failed to remove file %s: %s", doc.storage_path, exc)
        return deleted

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _upload_dir_for_kb(self, kb_id: str) -> Path:
        return self._settings.upload_dir_abs() / kb_id

    def _build_storage_path(self, kb_id: str, doc_id: str, ext: str) -> Path:
        return self._upload_dir_for_kb(kb_id) / f"{doc_id}{ext}"

    # ------------------------------------------------------------------
    # Convenience: list supported extensions
    # ------------------------------------------------------------------

    @staticmethod
    def supported_extensions() -> Sequence[str]:
        from app.rag.loader import supported_extensions

        return supported_extensions()


__all__ = [
    "KBService",
    "KBServiceError",
    "KBNotFoundError",
    "DocumentNotFoundError",
    "FileTooLargeError",
]