"""Unit tests for ``app.api.admin`` (admin user-management endpoints).

These tests focus on the HTTP layer of the admin router. They mock
``AuthService`` so we can drive each endpoint deterministically without
standing up a full SQLite + lifespan bootstrap (the ``P5b/V-rung``
pattern referenced in the stage-3 spec: stub the service, exercise the
endpoint, assert the envelope + status).

Coverage:

- ``GET    /api/admin/users`` -- empty list + populated list
- ``PATCH  /api/admin/users/{user_id}`` -- approve, change role,
  cannot demote self (400), not found (404)
- ``DELETE /api/admin/users/{user_id}`` -- cascade contract
- admin-only gate (``require_admin``) -- 403 for non-admin caller

All 8 tests run against the per-test ``TestClient`` and never touch the
filesystem or real ``AuthService`` / ``UserStore``.

Hard constraints (per stage-3 spec):

- Zero edits to ``app/api/admin.py`` -- this file only exercises it.
- Zero edits to ``app/auth/``, ``app/kb/service.py``, or backend runtime.
- Zero new dependencies; uses FastAPI ``TestClient`` + ``unittest.mock``.
- No commits -- the test file lives in ``tests/`` only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Tuple
from unittest.mock import MagicMock, Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.deps import require_admin
from app.auth.models import User, UserRole
from app.auth.service import (
    AuthService,
    CannotDemoteSelfError,
    UserNotFoundError,
)


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
    """Build a ``User`` instance for use in mock return values.

    ``password_hash`` is intentionally omitted from the public model so
    we don't need a real bcrypt hash to instantiate a fixture.
    """
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
    """A single approved member (the typical target of admin ops)."""
    return _make_user(
        user_id="member-1",
        username="alice",
        role=UserRole.MEMBER,
        email="alice@example.com",
    )


@pytest.fixture
def pending_user() -> User:
    """An unapproved member (typical pre-approval target)."""
    return _make_user(
        user_id="pending-1",
        username="pending",
        role=UserRole.MEMBER,
        is_approved=False,
        email="pending@example.com",
    )


@pytest.fixture
def mock_service() -> Mock:
    """A ``Mock(spec=AuthService)`` with all admin methods stubbed.

    The spec keeps callers honest: typos on method names raise
    ``AttributeError`` instead of silently passing.
    """
    return Mock(spec=AuthService)


@pytest.fixture
def admin_client(
    admin_user: User, mock_service: Mock, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Tuple[TestClient, Mock]]:
    """TestClient with ``require_admin`` bypassed as ``admin_user``.

    Order matters: dependency overrides must be installed BEFORE the
    TestClient's lifespan handler runs (so it sees them at request
    time), but ``app.state.auth_service`` must be replaced AFTER the
    lifespan runs (the lifespan populates it). We do both at the
    right moment via the TestClient context manager.

    ``monkeypatch.setenv("YOUFU_TURNSTILE_SECRET", "")`` puts the
    Turnstile helper into dev-mode (skip real HTTPS round-trip), which
    prevents cross-file pollution when this lifespan runs before
    tests that exercise AuthService.register / login.
    """
    # Force Turnstile into dev mode to avoid real Cloudflare calls
    # that pollute the rest of the test suite with SSL errors.
    monkeypatch.setenv("YOUFU_TURNSTILE_SECRET", "")

    from main import create_app

    app = create_app()

    def _mock_require_admin() -> User:
        return admin_user

    # Install BEFORE the lifespan so the override is visible at request time.
    app.dependency_overrides[require_admin] = _mock_require_admin

    with TestClient(app, raise_server_exceptions=False) as client:
        # The lifespan has now built the real ``auth_service`` on
        # ``app.state`` -- swap it for our mock before any request runs.
        app.state.auth_service = mock_service
        yield client, mock_service

    app.dependency_overrides.clear()


@pytest.fixture
def member_client(
    admin_user: User, member_user: User, mock_service: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Tuple[TestClient, Mock]]:
    """TestClient where ``require_admin`` rejects the caller with 403.

    Used to exercise the RBAC gate independently of the real JWT flow.
    """
    # Same Turnstile dev-mode isolation as admin_client.
    monkeypatch.setenv("YOUFU_TURNSTILE_SECRET", "")

    from main import create_app

    app = create_app()

    def _mock_require_admin() -> User:
        # Mirror ``app.auth.deps.require_admin``'s exact behaviour:
        # non-admins get HTTP 403 with ``admin role required``.
        raise HTTPException(
            status_code=403, detail="admin role required"
        )

    app.dependency_overrides[require_admin] = _mock_require_admin

    with TestClient(app, raise_server_exceptions=False) as client:
        # The service mock is never reached on this fixture -- the
        # dependency raises first -- but assigning it keeps the contract
        # identical to ``admin_client`` so the same teardown works.
        app.state.auth_service = mock_service
        yield client, mock_service

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/admin/users
# ---------------------------------------------------------------------------


def test_admin_list_users_empty(
    admin_client: Tuple[TestClient, Mock],
) -> None:
    """Admin with no users in the system sees an empty list."""
    client, svc = admin_client
    svc.list_users.return_value = []

    resp = client.get("/api/admin/users")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    assert body["data"] == []
    svc.list_users.assert_called_once_with()


def test_admin_list_users_returns_all(
    admin_client: Tuple[TestClient, Mock],
    admin_user: User,
    member_user: User,
    pending_user: User,
) -> None:
    """Admin sees every user (admin + approved member + pending member)."""
    client, svc = admin_client
    svc.list_users.return_value = [admin_user, member_user, pending_user]

    resp = client.get("/api/admin/users")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    payload: List[Dict[str, Any]] = body["data"]
    assert len(payload) == 3
    usernames = {u["username"] for u in payload}
    assert usernames == {"root", "alice", "pending"}

    # Each entry exposes the documented shape.
    for entry in payload:
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
        # Role comes back as the raw string, not the enum object.
        assert entry["role"] in {"admin", "member"}

    svc.list_users.assert_called_once_with()


# ---------------------------------------------------------------------------
# PATCH /api/admin/users/{user_id}
# ---------------------------------------------------------------------------


def test_admin_update_user_approve(
    admin_client: Tuple[TestClient, Mock],
    pending_user: User,
) -> None:
    """PATCH ``is_approved=True`` flips the pending member to approved."""
    client, svc = admin_client
    approved = pending_user.model_copy(update={"is_approved": True})
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

    # Service was called with the admin's id as ``acting_user_id`` and
    # only the patched field propagated.
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
    svc.update_user.side_effect = CannotDemoteSelfError(
        "cannot remove your own admin role"
    )

    resp = client.patch(
        f"/api/admin/users/{admin_user.id}",
        json={"role": "member"},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    # The HTTPException handler in main.py wraps ``detail`` into
    # ``message``; the original text must be preserved.
    assert "cannot" in body["message"].lower()
    assert "admin" in body["message"].lower()

    # Service was attempted with the admin's own id (acting == target).
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

    svc.update_user.assert_called_once_with(
        acting_user_id="admin-1",
        target_user_id="nonexistent",
        is_approved=True,
        role=None,
        is_active=None,
        email=None,
    )


# ---------------------------------------------------------------------------
# DELETE /api/admin/users/{user_id}
# ---------------------------------------------------------------------------


def test_admin_delete_user_cascade(
    admin_client: Tuple[TestClient, Mock],
    member_user: User,
) -> None:
    """DELETE returns ``{deleted, existed}``; ``existed=True`` on first call."""
    client, svc = admin_client
    svc.delete_user.return_value = True

    resp = client.delete(f"/api/admin/users/{member_user.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["deleted"] == member_user.id
    assert body["data"]["existed"] is True

    svc.delete_user.assert_called_once_with(
        acting_user_id="admin-1", target_user_id=member_user.id
    )


# ---------------------------------------------------------------------------
# RBAC gate
# ---------------------------------------------------------------------------


def test_admin_endpoints_require_admin_role_403(
    member_client: Tuple[TestClient, Mock],
    mock_service: Mock,
) -> None:
    """A non-admin caller is rejected with HTTP 403 on every admin route.

    The service mock is never reached -- ``require_admin`` short-circuits
    before the body runs.
    """
    client, _svc = member_client

    # GET /api/admin/users
    r = client.get("/api/admin/users")
    assert r.status_code == 403, r.text
    assert "admin role required" in r.json()["message"]

    # PATCH /api/admin/users/{user_id}
    r = client.patch(
        "/api/admin/users/member-1", json={"is_approved": True}
    )
    assert r.status_code == 403, r.text
    assert "admin role required" in r.json()["message"]

    # DELETE /api/admin/users/{user_id}
    r = client.delete("/api/admin/users/member-1")
    assert r.status_code == 403, r.text
    assert "admin role required" in r.json()["message"]

    # No service method was ever invoked.
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
