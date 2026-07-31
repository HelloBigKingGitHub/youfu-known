from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth.models import UserRole
from app.auth.security import hash_password
from app.auth.storage import UserStore
from app.kb.models import ChatTurn, ChunkMeta, DocumentStatus
from app.kb.storage import SQLiteStorage
from app.admin.stats import collect_dashboard_stats


def _set_kb_owner(storage: SQLiteStorage, kb_id: str, owner_id: str, shared: bool) -> None:
    with storage._connect() as conn:  # type: ignore[attr-defined]
        conn.execute(
            "UPDATE knowledge_bases SET owner_id = ?, is_shared = ?, is_public = ? WHERE id = ?",
            (owner_id, int(shared), int(shared), kb_id),
        )
        conn.commit()


def _insert_chunk(storage: SQLiteStorage, kb_id: str, doc_id: str, index: int) -> None:
    storage.save_chunks_batch(
        [
            ChunkMeta(
                id=f"{doc_id}::{index}",
                doc_id=doc_id,
                kb_id=kb_id,
                chunk_idx=index,
                content=f"chunk {index}",
                char_count=7,
                created_at=datetime.utcnow(),
            )
        ]
    )


def _insert_chat(storage: SQLiteStorage, user_id: str, kb_id: str, question: str) -> None:
    storage.save_chat_turn(
        ChatTurn(
            id=uuid4().hex,
            kb_id=kb_id,
            question=question,
            answer="answer",
            status="ready",
            user_id=user_id,
            created_at=datetime.utcnow(),
        )
    )


def test_collect_dashboard_stats_aggregates_real_sqlite_rows(settings) -> None:
    storage = SQLiteStorage(settings)
    storage.init()
    users = UserStore(settings, db_path=storage.db_path)
    users.init()
    admin = users.create_user(
        "admin_stats",
        hash_password("adminpw", rounds=4),
        role=UserRole.ADMIN,
        is_approved=True,
    )
    member = users.create_user(
        "member_stats",
        hash_password("memberpw", rounds=4),
        role=UserRole.MEMBER,
        is_approved=True,
    )

    private_kb = storage.create_kb("private-stats")
    shared_kb = storage.create_kb("shared-stats")
    _set_kb_owner(storage, private_kb.id, member.id, False)
    _set_kb_owner(storage, shared_kb.id, admin.id, True)

    ready_doc = storage.create_document(
        private_kb.id,
        "ready.txt",
        ".txt",
        17,
        str(Path(settings.project_root) / "ready.txt"),
        status=DocumentStatus.READY,
    )
    storage.create_document(
        shared_kb.id,
        "failed.txt",
        ".txt",
        23,
        str(Path(settings.project_root) / "failed.txt"),
        status=DocumentStatus.FAILED,
    )
    _insert_chunk(storage, private_kb.id, ready_doc.id, 0)
    _insert_chunk(storage, private_kb.id, ready_doc.id, 1)
    _insert_chat(storage, admin.id, shared_kb.id, "recent question")

    stats = collect_dashboard_stats(storage, users)

    assert stats["kbs"] == {"total": 2, "shared": 1, "private": 1}
    assert stats["users"] == {"total": 2, "approved": 2, "pending": 0}
    assert stats["documents"]["total"] == 2
    assert stats["documents"]["by_status"]["ready"] == 1
    assert stats["documents"]["by_status"]["failed"] == 1
    assert stats["chunks"] == 2
    assert stats["chat_turns_24h"] == 1
    assert stats["llm_calls_24h"] == 1
    assert stats["storage_bytes"] == 40
    assert stats["uploaded_24h"] == 2


