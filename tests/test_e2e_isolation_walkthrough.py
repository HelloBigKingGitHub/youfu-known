"""E2E walkthrough of the 12-step acceptance test from
``openspec/tasks/user-isolation.md`` §验收标准.

Steps:

1. 创 member alice + bob
2. alice 创 KB-A (私有)
3. bob 创 KB-B (私有)
4. alice 看不到 KB-B (404/403)
5. bob 看不到 KB-A (404/403)
6. alice 把 KB-A 标记 shared
7. bob 现在能看到 KB-A
8. alice 问 KB-A 一个问题
9. bob 问 KB-A 一个问题
10. alice GET /chats → 只看到 alice 的
11. bob GET /chats → 只看到 bob 的
12. admin 看 admin 审计端点 → 都看到 (有 user_id 区分)
"""

from __future__ import annotations

from typing import Dict, Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth.models import UserRole
from app.auth.security import hash_password
from app.auth.storage import UserStore


def _login(c: TestClient, username: str, password: str) -> None:
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def _create_kb(c: TestClient, name: str) -> str:
    r = c.post("/api/kbs", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


def test_e2e_12_step_acceptance(client: TestClient) -> None:
    """Walk through the spec's 12-step acceptance scenario end-to-end."""

    # --- Step 1: create member alice + bob via the UserStore
    store: UserStore = client.app.state.user_store  # type: ignore[attr-defined]
    admin = store.get_by_username("root")
    assert admin is not None
    alice = store.create_user(
        username="alice_e2e",
        password_hash=hash_password("alicepw12", rounds=4),
        role=UserRole.MEMBER,
        is_active=True,
        is_approved=True,
    )
    bob = store.create_user(
        username="bob_e2e",
        password_hash=hash_password("bobpw1234", rounds=4),
        role=UserRole.MEMBER,
        is_active=True,
        is_approved=True,
    )

    # --- Step 2: alice creates private KB-A
    _login(client, "alice_e2e", "alicepw12")
    alice_kb = _create_kb(client, "KB-A-private")

    # --- Step 3: bob creates private KB-B
    _login(client, "bob_e2e", "bobpw1234")
    bob_kb = _create_kb(client, "KB-B-private")

    # --- Step 4: alice cannot see KB-B (403/404)
    _login(client, "alice_e2e", "alicepw12")
    r = client.get(f"/api/kbs/{bob_kb}")
    assert r.status_code == 403, r.text

    # --- Step 5: bob cannot see KB-A (403/404)
    _login(client, "bob_e2e", "bobpw1234")
    r = client.get(f"/api/kbs/{alice_kb}")
    assert r.status_code == 403, r.text

    # --- Step 6: alice flips KB-A to shared
    _login(client, "alice_e2e", "alicepw12")
    r = client.patch(f"/api/kbs/{alice_kb}", json={"is_shared": True})
    assert r.status_code == 200, r.text
    payload = r.json()["data"]
    assert payload["is_shared"] is True
    assert payload["is_public"] is True

    # --- Step 7: bob can now see KB-A
    _login(client, "bob_e2e", "bobpw1234")
    r = client.get(f"/api/kbs/{alice_kb}")
    assert r.status_code == 200, r.text

    # --- Step 8 + 9: alice and bob each chat against KB-A
    # Inject a fake retriever so /chat returns a deterministic answer.
    from unittest.mock import AsyncMock

    from app.rag.retriever import Citation, RagResult

    class _R:
        async def ask(self, *args, **kwargs):  # noqa: ARG002
            return RagResult(answer="ok", citations=[])

    client.app.state.retriever = _R()  # type: ignore[attr-defined]

    _login(client, "alice_e2e", "alicepw12")
    r = client.post(f"/api/kbs/{alice_kb}/chat", json={"question": "alice-q"})
    assert r.status_code == 200, r.text

    _login(client, "bob_e2e", "bobpw1234")
    r = client.post(f"/api/kbs/{alice_kb}/chat", json={"question": "bob-q"})
    assert r.status_code == 200, r.text

    # --- Step 10: alice's /chats only contains her turn
    _login(client, "alice_e2e", "alicepw12")
    rows = client.get(f"/api/kbs/{alice_kb}/chats").json()["data"]
    assert {t["question"] for t in rows} == {"alice-q"}
    assert {t["user_id"] for t in rows} == {alice.id}

    # --- Step 11: bob's /chats only contains his turn
    _login(client, "bob_e2e", "bobpw1234")
    rows = client.get(f"/api/kbs/{alice_kb}/chats").json()["data"]
    assert {t["question"] for t in rows} == {"bob-q"}
    assert {t["user_id"] for t in rows} == {bob.id}

    # --- Step 12: admin audit endpoint sees every turn
    _login(client, "root", "rootpw")
    r = client.get(f"/api/admin/kbs/{alice_kb}/chats")
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert {t["question"] for t in rows} == {"alice-q", "bob-q"}
    seen_users = {t["user_id"] for t in rows}
    assert seen_users == {alice.id, bob.id}

    # Per-user audit: admin can pull alice's history across KBs.
    r = client.get(f"/api/admin/users/{alice.id}/chats")
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert {t["question"] for t in rows} == {"alice-q"}
    assert all(t["user_id"] == alice.id for t in rows)
