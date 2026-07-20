"""Tests for chat history persistence + CRUD endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.jobs.ingest import run_ingest
from app.kb.models import ChatTurn, Citation


# ---------------------------------------------------------------------------
# Storage-level tests (pure SQLite)
# ---------------------------------------------------------------------------


def _make_turn(kb_id: str, qid: str, *, status: str = "ready") -> ChatTurn:
    return ChatTurn(
        id=qid,
        kb_id=kb_id,
        question=f"问题-{qid}",
        answer="" if status == "failed" else f"回答-{qid}",
        error="" if status == "ready" else "boom",
        citations=[
            Citation(
                n=1,
                doc_id="d1",
                doc_filename="a.md",
                chunk_idx=2,
                chunk_id="d1::2",
                score=0.9,
                text="片段",
            )
        ],
        status=status,
        created_at=datetime.utcnow(),
        latency_ms=42,
    )


def test_save_and_get_chat_turn(sqlite_storage):
    kb = sqlite_storage.create_kb(name="kb")
    turn = _make_turn(kb.id, "t1")
    sqlite_storage.save_chat_turn(turn)

    fetched = sqlite_storage.get_chat_turn(kb.id, "t1")
    assert fetched is not None
    assert fetched.id == "t1"
    assert fetched.question == "问题-t1"
    assert fetched.answer == "回答-t1"
    assert fetched.status == "ready"
    assert fetched.latency_ms == 42
    assert fetched.citations[0].chunk_id == "d1::2"


def test_save_chat_turn_records_failure(sqlite_storage):
    kb = sqlite_storage.create_kb(name="kb")
    turn = _make_turn(kb.id, "tfail", status="failed")
    sqlite_storage.save_chat_turn(turn)

    fetched = sqlite_storage.get_chat_turn(kb.id, "tfail")
    assert fetched is not None
    assert fetched.status == "failed"
    assert fetched.answer == ""
    assert fetched.error == "boom"


def test_list_chat_turns_orders_newest_first(sqlite_storage):
    kb = sqlite_storage.create_kb(name="kb")
    sqlite_storage.save_chat_turn(_make_turn(kb.id, "old"))
    sqlite_storage.save_chat_turn(_make_turn(kb.id, "new"))
    turns = sqlite_storage.list_chat_turns(kb.id)
    assert [t.id for t in turns] == ["new", "old"]


def test_list_chat_turns_limit(sqlite_storage):
    kb = sqlite_storage.create_kb(name="kb")
    for i in range(5):
        sqlite_storage.save_chat_turn(_make_turn(kb.id, f"t{i}"))
    out = sqlite_storage.list_chat_turns(kb.id, limit=2)
    assert len(out) == 2


def test_delete_chat_turn(sqlite_storage):
    kb = sqlite_storage.create_kb(name="kb")
    sqlite_storage.save_chat_turn(_make_turn(kb.id, "t1"))
    assert sqlite_storage.delete_chat_turn(kb.id, "t1")
    assert sqlite_storage.get_chat_turn(kb.id, "t1") is None
    # second delete -> False
    assert not sqlite_storage.delete_chat_turn(kb.id, "t1")


def test_clear_chat_turns(sqlite_storage):
    kb = sqlite_storage.create_kb(name="kb")
    for i in range(3):
        sqlite_storage.save_chat_turn(_make_turn(kb.id, f"t{i}"))
    removed = sqlite_storage.clear_chat_turns(kb.id)
    assert removed == 3
    assert sqlite_storage.list_chat_turns(kb.id) == []


def test_delete_kb_cascades_chat_turns(sqlite_storage):
    kb = sqlite_storage.create_kb(name="kb")
    sqlite_storage.save_chat_turn(_make_turn(kb.id, "t1"))
    sqlite_storage.delete_kb(kb.id)
    assert sqlite_storage.get_chat_turn(kb.id, "t1") is None


def test_get_chat_turn_isolation_between_kbs(sqlite_storage):
    a = sqlite_storage.create_kb(name="a")
    b = sqlite_storage.create_kb(name="b")
    sqlite_storage.save_chat_turn(_make_turn(a.id, "ta"))
    sqlite_storage.save_chat_turn(_make_turn(b.id, "tb"))
    assert sqlite_storage.get_chat_turn(a.id, "tb") is None
    assert sqlite_storage.get_chat_turn(b.id, "ta") is None


# ---------------------------------------------------------------------------
# API-level tests (TestClient)
# ---------------------------------------------------------------------------


def _create_kb(client: TestClient, name: str) -> str:
    r = client.post("/api/kbs", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


def test_post_chat_persists_turn(admin_client: TestClient, mock_retriever, mock_embedder):
    """A successful chat call leaves a row in chat_turns."""
    client = admin_client
    kb_id = _create_kb(client, "history-api-1")
    r = client.post(f"/api/kbs/{kb_id}/chat", json={"question": "hi?"})
    assert r.status_code == 200

    listed = client.get(f"/api/kbs/{kb_id}/chats")
    assert listed.status_code == 200
    data = listed.json()["data"]
    assert len(data) == 1
    assert data[0]["question"] == "hi?"
    assert data[0]["status"] == "ready"
    assert data[0]["answer"].startswith("根据资料")
    assert data[0]["latency_ms"] >= 0
    assert data[0]["citations"][0]["chunk_id"] == "doc-abc::3"


def test_post_chat_persists_failure(admin_client: TestClient, mock_embedder):
    """An exception during retrieval also leaves a ``failed`` row."""

    class _BoomRetriever:
        async def ask(self, *args, **kwargs):
            raise RuntimeError("simulated LLM down")

    client = admin_client
    kb_id = _create_kb(client, "history-api-2")
    client.app.state.retriever = _BoomRetriever()

    r = client.post(f"/api/kbs/{kb_id}/chat", json={"question": "kaboom"})
    assert r.status_code == 500

    listed = client.get(f"/api/kbs/{kb_id}/chats")
    rows = listed.json()["data"]
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["error"]
    assert "simulated" in rows[0]["error"]


def test_get_single_chat_turn(admin_client: TestClient, mock_retriever, mock_embedder):
    client = admin_client
    kb_id = _create_kb(client, "history-api-3")
    r = client.post(f"/api/kbs/{kb_id}/chat", json={"question": "what?"})
    assert r.status_code == 200
    turn_id = client.get(f"/api/kbs/{kb_id}/chats").json()["data"][0]["id"]

    detail = client.get(f"/api/kbs/{kb_id}/chats/{turn_id}")
    assert detail.status_code == 200
    body = detail.json()["data"]
    assert body["id"] == turn_id
    assert body["answer"]


def test_get_unknown_chat_turn_returns_404(admin_client: TestClient, mock_retriever):
    client = admin_client
    kb_id = _create_kb(client, "history-api-4")
    r = client.get(f"/api/kbs/{kb_id}/chats/nope")
    assert r.status_code == 404


def test_delete_single_chat_turn(admin_client: TestClient, mock_retriever, mock_embedder):
    client = admin_client
    kb_id = _create_kb(client, "history-api-5")
    client.post(f"/api/kbs/{kb_id}/chat", json={"question": "x"})
    turn_id = client.get(f"/api/kbs/{kb_id}/chats").json()["data"][0]["id"]

    deleted = client.delete(f"/api/kbs/{kb_id}/chats/{turn_id}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] == turn_id
    assert client.get(f"/api/kbs/{kb_id}/chats/{turn_id}").status_code == 404


def test_clear_chat_history_endpoint(admin_client: TestClient, mock_retriever, mock_embedder):
    client = admin_client
    kb_id = _create_kb(client, "history-api-6")
    for q in ("q1", "q2", "q3"):
        client.post(f"/api/kbs/{kb_id}/chat", json={"question": q})
    assert len(client.get(f"/api/kbs/{kb_id}/chats").json()["data"]) == 3

    cleared = client.delete(f"/api/kbs/{kb_id}/chats")
    assert cleared.status_code == 200
    assert cleared.json()["data"]["deleted_count"] == 3
    assert client.get(f"/api/kbs/{kb_id}/chats").json()["data"] == []


def test_history_survives_storage_reinit(
    admin_client: TestClient, mock_retriever, mock_embedder
):
    """Simulating a process restart: drop the in-memory state but keep the
    SQLite file, then re-attach ``app.state.storage`` and confirm the
    chat turn is still visible (this is the e2e persistence check)."""
    client = admin_client
    kb_id = _create_kb(client, "history-api-7")
    client.post(f"/api/kbs/{kb_id}/chat", json={"question": "survive me"})

    # Save the storage singleton, replace with a fresh one pointed at the
    # same DB file. This mimics a service restart.
    from app.kb.storage import SQLiteStorage

    old_storage = client.app.state.storage
    db_path = old_storage.db_path
    settings = client.app.state.settings
    new_storage = SQLiteStorage(settings, db_path=db_path)
    client.app.state.storage = new_storage

    listed = client.get(f"/api/kbs/{kb_id}/chats").json()["data"]
    assert len(listed) == 1
    assert listed[0]["question"] == "survive me"


def test_upload_then_ask_persists_chat(
    admin_client: TestClient, mock_retriever, mock_embedder, sample_txt
):
    """Full E2E: upload docx -> ingest -> ask -> history visible."""
    client = admin_client
    kb_id = _create_kb(client, "history-e2e")
    with sample_txt.open("rb") as f:
        r = client.post(
            f"/api/kbs/{kb_id}/documents",
            files=[("files", ("a.txt", f, "text/plain"))],
        )
    assert r.status_code == 201, r.text
    doc_id = r.json()["data"]["uploaded"][0]["doc_id"]
    asyncio.run(run_ingest(client.app, kb_id, doc_id))

    chat = client.post(f"/api/kbs/{kb_id}/chat", json={"question": "hi"})
    assert chat.status_code == 200
    rows = client.get(f"/api/kbs/{kb_id}/chats").json()["data"]
    assert len(rows) == 1
    assert rows[0]["status"] == "ready"