def test_admin_phase1_endpoints_return_expected_envelopes(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login", json={"username": "root", "password": "rootpw"}
    )
    assert response.status_code == 200, response.text

    dashboard = client.get("/api/admin/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["code"] == 0
    assert set(dashboard.json()["data"]) >= {
        "kbs",
        "users",
        "documents",
        "chunks",
        "chat_turns_24h",
        "storage_bytes",
        "llm_calls_24h",
        "uploaded_24h",
    }

    settings = client.get("/api/admin/settings")
    assert settings.status_code == 200, settings.text
    assert settings.json()["data"]["model_name"]
    assert "jwt_secret" not in str(settings.json()["data"])

    patched = client.patch(
        "/api/admin/settings", json={"model_name": "test-runtime-model"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["data"]["model_name"] == "test-runtime-model"

    audit = client.get("/api/admin/audit", params={"limit": 10})
    assert audit.status_code == 200, audit.text
    assert isinstance(audit.json()["data"], list)


def test_admin_kbs_lists_cross_user_and_deletes_any_kb(client: TestClient) -> None:
    login = client.post(
        "/api/auth/login", json={"username": "root", "password": "rootpw"}
    )
    assert login.status_code == 200, login.text
    store: UserStore = client.app.state.user_store  # type: ignore[attr-defined]
    member = store.create_user(
        "member_kb_admin",
        hash_password("memberpw", rounds=4),
        role=UserRole.MEMBER,
        is_approved=True,
    )
    service = client.app.state.kb_service  # type: ignore[attr-defined]
    kb = service.create_kb("member-owned-admin-kb", owner_id=member.id)

    listed = client.get("/api/admin/kbs")
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json()["data"] if item["id"] == kb.id)
    assert row["owner_username"] == "member_kb_admin"

    deleted = client.delete(f"/api/admin/kbs/{kb.id}")
    assert deleted.status_code == 200, deleted.text
    assert client.app.state.storage.get_kb(kb.id) is None  # type: ignore[attr-defined]


def test_admin_phase1_routes_reject_unauthenticated_and_member(client: TestClient) -> None:
    assert client.get("/api/admin/dashboard").status_code == 401

    store: UserStore = client.app.state.user_store  # type: ignore[attr-defined]
    store.create_user(
        "member_gate",
        hash_password("memberpw", rounds=4),
        role=UserRole.MEMBER,
        is_approved=True,
    )
    login = client.post(
        "/api/auth/login", json={"username": "member_gate", "password": "memberpw"}
    )
    assert login.status_code == 200, login.text
    assert client.get("/api/admin/dashboard").status_code == 403
    assert client.get("/api/admin/kbs").status_code == 403
    assert client.get("/api/admin/audit").status_code == 403
    assert client.get("/api/admin/settings").status_code == 403


def test_admin_cors_and_secure_cookie_flags(client: TestClient) -> None:
    preflight = client.options(
        "/api/admin/dashboard",
        headers={
            "Origin": "https://admin.sxy.homes",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://admin.sxy.homes"
    assert preflight.headers["access-control-allow-credentials"] == "true"

    client.app.state.settings.auth.cookie_secure = True  # type: ignore[attr-defined]
    login = client.post(
        "/api/auth/login", json={"username": "root", "password": "rootpw"}
    )
    assert login.status_code == 200, login.text
    set_cookie = login.headers["set-cookie"].lower()
    assert "samesite=none" in set_cookie
    assert "secure" in set_cookie
    # Cookie is scoped to ``.sxy.homes`` so a single login works on
    # every ``*.sxy.homes`` subdomain (kb, admin, future ones).
    assert "domain=.sxy.homes" in set_cookie



def test_settings_patch_validates_chunk_overlap(client: TestClient) -> None:
    login = client.post(
        "/api/auth/login", json={"username": "root", "password": "rootpw"}
    )
    assert login.status_code == 200, login.text
    invalid = client.patch(
        "/api/admin/settings", json={"chunk_size": 10, "chunk_overlap": 10}
    )
    assert invalid.status_code == 400


def test_admin_cors_allows_loopback_dev_origin(client: TestClient) -> None:
    preflight = client.options(
        "/api/admin/dashboard",
        headers={
            "Origin": "http://127.0.0.1:5174",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:5174"


def test_cookie_uses_lax_without_secure_in_dev(client: TestClient) -> None:
    client.app.state.settings.auth.cookie_secure = False  # type: ignore[attr-defined]
    login = client.post(
        "/api/auth/login", json={"username": "root", "password": "rootpw"}
    )
    assert login.status_code == 200, login.text
    set_cookie = login.headers["set-cookie"].lower()
    assert "samesite=lax" in set_cookie
    assert "secure" not in set_cookie


def test_csrf_blocks_state_change_with_unknown_origin(client: TestClient) -> None:
    """A DELETE with a non-allowlisted Origin is rejected with 403.

    Closes the CSRF window opened by SameSite=None + cross-subdomain cookie:
    even if CORS blocks the response from being read, the server still
    processes the request without this check.
    """
    response = client.delete(
        "/api/admin/kbs/some-kb",
        headers={"Origin": "https://evil.example.com"},
    )
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == 403
    assert body["message"] == "invalid origin"


def test_csrf_allows_known_origin(client: TestClient) -> None:
    """A DELETE with an allowlisted Origin reaches the handler.

    Without authentication the auth dependency returns 401 -- the
    middleware lets the request through (not 403), proving the
    allowlist check passed.
    """
    response = client.delete(
        "/api/admin/kbs/does-not-exist",
        headers={"Origin": "https://admin.sxy.homes"},
    )
    assert response.status_code != 403
    assert response.status_code == 401


def test_csrf_allows_missing_origin(client: TestClient) -> None:
    """Same-origin requests (browser omits Origin) are allowed.

    Without authentication, the handler responds 401 rather than 403;
    the request reaches the auth dependency, proving the middleware
    didn't reject it.
    """
    response = client.get("/api/admin/dashboard")
    assert response.status_code == 401
