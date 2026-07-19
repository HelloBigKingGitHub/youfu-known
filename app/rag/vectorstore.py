"""Chroma PersistentClient wrapper.

Each knowledge base maps to a Chroma Collection named ``kb_<kb_id>``.
Embedding dimensionality is fixed by configuration and is verified
against the actual collection dimension at query/upsert time.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from chromadb import PersistentClient
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings as ChromaSettings

from app.config import Settings

logger = logging.getLogger(__name__)


class VectorStore:
    """Thin wrapper around :class:`chromadb.PersistentClient`."""

    def __init__(self, settings: Settings, client: Optional[PersistentClient] = None) -> None:
        self._settings = settings
        self._chroma_dir: Path = settings.chroma_dir_abs()
        self._chroma_dir.mkdir(parents=True, exist_ok=True)
        # Allow injection for tests
        self._client = client or PersistentClient(
            path=str(self._chroma_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        # PersistentClient is shared; protect collection-level mutations.
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Client / collection plumbing
    # ------------------------------------------------------------------

    @property
    def chroma_dir(self) -> Path:
        return self._chroma_dir

    @property
    def raw_client(self) -> PersistentClient:
        return self._client

    @staticmethod
    def collection_name(kb_id: str) -> str:
        if not kb_id:
            raise ValueError("kb_id must be non-empty")
        return f"kb_{kb_id}"

    def get_or_create(self, kb_id: str, dim: int) -> Collection:
        """Return (or create) the Chroma Collection for ``kb_id``."""
        with self._lock:
            return self._client.get_or_create_collection(
                name=self.collection_name(kb_id),
                metadata={"hnsw:space": "cosine", "dim": int(dim)},
            )

    def get_collection(self, kb_id: str) -> Optional[Collection]:
        """Return an existing collection or ``None``."""
        try:
            return self._client.get_collection(self.collection_name(kb_id))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    # ChromaDB has a hard per-call batch limit (default 5461). Chunk
    # large documents so a single .add() never blows it up.
    UPSERT_BATCH = 1000

    def upsert(
        self,
        kb_id: str,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> None:
        """Upsert chunk rows into the KB's collection.

        Splits into chunks of :attr:`UPSERT_BATCH` to stay under
        ChromaDB's per-call limit (5461 ids).
        """
        if not ids:
            return
        if not (len(ids) == len(embeddings) == len(documents) == len(metadatas)):
            raise ValueError(
                "ids, embeddings, documents, metadatas must have equal length"
            )
        col = self.get_or_create(kb_id, dim=len(embeddings[0]))

        n = len(ids)
        for start in range(0, n, self.UPSERT_BATCH):
            end = min(start + self.UPSERT_BATCH, n)
            col.upsert(
                ids=ids[start:end],
                embeddings=embeddings[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )
            logger.info(
                "upsert kb=%s %d/%d chunks", kb_id, end, n,
            )

    def add(
        self,
        kb_id: str,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> None:
        """Alias of :meth:`upsert` for clarity at call sites."""
        self.upsert(kb_id, ids, embeddings, documents, metadatas)

    def query(
        self,
        kb_id: str,
        query_embedding: List[float],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Return the top-k nearest chunks for ``query_embedding``."""
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        col = self.get_collection(kb_id)
        if col is None or col.count() == 0:
            return []

        res = col.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        ids_list = (res.get("ids") or [[]])[0]
        docs_list = (res.get("documents") or [[]])[0]
        metas_list = (res.get("metadatas") or [[]])[0]
        dists_list = (res.get("distances") or [[]])[0]

        results: List[Dict[str, Any]] = []
        for cid, doc, meta, dist in zip(ids_list, docs_list, metas_list, dists_list):
            results.append(
                {
                    "id": cid,
                    "document": doc,
                    "metadata": dict(meta or {}),
                    "distance": float(dist) if dist is not None else None,
                }
            )
        return results

    def delete_by_doc(self, kb_id: str, doc_id: str) -> int:
        """Delete every chunk belonging to ``doc_id`` from ``kb_id``."""
        col = self.get_collection(kb_id)
        if col is None:
            return 0
        with self._lock:
            # ``where`` on Chroma 1.0 uses the raw metadata field name.
            col.delete(where={"doc_id": doc_id})
        return 1

    def delete_collection(self, kb_id: str) -> None:
        """Delete the entire collection for ``kb_id`` (idempotent)."""
        with self._lock:
            try:
                self._client.delete_collection(self.collection_name(kb_id))
            except Exception as exc:
                logger.info(
                    "delete_collection(%s) skipped (likely absent): %s", kb_id, exc
                )

    def list_collection_ids(self) -> List[str]:
        """Return raw Chroma collection names (used in tests)."""
        try:
            return [c.name for c in self._client.list_collections()]
        except Exception:  # pragma: no cover -- depends on Chroma internals
            return []

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def iter_ids(doc_id: str, indices: Iterable[int]) -> List[str]:
        """Format Chroma chunk IDs as ``{doc_id}::{chunk_idx}``."""
        return [f"{doc_id}::{i}" for i in indices]