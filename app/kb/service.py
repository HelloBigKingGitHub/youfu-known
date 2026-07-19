"""KBService: business orchestration of knowledge bases & documents.

Coordinates SQLite metadata, Chroma vector store, the embedder, and
the document-ingest pipeline. All methods are synchronous; the
asyncio wrapper / FastAPI router layer is added in a later batch.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional, Sequence

from app.config import Settings
from app.kb.models import (
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

    def create_kb(self, name: str, description: str = "") -> KnowledgeBase:
        name = (name or "").strip()
        if not name:
            raise ValueError("name must be non-empty")
        kb = self._storage.create_kb(name=name, description=description or "")
        # Pre-create the empty Chroma collection so upload later is fast.
        self._vectorstore.get_or_create(kb.id, dim=self._embedder.dim)
        # Pre-create the per-KB upload directory so cleanup is straightforward.
        self._upload_dir_for_kb(kb.id).mkdir(parents=True, exist_ok=True)
        return kb

    def list_kbs(self) -> List[KnowledgeBase]:
        return self._storage.list_kbs()

    def get_kb_detail(self, kb_id: str) -> KBDetail:
        kb = self._storage.get_kb(kb_id)
        if kb is None:
            raise KBNotFoundError(f"knowledge base not found: {kb_id}")
        docs = self._storage.list_documents(kb_id)
        return KBDetail(kb=kb, documents=docs)

    def rename_kb(
        self,
        kb_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> KnowledgeBase:
        kb = self._storage.update_kb(kb_id, name=name, description=description)
        if kb is None:
            raise KBNotFoundError(f"knowledge base not found: {kb_id}")
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

        # Patch the storage_path column (status stays pending)
        with self._storage._connect() as conn:  # type: ignore[attr-defined]
            conn.execute(
                "UPDATE documents SET storage_path = ? WHERE id = ?",
                (str(storage_path), preview_doc.id),
            )
            conn.commit()

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
        5. mark ready and bump KB counters

        On any failure: ``status=failed``, ``error=<message>``,
        KB counters stay untouched. Other documents are unaffected.
        """
        doc = self._storage.get_document(doc_id)
        if doc is None or doc.kb_id != kb_id:
            raise DocumentNotFoundError(
                f"document {doc_id} not found in kb {kb_id}"
            )

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

            self._storage.update_document_status(
                doc_id,
                DocumentStatus.READY,
                error="",
                chunk_count=chunk_total,
            )
            self._storage.adjust_kb_counts(kb_id, doc_delta=0, chunk_delta=chunk_total)

        except Exception as exc:  # noqa: BLE001 -- surface the message to the UI
            logger.exception("Ingest failed for document %s: %s", doc_id, exc)
            self._storage.update_document_status(
                doc_id, DocumentStatus.FAILED, error=str(exc)[:500]
            )
            raise

        # Refresh doc counters: increment doc_count by exactly 1 (only first success)
        # We keep adjust_kb_counts doc_delta=1 here so a freshly uploaded doc
        # is reflected in the KB's doc_count.
        self._storage.adjust_kb_counts(kb_id, doc_delta=1, chunk_delta=0)

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