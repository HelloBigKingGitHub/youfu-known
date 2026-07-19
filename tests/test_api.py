"""End-to-end HTTP API tests via FastAPI TestClient.

Uses the factory pattern from ``main.create_app()`` so we can point
storage / chroma at a temp dir without polluting the project tree.
LLM calls are monkey-patched so the suite is hermetic.

The async ingest path is driven synchronously by ``await``-ing the
task returned from ``kick_ingest`` -- we don't depend on TestClient's
async quirks.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterator
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.kb.models import (
    DocumentStatus,
)
from app.rag.retriever import Citation, RagResult


# ---------------------------------------------------------------------------
# Settings helper: redirect storage + chroma to a temp dir for each test.
# ---------------------------------------------------------------------------


def _make_settings(project_root: Path, tmp: Path) -> Settings:
    """Build a Settings instance pointing every storage path at ``tmp``.

    ``project_root`` becomes the project root (used by config resolver
    helpers), but all actual data dirs are redirected to ``tmp``.
    """
    cfg_path = project_root / "config.yaml"
    with cfg_path.open() as f:
        cfg = yaml.safe_load(f)

    cfg["storage"]["upload_dir"] = str(tmp / "uploads")
    cfg["storage"]["chroma_dir"] = str(tmp / "chroma")
    cfg["storage"]["meta_db"] = str(tmp / "meta.sqlite3")
    # Inject placeholder API keys so pydantic Settings validate.
    cfg["chat"]["api_key"] = "test-chat-key"
    cfg["embedding"]["api_key"] = "test-embed-key"
    return Settings(project_root=project_root, **cfg)


@pytest.fixture()
def tmp_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    """Provide a Settings with storage redirected to ``tmp_path``.

    Sets ``YOUFU_KNOWN_ROOT`` so ``app.config._resolve_project_root``
    finds the real ``config.yaml`` -- but we override every storage path
    below so no data leaks into the project tree.
    """
    project_root = Path(__file__).resolve().parent.parent
    monkeypatch.setenv("YOUFU_KNOWN_ROOT", str(project_root))
    # Drop any cached singleton so the env-var change takes effect.
    import app.config as config_mod
    config_mod.get_settings.cache_clear()  # type: ignore[attr-defined]

    # Build a fresh settings object with storage redirected to tmp_path.
    import importlib
    importlib.reload(config_mod)

    # Now build a custom settings object with absolute tmp paths and
    # monkeypatch the resolver to return it.
    settings = _make_settings(project_root, tmp_path)
    import app.deps as deps
    monkeypatch.setattr(config_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    return settings


@pytest.fixture()
def client(tmp_storage: Settings) -> Iterator[TestClient]:
    """Spin up the FastAPI app pointed at the temp storage."""
    # Import lazily so monkeypatched get_settings is in effect.
    from main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class _FakeRetriever:
    """Drop-in replacement for Retriever used by the chat endpoint."""

    def __init__(self) -> None:
        self.ask = AsyncMock(
            return_value=RagResult(
                answer="根据资料, MiniMax Embedding 接口地址为 https://api.MiniMax.chat/v1/embeddings [1]。",
                citations=[
                    Citation(
                        n=1,
                        doc_id="doc-abc",
                        doc_filename="minimax_docs.md",
                        chunk_idx=3,
                        score=0.82,
                        text="MiniMax Embedding 接口地址为 https://api.MiniMax.chat/v1/embeddings ...",
                    )
                ],
            )
        )


@pytest.fixture()
def mock_retriever(client: TestClient) -> _FakeRetriever:
    """Swap the lifespan-built retriever with a mock."""
    fake = _FakeRetriever()
    client.app.state.retriever = fake  # type: ignore[attr-defined]
    return fake


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    """GET /api/health returns 200 + ok envelope."""
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "ok"


def test_kb_lifecycle(client: TestClient) -> None:
    """Create KB -> list -> detail -> delete."""
    create = client.post("/api/kbs", json={"name": "alpha"})
    assert create.status_code == 201, create.text
    kb_id = create.json()["data"]["id"]
    assert kb_id

    listed = client.get("/api/kbs").json()["data"]
    assert any(k["id"] == kb_id for k in listed)

    detail = client.get(f"/api/kbs/{kb_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["kb"]["doc_count"] == 0

    deleted = client.delete(f"/api/kbs/{kb_id}")
    assert deleted.status_code == 200

    missing = client.get(f"/api/kbs/{kb_id}")
    assert missing.status_code == 404
    assert missing.json()["code"] == 404


@pytest.fixture()
def mock_embedder(client: TestClient) -> None:
    """Replace the embedding client with one that returns random vectors.

    The Chroma collection persists in tmp_path, so upserting fake
    embeddings is fine -- the test only asserts the pipeline reaches
    READY status, not that retrievals are sensible.
    """
    import random

    class _FakeEmbedClient:
        dim = 1024  # must match real DashScope embedding dim
        model = "fake-embed"

        async def aembed(self, texts):
            import random
            return [[random.random() for _ in range(self.dim)] for _ in texts]

    fake = _FakeEmbedClient()
    client.app.state.embed_client = fake  # type: ignore[attr-defined]
    # KBService holds its own reference to the embedder; swap its inner
    # client too so ingest_document uses the fake.
    embedder = client.app.state.embedder  # type: ignore[attr-defined]
    embedder._client = fake  # type: ignore[attr-defined]


def test_upload_then_status_then_chat(
    client: TestClient, mock_retriever: _FakeRetriever, mock_embedder: None
) -> None:
    """Upload a sample, run ingest, wait for ready, ask a question."""
    kb_id = client.post("/api/kbs", json={"name": "beta"}).json()["data"]["id"]

    sample = Path(__file__).resolve().parent / "samples" / "a.txt"
    with sample.open("rb") as f:
        r = client.post(
            f"/api/kbs/{kb_id}/documents",
            files=[("files", ("a.txt", f, "text/plain"))],
        )
    assert r.status_code == 201, r.text
    doc_id = r.json()["data"]["uploaded"][0]["doc_id"]
    assert doc_id

    # Drive ingest synchronously -- fire-and-forget is hard to drive from
    # the sync TestClient.
    from app.jobs.ingest import run_ingest
    import asyncio

    asyncio.run(run_ingest(client.app, kb_id, doc_id))

    status = client.get(f"/api/kbs/{kb_id}/documents/{doc_id}/status").json()["data"]
    assert status["status"] == DocumentStatus.READY.value, status
    assert status["chunk_count"] >= 1

    # Ask a question -- retriever is mocked.
    chat = client.post(
        f"/api/kbs/{kb_id}/chat",
        json={"question": "MiniMax Embedding 接口地址是?", "top_k": 3},
    )
    assert chat.status_code == 200, chat.text
    body = chat.json()["data"]
    assert body["answer"]
    assert len(body["citations"]) >= 1
    assert body["citations"][0]["doc_filename"]


def test_chat_rejects_empty_question(client: TestClient, mock_retriever: _FakeRetriever) -> None:
    """Empty question returns 400."""
    kb_id = client.post("/api/kbs", json={"name": "gamma"}).json()["data"]["id"]
    r = client.post(f"/api/kbs/{kb_id}/chat", json={"question": "   "})
    assert r.status_code == 400


def test_chat_rejects_stream(client: TestClient, mock_retriever: _FakeRetriever) -> None:
    """stream=true returns 501 (TODO marker)."""
    kb_id = client.post("/api/kbs", json={"name": "delta"}).json()["data"]["id"]
    r = client.post(f"/api/kbs/{kb_id}/chat", json={"question": "x", "stream": True})
    assert r.status_code == 501


def test_validation_error_envelope(client: TestClient) -> None:
    """Validation errors return our envelope, not FastAPI default."""
    r = client.post("/api/kbs", json={})
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == 400
    assert "message" in body
    assert "detail" in body


def test_get_unknown_kb_returns_404(client: TestClient) -> None:
    r = client.get("/api/kbs/nonexistent-id")
    assert r.status_code == 404
    assert r.json()["code"] == 404