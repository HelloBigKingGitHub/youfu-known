"""PDF parse result cache (SQLite 旁路).

跟 32 commits DDD Theme A "SQLite 旁路" 同款:
- 复用现有 storage (knowledge_base.sqlite3), 新加 ``pdf_cache`` 表
  (sha256 PRIMARY KEY, page_count, ocr_json, vision_json, created_at).
- 不替换现有表; 新表 idempotent migration, 跟 Phase C.1 pdf_inspector
  "0 改 runtime" 同款.
- LRU 清理 (默认 10GB 上限), 跟 32 commits DDD P2.30 partial 修同款.

设计 (Phase PDF-C.2)
--------------------
* **Cache key**: 文件内容 sha256 (跟 32 commits DDD Theme A 双写期
  同款). 跟 path / KB id / doc_id 解耦 — 同样 byte content 不同
  path 自动 dedup (典型场景: 同一份 PDF 上传多 KB).
* **存储 value**: ``ocr_json`` (Tesseract OCR sections) + ``vision_json``
  (Qwen-VL-Max vision sections, 阶段 C.3). 两者**独立**, 一份 PDF 可
  两种 path 都跑 (跟 spec "Pipeline" 同款).
* **LRU 策略**: 按 ``created_at DESC`` 排序, 累加 ``size_bytes``, 超
  过 ``max_size_bytes`` 时删旧的. 跟 32 commits DDD P2.30 partial 修
  "LRU 自动清理" 同款, 但**不**预留 reservation window (Pi 4 装 10GB
  SSD 宽松).
* **持久化**: 单文件 db, 默认 ``<meta_db_dir>/pdf_cache.sqlite3``. 跟
  ``app/kb/storage.py`` 的 SQLite 独立 file, 互不干扰 (跟
  ``app/auth/storage.py`` 同款独立 file).

约束
----
* **0 改** 现有 SQLite schema (新加 ``pdf_cache`` 表).
* **0 改** ``app/kb/storage.py`` 现有 CRUD 方法 (本模块独立).
* 默认 **opt-in** (loader.py 留 placeholder 阶段 C.4 接入).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema (跟 openspec/tasks/pdf-parser-c.md 阶段 C.2 同款)
# ---------------------------------------------------------------------------


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pdf_cache (
    sha256        TEXT PRIMARY KEY,
    doc_id        TEXT,
    page_count    INTEGER,
    ocr_json      TEXT,    -- JSON: list of {page, text, metadata} (阶段 C.2)
    vision_json   TEXT,    -- JSON: list of {page, text, metadata} (阶段 C.3)
    size_bytes    INTEGER,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pdf_cache_created_at ON pdf_cache(created_at);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_CHUNK_SIZE = 8192


def _sha256_file(path: Path) -> str:
    """Compute SHA256 of ``path``'s content (8KB streaming chunks)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class PdfCache:
    """SQLite-backed cache for PDF parse results (sha256 → OCR/vision)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # check_same_thread=False mirrors app/kb/storage.py and
        # app/auth/storage.py: callers may dispatch work via
        # asyncio.to_thread; we serialise writes via the lock.
        self._conn = sqlite3.connect(
            str(self.db_path), check_same_thread=False, isolation_level=None
        )
        self._conn.executescript(SCHEMA_SQL)

    # ------------------------------------------------------------------
    # Read / write
    # ------------------------------------------------------------------

    def get(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Get cached PDF parse result by file sha256.

        Returns ``None`` on miss, else ``{"ocr": [...], "vision": [...]}``
        (each may independently be ``None`` if only one pipeline was
        run for that file).
        """
        sha = _sha256_file(file_path)
        with self._lock:
            cur = self._conn.execute(
                "SELECT ocr_json, vision_json FROM pdf_cache WHERE sha256 = ?",
                (sha,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        try:
            ocr = json.loads(row[0]) if row[0] else None
        except json.JSONDecodeError as exc:
            logger.warning("pdf_cache: corrupt ocr_json for sha=%s: %s", sha, exc)
            ocr = None
        try:
            vision = json.loads(row[1]) if row[1] else None
        except json.JSONDecodeError as exc:
            logger.warning(
                "pdf_cache: corrupt vision_json for sha=%s: %s", sha, exc
            )
            vision = None
        return {"ocr": ocr, "vision": vision}

    def put(
        self,
        file_path: Path,
        ocr_sections: Optional[List[Dict[str, Any]]] = None,
        vision_sections: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Store PDF parse result by file sha256 (INSERT OR REPLACE).

        Returns the computed sha256 so callers can log it.
        """
        sha = _sha256_file(file_path)
        try:
            size = int(file_path.stat().st_size)
        except OSError as exc:
            logger.warning("pdf_cache: stat failed for %s: %s", file_path, exc)
            size = 0
        ocr_json = json.dumps(ocr_sections, ensure_ascii=False) if ocr_sections else None
        vision_json = (
            json.dumps(vision_sections, ensure_ascii=False) if vision_sections else None
        )
        # page_count is the **union** of OCR + vision sections (typical
        # scan PDFs have the same page count in both pipelines).
        page_count = len((ocr_sections or []) + (vision_sections or []))

        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO pdf_cache
                   (sha256, page_count, ocr_json, vision_json, size_bytes)
                   VALUES (?, ?, ?, ?, ?)""",
                (sha, page_count, ocr_json, vision_json, size),
            )
        return sha

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def clear(self) -> int:
        """Clear all cached entries. Returns rows deleted (跟 Theme A P5b purge 同款)."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM pdf_cache")
        return cur.rowcount

    def lru_clean(self, max_size_bytes: int = 10 * 1024**3) -> int:
        """LRU clean: delete oldest entries until total ≤ ``max_size_bytes``.

        Strategy: walk rows ``ORDER BY created_at DESC, rowid DESC``
        (newest first), accumulate ``size_bytes``; **stop** adding to
        ``keep`` as soon as the running total would exceed the cap.
        Anything not in ``keep`` is dropped via a single ``DELETE``
        keyed on ``sha256 NOT IN (...)``.

        Returns the number of rows deleted. The default cap of 10 GB
        matches the spec ``openspec/tasks/pdf-parser-c.md`` §"成本目标".

        Notes
        -----
        ``rowid`` is the SQLite implicit rowid; it is monotonically
        increasing on ``INSERT`` and acts as a stable tiebreaker when
        two rows share the same ``CURRENT_TIMESTAMP`` second.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT sha256, size_bytes FROM pdf_cache "
                "ORDER BY created_at DESC, rowid DESC"
            ).fetchall()

        if not rows:
            return 0

        total = 0
        keep: list[str] = []
        for sha, size in rows:
            running = total + int(size or 0)
            if running > max_size_bytes:
                break
            total = running
            keep.append(sha)

        to_delete = len(rows) - len(keep)
        if to_delete <= 0:
            return 0

        if not keep:
            # Every row crosses the cap on its own — nuke them all.
            with self._lock:
                cur = self._conn.execute("DELETE FROM pdf_cache")
            return cur.rowcount

        with self._lock:
            placeholders = ",".join("?" * len(keep))
            cur = self._conn.execute(
                f"DELETE FROM pdf_cache WHERE sha256 NOT IN ({placeholders})",
                keep,
            )
        return cur.rowcount

    def count(self) -> int:
        """Return the number of cached entries (test / diagnostics helper)."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM pdf_cache").fetchone()
        return int(row[0] if row else 0)


__all__ = ["PdfCache", "_sha256_file", "SCHEMA_SQL"]