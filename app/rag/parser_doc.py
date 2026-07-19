"""DOC parser (legacy MS Word binary format, 1997-2003).

Strategy: shell out to ``libreoffice --headless`` to convert ``.doc``
to ``.docx``, then hand off to :mod:`app.rag.parser_docx`. This gives
us the cleanest text extraction (preserves headings, lists, tables) and
reuses the docx chunking path.

Tradeoffs:
* Requires ``libreoffice-core`` + ``libreoffice-writer`` (~200 MB on
  Debian/RPi). Already installed on this Pi.
* Conversion is slow (1-3 s per file). Acceptable for personal use.
* LibreOffice spawns its own user profile (~/.config/libreoffice) on
  first run; we isolate that under a per-process tempdir to avoid lock
  contention when multiple uploads happen in parallel.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


# Hard timeout for a single soffice conversion. Personal use, files
# usually < 5 MB; 60 s is generous.
_CONVERT_TIMEOUT_S = 60


def parse_doc(path: str | Path) -> List[dict]:
    """Extract sections from a legacy ``.doc`` file.

    Returns ``{"page": None, "text": <str>}`` per non-empty paragraph.

    Pipeline:
        1. mkdir tmp, ``soffice --headless --convert-to docx --outdir``
        2. read the generated ``.docx``
        3. delegate to ``parse_docx`` for the actual text extraction
        4. clean up tmp
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"DOC not found: {p}")

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        raise RuntimeError(
            "libreoffice (soffice) not installed. "
            "Run: apt-get install -y libreoffice-core libreoffice-writer"
        )

    # Isolate LibreOffice user profile to /tmp so concurrent calls don't
    # hit the global profile lock.
    with tempfile.TemporaryDirectory(prefix="lo-profile-") as user_profile:
        with tempfile.TemporaryDirectory(prefix="lo-out-") as outdir:
            try:
                proc = subprocess.run(
                    [
                        soffice,
                        f"-env:UserInstallation=file://{user_profile}",
                        "--headless",
                        "--nologo",
                        "--norestore",
                        "--nolockcheck",
                        "--convert-to", "docx",
                        "--outdir", outdir,
                        str(p),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=_CONVERT_TIMEOUT_S,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"libreoffice conversion of {p.name} timed out "
                    f"after {_CONVERT_TIMEOUT_S}s"
                ) from exc

            if proc.returncode != 0:
                # soffice sometimes returns 0 even on success; don't trust
                # returncode alone. Fall through and check output file.
                logger.warning(
                    "soffice returned rc=%d for %s: %s",
                    proc.returncode, p.name, (proc.stderr or "")[:300],
                )

            converted = Path(outdir) / (p.stem + ".docx")
            if not converted.is_file():
                raise RuntimeError(
                    f"libreoffice failed to convert {p.name} to docx. "
                    f"stderr: {(proc.stderr or '')[:500]}"
                )

            # Lazy import to avoid circular dependency
            from app.rag.parser_docx import parse_docx

            try:
                return parse_docx(converted)
            finally:
                # Clean up the converted file (we own it)
                try:
                    converted.unlink(missing_ok=True)
                except Exception:  # pragma: no cover -- best-effort
                    pass