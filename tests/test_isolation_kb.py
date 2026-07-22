"""End-to-end tests for KB-level user isolation.

Covers the "shared KB" visibility model where a KB is private by
default, becomes visible to other members when the owner flips
``is_shared``, and stays in admin's view regardless. The two field
names (``is_shared`` and the deprecated ``is_public`` alias) are
both asserted at the API layer.
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
        username="alice_iso",
        password_hash=hash_password("alicepw12", rounds=4),
        role=UserRole.MEMBER,
        is_active=True,
        is_approved=True,
    )
    bob = store.create_user(
        username="bob_iso",
        password_hash=hash_password("bobpw1234", rounds=4),
        role=UserRole.MEMBER,
        is_active=True,
        is_approved=True,
    )
    yield {
        "admin": {"id": admin.id, "username": "root", "password": "rootpw"},
        "alice": {
            "id": alice.id,
            "username": "alice_iso",
            "password": "alicepw12",
        },
        "bob": {"id": bob.id, "username": "bob_iso", "password": "bobpw1234"},
    }


# ---------------------------------------------------------------------------
# 12-step acceptance
# ---------------------------------------------------------------------------


def test_alice_and_bob_cannot_see_each_others_private_kbs(
    client: TestClient, iso_users
) -> None:
    """Steps 2-5: each member's private KB is invisible to the other."""
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-kb-private")
    _login(client, iso_users["bob"]["username"], iso_users["bob"]["password"])
    bob_kb = _create_kb(client, "bob-kb-private")

    # Each user lists their own and sees only their own.
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    listed = {kb["id"] for kb in client.get("/api/kbs").json()["data"]}
    assert alice_kb in listed
    assert bob_kb not in listed
    # Direct fetch is 403.
    r = client.get(f"/api/kbs/{bob_kb}")
    assert r.status_code == 403

    _login(client, iso_users["bob"]["username"], iso_users["bob"]["password"])
    listed = {kb["id"] for kb in client.get("/api/kbs").json()["data"]}
    assert bob_kb in listed
    assert alice_kb not in listed
    r = client.get(f"/api/kbs/{alice_kb}")
    assert r.status_code == 403


def test_shared_kb_becomes_visible_to_other_members(
    client: TestClient, iso_users
) -> None:
    """Steps 6-7: after the owner flips is_shared, other members see it."""
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-shareable")

    # Bob cannot see it yet.
    _login(client, iso_users["bob"]["username"], iso_users["bob"]["password"])
    assert alice_kb not in {
        kb["id"] for kb in client.get("/api/kbs").json()["data"]
    }

    # Alice flips is_shared via the PATCH endpoint.
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    r = client.patch(
        f"/api/kbs/{alice_kb}", json={"is_shared": True}
    )
    assert r.status_code == 200, r.text
    payload = r.json()["data"]
    # Both the new and deprecated field names agree.
    assert payload["is_shared"] is True
    assert payload["is_public"] is True

    # Bob now sees it in the list and can fetch it.
    _login(client, iso_users["bob"]["username"], iso_users["bob"]["password"])
    listed = {kb["id"] for kb in client.get("/api/kbs").json()["data"]}
    assert alice_kb in listed
    r = client.get(f"/api/kbs/{alice_kb}")
    assert r.status_code == 200


def test_patch_is_public_alias_still_toggles_visibility(
    client: TestClient, iso_users
) -> None:
    """The deprecated ``is_public`` body field still works for old clients."""
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-share-legacy")

    r = client.patch(f"/api/kbs/{alice_kb}", json={"is_public": True})
    assert r.status_code == 200, r.text
    payload = r.json()["data"]
    assert payload["is_shared"] is True
    assert payload["is_public"] is True


def test_default_kb_is_private_for_other_members(
    client: TestClient, iso_users
) -> None:
    """A KB created without any flag is private to its owner."""
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    r = client.post("/api/kbs", json={"name": "fresh-private"})
    assert r.status_code == 201
    payload = r.json()["data"]
    assert payload["is_shared"] is False
    assert payload["is_public"] is False
    assert payload["owner_id"] == iso_users["alice"]["id"]


def test_only_owner_or_admin_can_toggle_is_shared(
    client: TestClient, iso_users
) -> None:
    """A non-owner non-admin cannot mutate a KB's shared flag."""
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-tamper-proof")

    _login(client, iso_users["bob"]["username"], iso_users["bob"]["password"])
    r = client.patch(f"/api/kbs/{alice_kb}", json={"is_shared": True})
    assert r.status_code == 403


def test_admin_sees_every_kb_regardless_of_owner(
    client: TestClient, iso_users
) -> None:
    """Admin visibility bypasses is_shared; they see every KB."""
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    alice_kb = _create_kb(client, "alice-admin-view")
    _login(client, iso_users["bob"]["username"], iso_users["bob"]["password"])
    bob_kb = _create_kb(client, "bob-admin-view")

    _login(client, iso_users["admin"]["username"], iso_users["admin"]["password"])
    listed = {kb["id"] for kb in client.get("/api/kbs").json()["data"]}
    assert alice_kb in listed
    assert bob_kb in listed

    r = client.get(f"/api/kbs/{alice_kb}")
    assert r.status_code == 200
    r = client.get(f"/api/kbs/{bob_kb}")
    assert r.status_code == 200


def test_kb_payload_returns_both_field_names(
    client: TestClient, iso_users
) -> None:
    """API responses include both ``is_shared`` and ``is_public`` mirrors."""
    _login(client, iso_users["alice"]["username"], iso_users["alice"]["password"])
    create = client.post("/api/kbs", json={"name": "mirror-fields"})
    assert create.status_code == 201
    data = create.json()["data"]
    assert "is_shared" in data
    assert "is_public" in data
    assert data["is_shared"] is False
    assert data["is_public"] is False

    r = client.patch(f"/api/kbs/{data['id']}", json={"is_shared": True})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["is_shared"] is True
    assert data["is_public"] is True
