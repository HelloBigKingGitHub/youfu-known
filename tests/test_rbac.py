"""End-to-end RBAC tests over the HTTP layer.

Two flavours:

- KB visibility: members see only their own KBs + ``is_public=True``
  KBs; admins see everything.
- KB write permissions: a non-owner member gets 403 on patch / delete
  / upload; the owner or an admin gets through.

Each test logs in via the real ``/api/auth/login`` flow and uses the
``session_token`` cookie set by the response.
"""

from __future__ import annotations

from typing import Dict, Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth.models import UserRole
from app.auth.security import hash_password
from app.auth.storage import UserStore


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _login(client: TestClient, username: str, password: str) -> None:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


@pytest.fixture()
def rbac_users(client: TestClient) -> Iterator[Dict[str, Dict[str, str]]]:
    """Seed two members, reuse the bootstrapped admin from lifespan.

    Depends on ``client`` so the lifespan handler has already populated
    ``app.state.user_store`` and created the ``root`` admin. We seed
    alice + bob off that store instead of through ``api_settings`` (which
    would point at a different DB path).
    """
    store: UserStore = client.app.state.user_store  # type: ignore[attr-defined]
    admin = store.get_by_username("root")
    assert admin is not None, "lifespan should have bootstrapped admin"

    alice = store.create_user(
        username="alice",
        password_hash=hash_password("alicepw12", rounds=4),
        role=UserRole.MEMBER,
        is_active=True,
        is_approved=True,
    )
    bob = store.create_user(
        username="bob",
        password_hash=hash_password("bobpw1234", rounds=4),
        role=UserRole.MEMBER,
        is_active=True,
        is_approved=True,
    )
    yield {
        "admin": {"id": admin.id, "username": "root", "password": "rootpw"},
        "alice": {"id": alice.id, "username": "alice", "password": "alicepw12"},
        "bob": {"id": bob.id, "username": "bob", "password": "bobpw1234"},
    }


