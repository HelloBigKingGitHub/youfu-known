"""End-to-end HTTP API tests via FastAPI TestClient.

Uses the factory pattern from ``main.create_app()`` so we can point
storage / chroma at a temp dir without polluting the project tree.
LLM calls are monkey-patched so the suite is hermetic.

The async ingest path is driven synchronously by ``await``-ing the
task returned from ``kick_ingest`` -- we don't depend on TestClient's
async quirks.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.kb.models import DocumentStatus


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


def test_kb_lifecycle(admin_client: TestClient) -> None:
    """Create KB -> list -> detail -> delete."""
    create = admin_client.post("/api/kbs", json={"name": "alpha"})
    assert create.status_code == 201, create.text
    kb_id = create.json()["data"]["id"]
    assert kb_id

    listed = admin_client.get("/api/kbs").json()["data"]
    assert any(k["id"] == kb_id for k in listed)

    detail = admin_client.get(f"/api/kbs/{kb_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["kb"]["doc_count"] == 0

    deleted = admin_client.delete(f"/api/kbs/{kb_id}")
    assert deleted.status_code == 200

    missing = admin_client.get(f"/api/kbs/{kb_id}")
    assert missing.status_code == 404
    assert missing.json()["code"] == 404


def test_upload_then_status_then_chat(
    admin_client: TestClient, mock_retriever, mock_embedder
) -> None:
    """Upload a sample, run ingest, wait for ready, ask a question."""
    import asyncio

    from app.jobs.ingest import run_ingest

    client = admin_client
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


def test_chat_rejects_empty_question(admin_client: TestClient, mock_retriever) -> None:
    """Empty question returns 400."""
    kb_id = admin_client.post("/api/kbs", json={"name": "gamma"}).json()["data"]["id"]
    r = admin_client.post(f"/api/kbs/{kb_id}/chat", json={"question": "   "})
    assert r.status_code == 400


def test_chat_rejects_stream(admin_client: TestClient, mock_retriever) -> None:
    """stream=true returns 501 (TODO marker)."""
    kb_id = admin_client.post("/api/kbs", json={"name": "delta"}).json()["data"]["id"]
    r = admin_client.post(f"/api/kbs/{kb_id}/chat", json={"question": "x", "stream": True})
    assert r.status_code == 501


def test_validation_error_envelope(admin_client: TestClient) -> None:
    """Validation errors return our envelope, not FastAPI default."""
    r = admin_client.post("/api/kbs", json={})
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == 400
    assert "message" in body
    assert "detail" in body


def test_get_unknown_kb_returns_404(admin_client: TestClient) -> None:
    r = admin_client.get("/api/kbs/nonexistent-id")
    assert r.status_code == 404
    assert r.json()["code"] == 404


def test_unauthenticated_kb_requests_are_401(client: TestClient) -> None:
    """No login -> 401 on protected endpoints."""
    r = client.get("/api/kbs")
    assert r.status_code == 401
    r = client.post("/api/kbs", json={"name": "x"})
    assert r.status_code == 401