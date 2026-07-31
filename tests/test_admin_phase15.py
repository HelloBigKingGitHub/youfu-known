"""Tests for Phase 1.5 admin Users endpoint.

Follows the same RED -> GREEN pattern as :mod:`tests.test_admin_phase1`
: the ``client`` / ``api_settings`` fixtures in ``conftest.py`` spin
up a real app with a lifespan-built ``UserStore`` and seeded admin
(``root`` / ``rootpw``); we then issue HTTP calls through
``fastapi.testclient.TestClient`` and assert on the spec'd envelope.

Phase 1.5 deliberately omits the PATCH /api/admin/users/{user_id}
mutation that the legacy :mod:`app.api.admin` exposes -- role
changes are deferred to Phase 2. The five tests here cover:

1. GET /api/admin/users returns every user (admin caller)
2. GET /api/admin/users rejects a ``member`` caller with 403
3. DELETE /api/admin/users/{id} removes a user (admin caller)
4. DELETE /api/admin/users/bogus returns 404
5. DELETE /api/admin/users/{own_id} returns 400 (cannot self-delete)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login_admin(client: TestClient) -> TestClient:
    """Log in as the bootstrap admin and stash the bearer header."""
    resp = client.post(
        "/api/auth/login",
        json={"username": "root", "password": "rootpw"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["data"]["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def _create_approved_member(
    client: TestClient, username: str, password: str
) -> str:
    """Register a member, approve via admin, and return the user id."""
    # Register (creates an unapproved member). The endpoint advertises
    # 201 Created, but some legacy callers still expect 200 -- accept
    # either so the helper stays stable across registration refactors.
    register = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@test.com",
            "password": password,
            "turnstile_token": "",
        },
    )
    assert register.status_code in (200, 201), register.text

    # Look up the user id via the admin list endpoint.
    admin_headers = {"Authorization": client.headers["Authorization"]}
    listed = client.get("/api/admin/users", headers=admin_headers)
    assert listed.status_code == 200, listed.text
    match = next(
        u
        for u in listed.json()["data"]
        if u["username"] == username
    )
    user_id = match["id"]

    # Approve via the legacy PATCH endpoint (kept for backwards compat
    # with the frontend -- the new ``app/admin/users.py`` only exposes
    # GET + DELETE in Phase 1.5).
    patched = client.patch(
        f"/api/admin/users/{user_id}",
        json={"is_approved": True},
        headers=admin_headers,
    )
    assert patched.status_code == 200, patched.text
    return user_id


def _login_as(client: TestClient, username: str, password: str) -> TestClient:
    """Log in as ``username`` and overwrite the client's Authorization header."""
    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["data"]["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client(client: TestClient) -> TestClient:
    """Return ``client`` with the bootstrap admin already logged in."""
    return _login_admin(client)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_admin_list_users_returns_every_account_without_secrets(
    admin_client: TestClient,
) -> None:
    """GET /api/admin/users returns a non-empty list of safe user dicts."""
    response = admin_client.get("/api/admin/users")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 0
    data = payload["data"]
    assert isinstance(data, list)
    # The bootstrap admin is always present.
    assert len(data) >= 1

    admin_row = next(row for row in data if row["username"] == "root")
    assert admin_row["role"] == "admin"
    assert admin_row["is_active"] is True
    assert admin_row["is_approved"] is True
    # The contract MUST NOT leak password hashes.
    assert "password_hash" not in admin_row
    for forbidden_key in ("password", "passwordHash"):
        assert forbidden_key not in admin_row


def test_admin_list_users_rejects_non_admin_caller_with_403(
    client: TestClient,
) -> None:
    """A member calling GET /api/admin/users gets 403, not 200."""
    # Bootstrap admin approves a member so the member can log in.
    admin_client = _login_admin(client)
    username = "p15_member_list"
    password = "p15_member_password_123"
    _create_approved_member(admin_client, username, password)

    # Reuse the same TestClient -- just swap the Authorization header
    # so the new login overwrites the admin session. The lifespan-
    # scoped singleton ``user_store`` is preserved across requests.
    _login_as(client, username, password)

    response = client.get("/api/admin/users")
    assert response.status_code == 403, response.text
    body = response.json()
    # The unified envelope should report the 403 code clearly.
    assert body["code"] == 403


def test_admin_delete_user_removes_the_target(
    admin_client: TestClient,
) -> None:
    """DELETE /api/admin/users/{id} returns a deleted marker and hides them."""
    # Create a fresh user we can safely delete.
    target_username = "p15_delete_target"
    target_password = "p15_delete_password_123"
    _create_approved_member(admin_client, target_username, target_password)

    # Resolve the user id from the listing.
    listed = admin_client.get("/api/admin/users")
    assert listed.status_code == 200, listed.text
    target_id = next(
        row["id"]
        for row in listed.json()["data"]
        if row["username"] == target_username
    )

    # DELETE should succeed.
    deleted = admin_client.delete(f"/api/admin/users/{target_id}")
    assert deleted.status_code == 200, deleted.text
    body = deleted.json()
    assert body["code"] == 0
    assert body["data"]["deleted"] == target_id
    assert body["data"]["existed"] is True

    # The user is gone from the listing.
    listed2 = admin_client.get("/api/admin/users")
    assert listed2.status_code == 200, listed2.text
    ids_after = [row["id"] for row in listed2.json()["data"]]
    assert target_id not in ids_after


def test_admin_delete_user_returns_404_for_missing_id(
    admin_client: TestClient,
) -> None:
    """DELETE /api/admin/users/bogus returns 404 with a 'not found' message."""
    response = admin_client.delete("/api/admin/users/does-not-exist-p15")
    assert response.status_code == 404, response.text
    body = response.json()
    assert body["code"] == 404
    assert "not found" in body["message"].lower()


def test_admin_delete_user_rejects_self_delete_with_400(
    admin_client: TestClient,
) -> None:
    """An admin cannot delete themselves (INC-005 / CannotDemoteSelfError)."""
    listed = admin_client.get("/api/admin/users")
    assert listed.status_code == 200, listed.text
    admin_id = next(
        row["id"] for row in listed.json()["data"] if row["username"] == "root"
    )

    response = admin_client.delete(f"/api/admin/users/{admin_id}")
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == 400
    # The message should mention self / yourself so the SPA can render it.
    assert "yourself" in body["message"].lower() or "delete" in body["message"].lower()