def _create_kb(client: TestClient, name: str) -> str:
    r = client.post("/api/kbs", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


# ---------------------------------------------------------------------------
# KB visibility
# ---------------------------------------------------------------------------


def test_unauthenticated_cannot_list_kbs(client: TestClient) -> None:
    r = client.get("/api/kbs")
    assert r.status_code == 401


def test_admin_sees_all_kbs(client: TestClient, rbac_users) -> None:
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb")

    _login(client, rbac_users["bob"]["username"], rbac_users["bob"]["password"])
    bob_kb = _create_kb(client, "bob-kb")

    _login(client, rbac_users["admin"]["username"], rbac_users["admin"]["password"])
    listed = {kb["id"] for kb in client.get("/api/kbs").json()["data"]}
    assert alice_kb in listed
    assert bob_kb in listed


def test_member_sees_only_own_and_public_kbs(
    client: TestClient, rbac_users
) -> None:
    # Alice creates a KB; Bob creates a KB and makes his public.
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb")

    _login(client, rbac_users["bob"]["username"], rbac_users["bob"]["password"])
    bob_kb = _create_kb(client, "bob-kb")
    r = client.patch(f"/api/kbs/{bob_kb}", json={"is_public": True})
    assert r.status_code == 200, r.text

    # Alice lists: she sees her own KB + Bob's public one.
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    listed = {kb["id"] for kb in client.get("/api/kbs").json()["data"]}
    assert alice_kb in listed
    assert bob_kb in listed  # because is_public

    # But Alice cannot READ Bob's private KB (make a fresh private one).
    _login(client, rbac_users["bob"]["username"], rbac_users["bob"]["password"])
    private_kb = _create_kb(client, "bob-private")
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    listed = {kb["id"] for kb in client.get("/api/kbs").json()["data"]}
    assert private_kb not in listed
    # And direct fetch is forbidden.
    r = client.get(f"/api/kbs/{private_kb}")
    assert r.status_code == 403


def test_member_cannot_read_other_members_kb(
    client: TestClient, rbac_users
) -> None:
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb")
    _login(client, rbac_users["bob"]["username"], rbac_users["bob"]["password"])
    r = client.get(f"/api/kbs/{alice_kb}")
    assert r.status_code == 403


def test_owner_can_read_own_kb(client: TestClient, rbac_users) -> None:
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb")
    r = client.get(f"/api/kbs/{alice_kb}")
    assert r.status_code == 200


def test_admin_can_read_any_kb(client: TestClient, rbac_users) -> None:
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb")
    _login(client, rbac_users["admin"]["username"], rbac_users["admin"]["password"])
    r = client.get(f"/api/kbs/{alice_kb}")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# KB write permissions
# ---------------------------------------------------------------------------


def test_member_cannot_rename_other_members_kb(
    client: TestClient, rbac_users
) -> None:
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb")
    _login(client, rbac_users["bob"]["username"], rbac_users["bob"]["password"])
    r = client.patch(f"/api/kbs/{alice_kb}", json={"name": "stolen"})
    assert r.status_code == 403


def test_member_cannot_delete_other_members_kb(
    client: TestClient, rbac_users
) -> None:
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb")
    _login(client, rbac_users["bob"]["username"], rbac_users["bob"]["password"])
    r = client.delete(f"/api/kbs/{alice_kb}")
    assert r.status_code == 403


def test_owner_can_rename_and_delete_own_kb(
    client: TestClient, rbac_users
) -> None:
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb")
    r = client.patch(f"/api/kbs/{alice_kb}", json={"name": "renamed"})
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "renamed"
    r = client.delete(f"/api/kbs/{alice_kb}")
    assert r.status_code == 200


def test_admin_can_rename_and_delete_any_kb(
    client: TestClient, rbac_users
) -> None:
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb")
    _login(client, rbac_users["admin"]["username"], rbac_users["admin"]["password"])
    r = client.patch(f"/api/kbs/{alice_kb}", json={"description": "owned"})
    assert r.status_code == 200
    r = client.delete(f"/api/kbs/{alice_kb}")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Document ownership
# ---------------------------------------------------------------------------


def test_member_cannot_upload_to_other_members_kb(
    client: TestClient, rbac_users, sample_txt
) -> None:
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb")
    _login(client, rbac_users["bob"]["username"], rbac_users["bob"]["password"])
    with sample_txt.open("rb") as f:
        r = client.post(
            f"/api/kbs/{alice_kb}/documents",
            files=[("files", ("a.txt", f, "text/plain"))],
        )
    assert r.status_code == 403


def test_member_cannot_list_other_members_documents(
    client: TestClient, rbac_users, sample_txt
) -> None:
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb")
    _login(client, rbac_users["bob"]["username"], rbac_users["bob"]["password"])
    r = client.get(f"/api/kbs/{alice_kb}/documents")
    assert r.status_code == 403


def test_member_cannot_delete_other_members_document(
    client: TestClient, rbac_users, sample_txt
) -> None:
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb")
    with sample_txt.open("rb") as f:
        r = client.post(
            f"/api/kbs/{alice_kb}/documents",
            files=[("files", ("a.txt", f, "text/plain"))],
        )
    assert r.status_code == 201
    doc_id = r.json()["data"]["uploaded"][0]["doc_id"]

    _login(client, rbac_users["bob"]["username"], rbac_users["bob"]["password"])
    r = client.delete(f"/api/kbs/{alice_kb}/documents/{doc_id}")
    assert r.status_code == 403


def test_owner_can_upload_to_own_kb(
    client: TestClient, rbac_users, sample_txt
) -> None:
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb")
    with sample_txt.open("rb") as f:
        r = client.post(
            f"/api/kbs/{alice_kb}/documents",
            files=[("files", ("a.txt", f, "text/plain"))],
        )
    assert r.status_code == 201


def test_admin_can_upload_to_any_kb(
    client: TestClient, rbac_users, sample_txt
) -> None:
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb")
    _login(client, rbac_users["admin"]["username"], rbac_users["admin"]["password"])
    with sample_txt.open("rb") as f:
        r = client.post(
            f"/api/kbs/{alice_kb}/documents",
            files=[("files", ("a.txt", f, "text/plain"))],
        )
    assert r.status_code == 201


# ---------------------------------------------------------------------------
# Chat history isolation
# ---------------------------------------------------------------------------


def test_member_cannot_read_other_members_chat_history(
    client: TestClient, rbac_users, mock_retriever, mock_embedder
) -> None:
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb")
    client.post(f"/api/kbs/{alice_kb}/chat", json={"question": "hi"})

    _login(client, rbac_users["bob"]["username"], rbac_users["bob"]["password"])
    r = client.get(f"/api/kbs/{alice_kb}/chats")
    assert r.status_code == 403


def test_member_cannot_chat_against_other_members_kb(
    client: TestClient, rbac_users, mock_retriever, mock_embedder
) -> None:
    _login(client, rbac_users["alice"]["username"], rbac_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb")
    _login(client, rbac_users["bob"]["username"], rbac_users["bob"]["password"])
    r = client.post(f"/api/kbs/{alice_kb}/chat", json={"question": "hi"})
    assert r.status_code == 403
