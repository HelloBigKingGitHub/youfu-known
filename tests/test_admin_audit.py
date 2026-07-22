"""End-to-end tests for the admin chat-audit endpoints.

Admins can read every user's chat history, scoped either by KB
(``/api/admin/kbs/{id}/chats``) or by user across all KBs
(``/api/admin/users/{id}/chats``). Non-admin members get 403.
"""

from __future__ import annotations

from typing import Dict, Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth.models import UserRole
from app.auth.security import hash_password
from app.auth.storage import UserStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login(client: TestClient, username: str, password: str) -> None:
    r = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert r.status_code == 200, r.text


def _create_kb(client: TestClient, name: str) -> str:
    r = client.post("/api/kbs", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


def _chat(client: TestClient, kb_id: str, question: str) -> dict:
    r = client.post(f"/api/kbs/{kb_id}/chat", json={"question": question})
    assert r.status_code == 200, r.text
    return r.json()["data"]


@pytest.fixture()
def audit_users(client: TestClient) -> Iterator[Dict[str, Dict[str, str]]]:
    """Seed alice + bob as members, reuse the bootstrapped admin."""
    store: UserStore = client.app.state.user_store  # type: ignore[attr-defined]
    admin = store.get_by_username("root")
    assert admin is not None
    alice = store.create_user(
        username="alice_audit",
        password_hash=hash_password("alicepw12", rounds=4),
        role=UserRole.MEMBER,
        is_active=True,
        is_approved=True,
    )
    bob = store.create_user(
        username="bob_audit",
        password_hash=hash_password("bobpw1234", rounds=4),
        role=UserRole.MEMBER,
        is_active=True,
        is_approved=True,
    )
    yield {
        "admin": {"id": admin.id, "username": "root", "password": "rootpw"},
        "alice": {
            "id": alice.id,
            "username": "alice_audit",
            "password": "alicepw12",
        },
        "bob": {"id": bob.id, "username": "bob_audit", "password": "bobpw1234"},
    }


# ---------------------------------------------------------------------------
# Audit endpoints
# ---------------------------------------------------------------------------


def test_admin_can_list_every_chat_turn_in_a_kb(
    client: TestClient, audit_users, mock_retriever, mock_embedder
) -> None:
    """Step 12: admin sees turns from every user in a shared KB."""
    # Alice creates a shared KB.
    _login(
        client, audit_users["alice"]["username"], audit_users["alice"]["password"]
    )
    kb_id = _create_kb(client, "shared-for-audit")
    client.patch(f"/api/kbs/{kb_id}", json={"is_shared": True})

    _chat(client, kb_id, "alice-1")
    _chat(client, kb_id, "alice-2")
    _login(client, audit_users["bob"]["username"], audit_users["bob"]["password"])
    _chat(client, kb_id, "bob-1")

    # Admin reads the full audit view.
    _login(
        client, audit_users["admin"]["username"], audit_users["admin"]["password"]
    )
    r = client.get(f"/api/admin/kbs/{kb_id}/chats")
    assert r.status_code == 200
    turns = r.json()["data"]
    questions = {t["question"] for t in turns}
    assert questions == {"alice-1", "alice-2", "bob-1"}
    # user_id is included so the admin can attribute each turn.
    user_ids = {t["user_id"] for t in turns}
    assert audit_users["alice"]["id"] in user_ids
    assert audit_users["bob"]["id"] in user_ids


def test_admin_can_list_every_chat_turn_for_a_user(
    client: TestClient, audit_users, mock_retriever, mock_embedder
) -> None:
    """``/api/admin/users/{id}/chats`` spans all KBs the user touched."""
    _login(
        client, audit_users["alice"]["username"], audit_users["alice"]["password"]
    )
    kb_a = _create_kb(client, "alice-kb-a")
    kb_b = _create_kb(client, "alice-kb-b")
    _chat(client, kb_a, "q-a-1")
    _chat(client, kb_b, "q-b-1")

    _login(
        client, audit_users["admin"]["username"], audit_users["admin"]["password"]
    )
    r = client.get(f"/api/admin/users/{audit_users['alice']['id']}/chats")
    assert r.status_code == 200
    turns = r.json()["data"]
    assert {t["question"] for t in turns} == {"q-a-1", "q-b-1"}
    assert {t["kb_id"] for t in turns} == {kb_a, kb_b}


def test_audit_endpoints_reject_non_admin(
    client: TestClient, audit_users, mock_retriever, mock_embedder
) -> None:
    """A regular member is rejected with HTTP 403 on every audit route."""
    _login(
        client, audit_users["alice"]["username"], audit_users["alice"]["password"]
    )
    kb_id = _create_kb(client, "alice-no-audit")

    r = client.get(f"/api/admin/kbs/{kb_id}/chats")
    assert r.status_code == 403
    r = client.get(f"/api/admin/users/{audit_users['alice']['id']}/chats")
    assert r.status_code == 403


def test_audit_endpoints_require_authentication(
    client: TestClient, audit_users
) -> None:
    """Unauthenticated callers cannot reach admin endpoints either."""
    r = client.get("/api/admin/kbs/anything/chats")
    assert r.status_code == 401
    r = client.get("/api/admin/users/anything/chats")
    assert r.status_code == 401
