"""Unit + integration tests for the admin user-management endpoints.

Phase 1 of the admin router lived entirely under ``app.api.admin`` and
exposed a single ``list_users`` / ``delete_user`` / ``update_user`` set
of routes. Phase 2.0 split the surface area:

- ``GET    /api/admin/users``              -- moved to ``app.admin.users``
- ``DELETE /api/admin/users/{user_id}``    -- moved to ``app.admin.users``
- ``GET    /api/admin/users/{id}/stats``   -- new in ``app.admin.users``
- ``PATCH  /api/admin/users/{user_id}``    -- stayed in ``app.api.admin``
                                               (now also reconciles
                                               ``feature_flags`` via
                                               :func:`_apply_auto_features`)

This file replaces the Phase-1 ``test_admin_api.py`` so the suite
covers the *new* surface area:

- ``GET /api/admin/users`` envelope shape  -- ``{total, items, limit,
  offset}`` rather than a bare list.
- ``DELETE /api/admin/users/{id}`` contract -- ``{deleted, existed}``
  on the storage-backed router, not the legacy auth-service method.
- ``PATCH /api/admin/users/{id}`` unchanged at the URL level, but
  its body now drives the auto-feature sync so we stub the new
  ``svc.list_users`` lookup too.
- ``require_admin`` gate remains universal across both routers.

The list / delete tests run through the real ``TestClient`` lifespan
because the new router pulls ``UserStore`` from ``app.state`` --
mocking the whole storage layer would re-implement the spec. The
PATCH tests keep the ``Mock(spec=AuthService)`` pattern from the
Phase-1 baseline because that endpoint still talks to the auth
service, not the storage layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterator, List, Tuple
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.deps import require_admin
from app.auth.models import User, UserRole
from app.auth.security import hash_password
from app.auth.service import AuthService, CannotDemoteSelfError, UserNotFoundError
from app.auth.storage import UserStore
from app.config import Settings


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


# A static timestamp so payload comparisons stay stable across tests.
_FIXED_TS = datetime(2026, 1, 1, 12, 0, 0)


def _make_user(
    *,
    user_id: str,
    username: str,
    role: UserRole,
    is_active: bool = True,
    is_approved: bool = True,
    email: str = "",
) -> User:
    return User(
        id=user_id,
        username=username,
        email=email or f"{username}@example.com",
        role=role,
        is_active=is_active,
        is_approved=is_approved,
        created_at=_FIXED_TS,
        last_login_at=None,
    )


@pytest.fixture
def admin_user() -> User:
    """A single admin caller used to satisfy ``require_admin``."""
    return _make_user(
        user_id="admin-1",
        username="root",
        role=UserRole.ADMIN,
        email="root@example.com",
    )


@pytest.fixture
def member_user() -> User:
    return _make_user(
        user_id="member-1",
        username="alice",
        role=UserRole.MEMBER,
        email="alice@example.com",
    )


@pytest.fixture
def pending_user() -> User:
    return _make_user(
        user_id="pending-1",
        username="pending",
        role=UserRole.MEMBER,
        is_approved=False,
        email="pending@example.com",
    )


@pytest.fixture
def mock_service() -> Mock:
    """``Mock(spec=AuthService)`` -- keeps callers honest on typos."""
    return Mock(spec=AuthService)


@pytest.fixture
def admin_client(
    admin_user: User,
    mock_service: Mock,
    api_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Tuple[TestClient, Mock]]:
    """TestClient with ``require_admin`` bypassed as ``admin_user``.

    PATCH /api/admin/users/{id} still routes through
    ``app.api.admin`` and consults ``app.state.auth_service``; we swap
    that for ``mock_service`` so we can drive the endpoint without a
    real SQLite-backed AuthService. The list / delete / stats endpoints
    live under ``app.admin.users`` and use the real UserStore -- which
    this fixture leaves untouched (with ``api_settings`` redirecting
    every storage path at a per-test ``tmp_path``).
    """
    monkeypatch.setenv("YOUFU_TURNSTILE_SECRET", "")

    from main import create_app

    app = create_app()

    def _mock_require_admin() -> User:
        return admin_user

    app.dependency_overrides[require_admin] = _mock_require_admin

    with TestClient(app, raise_server_exceptions=False) as client:
        # Replace the auth service AFTER lifespan so the rest of the
        # admin router (storage, user_store, feature flags) stays real.
        app.state.auth_service = mock_service
        yield client, mock_service

    app.dependency_overrides.clear()


@pytest.fixture
def member_client(
    admin_user: User,
    member_user: User,
    mock_service: Mock,
    api_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Tuple[TestClient, Mock]]:
    """TestClient where ``require_admin`` rejects the caller with 403."""
    monkeypatch.setenv("YOUFU_TURNSTILE_SECRET", "")

    from main import create_app

    app = create_app()

    def _mock_require_admin() -> User:
        raise HTTPException(
            status_code=403, detail="admin role required"
        )

    app.dependency_overrides[require_admin] = _mock_require_admin

    with TestClient(app, raise_server_exceptions=False) as client:
        app.state.auth_service = mock_service
        yield client, mock_service

    app.dependency_overrides.clear()


def _seed_users(store: UserStore) -> Dict[str, User]:
    """Seed the UserStore with the canonical Phase-1 fixture trio.

    The lifespan already bootstraps an admin (``root``); we look it up
    instead of re-creating it so the UNIQUE constraint on ``username``
    is honoured.
    """
    created: Dict[str, User] = {}
    admin = store.list_users()
    assert admin, "expected the lifespan to have seeded the root admin"
    created["admin"] = admin[0]
    created["alice"] = store.create_user(
        "alice",
        hash_password("alicepw", rounds=4),
        role=UserRole.MEMBER,
        is_approved=True,
        email="alice@example.com",
    )
    created["bob"] = store.create_user(
        "bob",
        hash_password("bobpw", rounds=4),
        role=UserRole.MEMBER,
        is_approved=True,
        email="user-bob@example.com",
    )
    created["pending"] = store.create_user(
        "pending",
        hash_password("pendingpw", rounds=4),
        role=UserRole.MEMBER,
        is_approved=False,
    )
    return created


# ---------------------------------------------------------------------------
# GET /api/admin/users  (new envelope shape)
# ---------------------------------------------------------------------------


def test_admin_list_users_empty(admin_client: Tuple[TestClient, Mock]) -> None:
    """Admin envelope shape: total reflects the bootstrapped root user.

    The lifespan seeds a single admin (``root``) so the "empty" case
    is "no extra users beyond the bootstrap admin". The endpoint
    must still return the documented envelope shape and respect
    pagination defaults.
    """
    client, _svc = admin_client
    store: UserStore = client.app.state.user_store  # type: ignore[attr-defined]
    pre = store.list_users()
    # Only the lifespan-seeded root admin is expected.
    assert [u.username for u in pre] == ["root"]

    resp = client.get("/api/admin/users")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    payload = body["data"]
    assert payload["total"] == 1
    assert payload["limit"] == 50
    assert payload["offset"] == 0
    assert len(payload["items"]) == 1
    assert payload["items"][0]["username"] == "root"


def test_admin_list_users_returns_all(
    admin_client: Tuple[TestClient, Mock],
) -> None:
    """Admin sees every user through the new envelope."""
    client, _svc = admin_client
    store: UserStore = client.app.state.user_store  # type: ignore[attr-defined]
    seeded = _seed_users(store)

    resp = client.get("/api/admin/users")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    payload = body["data"]
    # total reflects all seeded rows.
    assert payload["total"] == len(seeded)
    assert payload["limit"] == 50
    assert payload["offset"] == 0
    assert len(payload["items"]) == len(seeded)
    usernames = {u["username"] for u in payload["items"]}
    assert usernames == {"root", "alice", "bob", "pending"}

    # Each entry exposes the documented shape.
    for entry in payload["items"]:
        assert set(entry.keys()) == {
            "id",
            "username",
            "email",
            "role",
            "is_active",
            "is_approved",
            "created_at",
            "last_login_at",
        }
        assert entry["role"] in {"admin", "member"}


# ---------------------------------------------------------------------------
# PATCH /api/admin/users/{user_id}  (stays in app/api/admin.py)
# ---------------------------------------------------------------------------


def test_admin_update_user_approve(
    admin_client: Tuple[TestClient, Mock],
    pending_user: User,
) -> None:
    """PATCH ``is_approved=True`` flips the pending member to approved.

    PATCH still lives in ``app.api.admin``; we mock the auth service
    but the new lookup-of-pre-state line calls ``svc.list_users()``,
    so we have to stub that too.
    """
    client, svc = admin_client
    approved = pending_user.model_copy(update={"is_approved": True})
    # Pre-mutation lookup must yield the pending user.
    svc.list_users.return_value = [pending_user]
    svc.update_user.return_value = approved

    resp = client.patch(
        f"/api/admin/users/{pending_user.id}",
        json={"is_approved": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["id"] == pending_user.id
    assert body["data"]["is_approved"] is True

    svc.list_users.assert_called_once_with()
    svc.update_user.assert_called_once()
    kwargs = svc.update_user.call_args.kwargs
    assert kwargs["acting_user_id"] == "admin-1"
    assert kwargs["target_user_id"] == pending_user.id
    assert kwargs["is_approved"] is True
    assert kwargs["role"] is None
    assert kwargs["is_active"] is None
    assert kwargs["email"] is None


def test_admin_update_user_change_role(
    admin_client: Tuple[TestClient, Mock],
    member_user: User,
) -> None:
    """PATCH ``role='member'`` round-trips the new role back to the admin."""
    client, svc = admin_client
    promoted = member_user.model_copy(update={"role": UserRole.MEMBER})
    svc.list_users.return_value = [member_user]
    svc.update_user.return_value = promoted

    resp = client.patch(
        f"/api/admin/users/{member_user.id}",
        json={"role": "member"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["role"] == "member"

    svc.update_user.assert_called_once()
    kwargs = svc.update_user.call_args.kwargs
    assert kwargs["acting_user_id"] == "admin-1"
    assert kwargs["target_user_id"] == member_user.id
    assert kwargs["role"] == UserRole.MEMBER


def test_admin_update_user_cannot_demote_self(
    admin_client: Tuple[TestClient, Mock],
    admin_user: User,
) -> None:
    """An admin demoting themselves gets HTTP 400 with a clear message."""
    client, svc = admin_client
    # ``update_user`` raises CannotDemoteSelfError on self-demotion; the
    # pre-lookup must find the admin so we get past the 404 guard.
    svc.list_users.return_value = [admin_user]
    svc.update_user.side_effect = CannotDemoteSelfError(
        "cannot remove your own admin role"
    )

    resp = client.patch(
        f"/api/admin/users/{admin_user.id}",
        json={"role": "member"},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert "cannot" in body["message"].lower()
    assert "admin" in body["message"].lower()

    svc.update_user.assert_called_once()
    kwargs = svc.update_user.call_args.kwargs
    assert kwargs["acting_user_id"] == "admin-1"
    assert kwargs["target_user_id"] == admin_user.id
    assert kwargs["role"] == UserRole.MEMBER


def test_admin_update_user_not_found_404(
    admin_client: Tuple[TestClient, Mock],
) -> None:
    """Patching a non-existent user surfaces HTTP 404."""
    client, svc = admin_client
    # Pre-lookup is empty -> the endpoint raises 404 BEFORE hitting
    # ``svc.update_user``.
    svc.list_users.return_value = []
    svc.update_user.side_effect = UserNotFoundError(
        "user not found: nonexistent"
    )

    resp = client.patch(
        "/api/admin/users/nonexistent",
        json={"is_approved": True},
    )
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert "not found" in body["message"].lower()

    svc.list_users.assert_called_once_with()
    # update_user is never reached on the empty-pre-state branch.
    svc.update_user.assert_not_called()


# ---------------------------------------------------------------------------
# DELETE /api/admin/users/{user_id}  (moved to app/admin/users.py)
# ---------------------------------------------------------------------------


def test_admin_delete_user_cascade(
    admin_client: Tuple[TestClient, Mock],
    member_user: User,
) -> None:
    """DELETE goes through the storage-backed router and returns
    ``{deleted, existed}``.

    The legacy ``app.api.admin.delete_user`` is gone, so we exercise
    the new ``app.admin.users.delete_user`` directly via TestClient +
    the real ``UserStore`` (seeded with the canonical fixture trio).
    """
    client, _svc = admin_client
    store: UserStore = client.app.state.user_store  # type: ignore[attr-defined]
    seeded = _seed_users(store)
    target_id = seeded["alice"].id

    resp = client.delete(f"/api/admin/users/{target_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["deleted"] == target_id
    assert body["data"]["existed"] is True
    # User is actually gone from storage.
    assert store.get_user(target_id) is None


# ---------------------------------------------------------------------------
# RBAC gate
# ---------------------------------------------------------------------------


def test_admin_endpoints_require_admin_role_403(
    member_client: Tuple[TestClient, Mock],
    mock_service: Mock,
) -> None:
    """A non-admin caller is rejected with HTTP 403 on every admin route.

    ``require_admin`` short-circuits before the body runs on every
    router (the legacy ``app.api.admin`` and the new
    ``app.admin.users``), so the service mock is never reached.
    """
    client, _svc = member_client

    # GET /api/admin/users -- new envelope endpoint under app.admin.users
    r = client.get("/api/admin/users")
    assert r.status_code == 403, r.text
    assert "admin role required" in r.json()["message"]

    # PATCH /api/admin/users/{user_id} -- legacy app.api.admin endpoint
    r = client.patch(
        "/api/admin/users/member-1", json={"is_approved": True}
    )
    assert r.status_code == 403, r.text
    assert "admin role required" in r.json()["message"]

    # DELETE /api/admin/users/{user_id} -- new endpoint under app.admin.users
    r = client.delete("/api/admin/users/member-1")
    assert r.status_code == 403, r.text
    assert "admin role required" in r.json()["message"]

    # No auth-service method was ever invoked.
    _svc.list_users.assert_not_called()
    _svc.update_user.assert_not_called()
    _svc.delete_user.assert_not_called()


__all__ = [
    "test_admin_list_users_empty",
    "test_admin_list_users_returns_all",
    "test_admin_update_user_approve",
    "test_admin_update_user_change_role",
    "test_admin_update_user_cannot_demote_self",
    "test_admin_update_user_not_found_404",
    "test_admin_delete_user_cascade",
    "test_admin_endpoints_require_admin_role_403",
]
