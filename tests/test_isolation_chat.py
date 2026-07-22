"""End-to-end tests for per-user chat history isolation.

Even on a shared KB, two users' question/answer history is split:
each user only sees (and can fetch, delete) their own turns. The
admin audit endpoint under ``/api/admin`` is the only way to
cross the boundary.
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


@pytest.fixture()
def iso_users(client: TestClient) -> Iterator[Dict[str, Dict[str, str]]]:
    """Seed alice + bob as members, reuse the bootstrapped admin."""
    store: UserStore = client.app.state.user_store  # type: ignore[attr-defined]
    admin = store.get_by_username("root")
    assert admin is not None
    alice = store.create_user(
        username="alice_chat",
        password_hash=hash_password("alicepw12", rounds=4),
        role=UserRole.MEMBER,
        is_active=True,
        is_approved=True,
    )
    bob = store.create_user(
        username="bob_chat",
        password_hash=hash_password("bobpw1234", rounds=4),
        role=UserRole.MEMBER,
        is_active=True,
        is_approved=True,
    )
    yield {
        "admin": {"id": admin.id, "username": "root", "password": "rootpw"},
        "alice": {
            "id": alice.id,
            "username": "alice_chat",
            "password": "alicepw12",
        },
        "bob": {"id": bob.id, "username": "bob_chat", "password": "bobpw1234"},
    }


# ---------------------------------------------------------------------------
# Per-user isolation on a shared KB
# ---------------------------------------------------------------------------


def _create_shared_kb_with_doc(
    client: TestClient,
    owner: Dict[str, str],
    name: str,
    other: Dict[str, str],
    mock_retriever,
    mock_embedder,
) -> str:
    """Create a shared KB (with one uploaded doc for retriever sanity)
    and return its id."""
    _login(client, owner["username"], owner["password"])
    kb_id = _create_kb(client, name)
    r = client.patch(f"/api/kbs/{kb_id}", json={"is_shared": True})
    assert r.status_code == 200
    return kb_id


def test_chat_turn_carries_current_user_id(
    client: TestClient, iso_users, mock_retriever, mock_embedder
) -> None:
    """Each chat turn is stamped with the user that asked the question."""
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    kb_id = _create_kb(client, "chat-user-stamp")
    r = client.post(f"/api/kbs/{kb_id}/chat", json={"question": "who?"})
    assert r.status_code == 200
    listed = client.get(f"/api/kbs/{kb_id}/chats").json()["data"]
    assert len(listed) == 1
    assert listed[0]["user_id"] == iso_users["alice"]["id"]


def test_users_see_only_their_own_chat_history(
    client: TestClient, iso_users, mock_retriever, mock_embedder
) -> None:
    """On a shared KB, alice and bob see only their own turns."""
    kb_id = _create_shared_kb_with_doc(
        client,
        iso_users["alice"],
        "shared-kb-history",
        iso_users["bob"],
        mock_retriever,
        mock_embedder,
    )

    # Alice asks two questions.
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    client.post(f"/api/kbs/{kb_id}/chat", json={"question": "alice-1"})
    client.post(f"/api/kbs/{kb_id}/chat", json={"question": "alice-2"})

    # Bob asks one question.
    _login(client, iso_users["bob"]["username"], iso_users["bob"]["password"])
    client.post(f"/api/kbs/{kb_id}/chat", json={"question": "bob-1"})

    # Each user only sees their own.
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    alice_turns = client.get(f"/api/kbs/{kb_id}/chats").json()["data"]
    assert {t["question"] for t in alice_turns} == {"alice-1", "alice-2"}

    _login(client, iso_users["bob"]["username"], iso_users["bob"]["password"])
    bob_turns = client.get(f"/api/kbs/{kb_id}/chats").json()["data"]
    assert {t["question"] for t in bob_turns} == {"bob-1"}


def test_get_other_users_turn_returns_404(
    client: TestClient, iso_users, mock_retriever, mock_embedder
) -> None:
    """Bob cannot read Alice's chat turn even by guessing the id."""
    kb_id = _create_shared_kb_with_doc(
        client,
        iso_users["alice"],
        "shared-kb-no-peek",
        iso_users["bob"],
        mock_retriever,
        mock_embedder,
    )
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    client.post(f"/api/kbs/{kb_id}/chat", json={"question": "alice-secret"})
    alice_turn_id = client.get(f"/api/kbs/{kb_id}/chats").json()["data"][0]["id"]

    _login(client, iso_users["bob"]["username"], iso_users["bob"]["password"])
    r = client.get(f"/api/kbs/{kb_id}/chats/{alice_turn_id}")
    assert r.status_code == 404


def test_delete_other_users_turn_returns_404(
    client: TestClient, iso_users, mock_retriever, mock_embedder
) -> None:
    """Bob cannot delete Alice's chat turn either."""
    kb_id = _create_shared_kb_with_doc(
        client,
        iso_users["alice"],
        "shared-kb-no-delete",
        iso_users["bob"],
        mock_retriever,
        mock_embedder,
    )
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    client.post(f"/api/kbs/{kb_id}/chat", json={"question": "alice-keepme"})
    alice_turn_id = client.get(f"/api/kbs/{kb_id}/chats").json()["data"][0]["id"]

    _login(client, iso_users["bob"]["username"], iso_users["bob"]["password"])
    r = client.delete(f"/api/kbs/{kb_id}/chats/{alice_turn_id}")
    assert r.status_code == 404

    # And the turn is still there for Alice.
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    listing = client.get(f"/api/kbs/{kb_id}/chats").json()["data"]
    assert {t["id"] for t in listing} == {alice_turn_id}


def test_clear_chat_only_removes_callers_turns(
    client: TestClient, iso_users, mock_retriever, mock_embedder
) -> None:
    """DELETE /chats clears only the caller's history on a shared KB."""
    kb_id = _create_shared_kb_with_doc(
        client,
        iso_users["alice"],
        "shared-kb-clear",
        iso_users["bob"],
        mock_retriever,
        mock_embedder,
    )
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    client.post(f"/api/kbs/{kb_id}/chat", json={"question": "alice-1"})
    client.post(f"/api/kbs/{kb_id}/chat", json={"question": "alice-2"})

    _login(client, iso_users["bob"]["username"], iso_users["bob"]["password"])
    client.post(f"/api/kbs/{kb_id}/chat", json={"question": "bob-1"})

    # Alice clears her history.
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    r = client.delete(f"/api/kbs/{kb_id}/chats")
    assert r.status_code == 200
    assert r.json()["data"]["deleted_count"] == 2

    # Alice's history is empty; Bob's survives untouched.
    assert client.get(f"/api/kbs/{kb_id}/chats").json()["data"] == []
    _login(client, iso_users["bob"]["username"], iso_users["bob"]["password"])
    assert {
        t["question"]
        for t in client.get(f"/api/kbs/{kb_id}/chats").json()["data"]
    } == {"bob-1"}


def test_member_cannot_list_history_of_inaccessible_kb(
    client: TestClient, iso_users, mock_retriever, mock_embedder
) -> None:
    """Chat history endpoint enforces KB visibility first."""
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-private-nochat")
    _login(client, iso_users["bob"]["username"], iso_users["bob"]["password"])
    r = client.get(f"/api/kbs/{alice_kb}/chats")
    assert r.status_code == 403
