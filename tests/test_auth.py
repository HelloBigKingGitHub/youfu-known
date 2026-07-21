"""Tests for the auth module.

Covers the three layers independently so failures pinpoint the layer:

- ``test_security_*`` -- bcrypt + JWT roundtrip
- ``test_user_store_*`` -- ``UserStore`` SQL CRUD + column migration
- ``test_service_*``   -- ``AuthService`` business logic (register/login/etc.)
- ``test_api_*``       -- FastAPI endpoints (cookie set, JSON envelope, etc.)

All API-level tests run against the per-test ``TestClient`` and rely on
a fixture that pre-populates an admin user + bootstraps the auth graph
on ``app.state``.
"""

from __future__ import annotations

import time
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from app.auth.models import UserRole
from app.auth.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


# ---------------------------------------------------------------------------
# Security primitives
# ---------------------------------------------------------------------------


def test_hash_and_verify_password_roundtrip() -> None:
    """bcrypt verify accepts the same password, rejects a wrong one."""
    h = hash_password("correct horse battery staple", rounds=4)
    assert h.startswith("$2b$")
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong", h)
    assert not verify_password("", h)


def test_verify_password_rejects_malformed_hash() -> None:
    """Garbage hashes must not raise; they must return False."""
    assert verify_password("anything", "not-a-bcrypt-hash") is False
    assert verify_password("anything", "") is False


def test_jwt_access_token_roundtrip() -> None:
    """encode -> decode returns the same sub/role and ``typ=access``."""
    secret = "test-secret"
    token = create_access_token("u1", "admin", secret=secret, expires_in=60)
    payload = decode_token(token, secret=secret, expected_kind="access")
    assert payload["sub"] == "u1"
    assert payload["role"] == "admin"
    assert payload["typ"] == "access"
    assert payload["exp"] > payload["iat"]


def test_jwt_refresh_token_has_typ_refresh() -> None:
    secret = "test-secret"
    token = create_refresh_token("u1", secret=secret, expires_in=60)
    payload = decode_token(token, secret=secret, expected_kind="refresh")
    assert payload["typ"] == "refresh"
    assert payload["sub"] == "u1"
    # ``role`` is not part of the refresh payload.
    assert "role" not in payload


def test_decode_token_rejects_wrong_kind() -> None:
    """An access token must not pass as a refresh token."""
    secret = "test-secret"
    access = create_access_token("u1", "member", secret=secret, expires_in=60)
    with pytest.raises(TokenError, match="wrong token kind"):
        decode_token(access, secret=secret, expected_kind="refresh")


def test_decode_token_rejects_expired() -> None:
    secret = "test-secret"
    token = create_access_token("u1", "member", secret=secret, expires_in=-1)
    with pytest.raises(TokenError, match="expired"):
        decode_token(token, secret=secret, expected_kind="access")


def test_decode_token_rejects_bad_signature() -> None:
    token = create_access_token("u1", "member", secret="a", expires_in=60)
    with pytest.raises(TokenError):
        decode_token(token, secret="b", expected_kind="access")


def test_decode_token_rejects_empty() -> None:
    with pytest.raises(TokenError, match="missing"):
        decode_token("", secret="x", expected_kind="access")


# ---------------------------------------------------------------------------
# UserStore
# ---------------------------------------------------------------------------


def test_user_store_creates_and_gets_user(sqlite_storage, settings) -> None:
    """End-to-end CRUD on the ``users`` table."""
    from app.auth.storage import UserStore

    store = UserStore(settings, db_path=sqlite_storage.db_path)
    user = store.create_user(
        username="alice", password_hash=hash_password("pw", rounds=4)
    )
    assert user.username == "alice"
    assert user.role == UserRole.MEMBER
    assert user.is_active is True
    assert user.is_approved is False  # default

    fetched = store.get_user(user.id)
    assert fetched == user

    by_name = store.get_by_username("alice")
    assert by_name == user


def test_user_store_duplicate_username_raises(sqlite_storage, settings) -> None:
    from app.auth.storage import UserStore

    store = UserStore(settings, db_path=sqlite_storage.db_path)
    store.create_user(username="dup", password_hash="h")
    with pytest.raises(ValueError, match="already exists"):
        store.create_user(username="dup", password_hash="h")


def test_user_store_list_and_count(sqlite_storage, settings) -> None:
    from app.auth.storage import UserStore

    store = UserStore(settings, db_path=sqlite_storage.db_path)
    assert store.count() == 0
    store.create_user(username="a", password_hash="h")
    store.create_user(username="b", password_hash="h", role=UserRole.ADMIN)
    assert store.count() == 2
    assert [u.username for u in store.list_users()] == ["a", "b"]


def test_user_store_list_users_orders_by_natural_created_at(
    sqlite_storage, settings
) -> None:
    """``list_users`` returns rows in natural insert order.

    The lifespan picks the bootstrap admin for orphan-row migration via
    ``list_users()`` and filters by role -- it must NOT depend on
    ``settings.auth.admin_username``. If the operator renames
    ``YOUFU_ADMIN_USERNAME`` in ``.env`` after the original admin is
    already in the DB, the migration must still target the originally
    bootstrapped admin (the first admin by ``created_at``), not the
    freshly-configured username.
    """
    from app.auth.storage import UserStore

    # ``.env`` claims a different admin username than what's in the DB
    # -- simulates an operator renaming the bootstrap admin.
    settings.auth.admin_username = "newly-configured-admin"

    store = UserStore(settings, db_path=sqlite_storage.db_path)
    original_admin = store.create_user(
        username="original-admin",
        password_hash="h",
        role=UserRole.ADMIN,
        is_approved=True,
    )
    later_member = store.create_user(username="late-member", password_hash="h")

    users = store.list_users()
    assert [u.id for u in users] == [original_admin.id, later_member.id]
    # The first admin by natural order is the one already in the DB,
    # NOT the .env-configured username.
    assert users[0].username == "original-admin"
    assert users[0].role == UserRole.ADMIN  # the original admin keeps its role


def test_user_store_list_users_tiebreaks_on_rowid(
    sqlite_storage, settings
) -> None:
    """Same-second creates must order by ``rowid`` (insert order).

    SQLite's ``CURRENT_TIMESTAMP`` resolves to one-second granularity,
    so two users inserted in the same second share ``created_at``; we
    need ``rowid ASC`` as the deterministic tiebreaker so the natural
    order matches insertion order instead of being arbitrary.
    """
    from app.auth.storage import UserStore

    store = UserStore(settings, db_path=sqlite_storage.db_path)
    first = store.create_user(username="first", password_hash="h")
    second = store.create_user(username="second", password_hash="h")
    third = store.create_user(username="third", password_hash="h")
    assert [u.id for u in store.list_users()] == [first.id, second.id, third.id]


def test_user_store_update_fields(sqlite_storage, settings) -> None:
    from app.auth.storage import UserStore

    store = UserStore(settings, db_path=sqlite_storage.db_path)
    user = store.create_user(username="bob", password_hash="old")
    updated = store.update_user(
        user.id,
        password_hash="new",
        is_approved=True,
        role=UserRole.ADMIN,
        is_active=False,
        email="bob@example.com",
    )
    assert updated is not None
    assert updated.is_approved is True
    assert updated.role == UserRole.ADMIN
    assert updated.is_active is False
    assert updated.email == "bob@example.com"
    assert store.get_password_hash(user.id) == "new"


def test_user_store_delete_user(sqlite_storage, settings) -> None:
    from app.auth.storage import UserStore

    store = UserStore(settings, db_path=sqlite_storage.db_path)
    user = store.create_user(username="del", password_hash="h")
    assert store.delete_user(user.id)
    assert store.get_user(user.id) is None
    assert store.delete_user(user.id) is False


def test_user_store_touch_last_login(sqlite_storage, settings) -> None:
    from app.auth.storage import UserStore

    store = UserStore(settings, db_path=sqlite_storage.db_path)
    user = store.create_user(username="login", password_hash="h")
    assert user.last_login_at is None
    store.touch_last_login(user.id)
    refreshed = store.get_user(user.id)
    assert refreshed is not None
    assert refreshed.last_login_at is not None


def test_user_store_adds_owner_columns_idempotently(sqlite_storage, settings) -> None:
    """``init()`` on a legacy DB must add owner/visibility columns."""
    from app.auth.storage import UserStore

    # Pre-create a KB *before* the UserStore runs, so the legacy columns
    # are present but owner/is_public are not.
    sqlite_storage.create_kb(name="legacy")

    store = UserStore(settings, db_path=sqlite_storage.db_path)
    store.init()  # idempotent on second call too
    store.init()

    # The new columns must exist now (write a row that uses them).
    with sqlite_storage._connect() as conn:
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(knowledge_bases)").fetchall()
        }
    assert "owner_id" in cols
    assert "is_public" in cols


def test_user_store_kb_visibility_helper(sqlite_storage, settings) -> None:
    from app.auth.storage import UserStore

    store = UserStore(settings, db_path=sqlite_storage.db_path)
    a = sqlite_storage.create_kb(name="a")
    b = sqlite_storage.create_kb(name="b")
    store.set_kb_owner(a.id, owner_id="u1")
    store.set_kb_owner(b.id, owner_id="u2")
    store.set_kb_visibility(b.id, is_public=True)

    visible_u1 = set(store.list_kbs_visible_to("u1", is_admin=False))
    assert a.id in visible_u1  # owner
    assert b.id in visible_u1  # public
    visible_admin = set(store.list_kbs_visible_to("u1", is_admin=True))
    assert visible_admin == {a.id, b.id}


# ---------------------------------------------------------------------------
# AuthService
# ---------------------------------------------------------------------------


def _make_service(sqlite_storage, settings):
    from app.auth.service import AuthService
    from app.auth.storage import UserStore

    store = UserStore(settings, db_path=sqlite_storage.db_path)
    return AuthService(store=store, settings=settings), store


def test_service_bootstrap_admin_creates_when_empty(sqlite_storage, settings) -> None:
    svc, _ = _make_service(sqlite_storage, settings)
    settings.auth.admin_username = "root"
    settings.auth.admin_password = "rootpw"
    admin = svc.bootstrap_admin_if_empty()
    assert admin is not None
    assert admin.role == UserRole.ADMIN
    assert admin.is_approved is True
    # Second call: nothing to do.
    assert svc.bootstrap_admin_if_empty() is None


def test_service_bootstrap_admin_noop_when_users_present(
    sqlite_storage, settings
) -> None:
    svc, store = _make_service(sqlite_storage, settings)
    store.create_user(username="preexisting", password_hash="h")
    settings.auth.admin_username = "root"
    settings.auth.admin_password = "rootpw"
    assert svc.bootstrap_admin_if_empty() is None
    # Only the pre-existing user remains.
    assert [u.username for u in store.list_users()] == ["preexisting"]


def test_service_register_creates_unapproved_member(
    sqlite_storage, settings
) -> None:
    svc, _ = _make_service(sqlite_storage, settings)
    user = svc.register("alice", "alicepw12", email="a@x.com")
    assert user.role == UserRole.MEMBER
    assert user.is_approved is False
    assert user.email == "a@x.com"


def test_service_register_rejects_short_password(sqlite_storage, settings) -> None:
    svc, _ = _make_service(sqlite_storage, settings)
    with pytest.raises(ValueError):
        svc.register("alice", "short")


def test_service_register_rejects_duplicate(sqlite_storage, settings) -> None:
    from app.auth.service import UsernameTakenError

    svc, _ = _make_service(sqlite_storage, settings)
    svc.register("alice", "alicepw12")
    with pytest.raises(UsernameTakenError):
        svc.register("alice", "alicepw12")


def test_service_login_success_mints_tokens(sqlite_storage, settings) -> None:
    svc, _ = _make_service(sqlite_storage, settings)
    svc.register("alice", "alicepw12")
    # Approve so login succeeds.
    store_user = svc.list_users()[0]
    # The store isn't directly exposed; use the UserStore via list_users.
    from app.auth.storage import UserStore

    UserStore(settings, db_path=sqlite_storage.db_path).update_user(
        store_user.id, is_approved=True
    )

    result = svc.login("alice", "alicepw12")
    assert result.user.username == "alice"
    assert result.access_token
    assert result.refresh_token
    from datetime import datetime, timedelta

    assert result.expires_at > datetime.utcnow()
    assert result.expires_at <= datetime.utcnow() + timedelta(hours=25)


def test_service_login_rejects_wrong_password(sqlite_storage, settings) -> None:
    from app.auth.service import InvalidCredentialsError

    svc, _ = _make_service(sqlite_storage, settings)
    svc.register("alice", "alicepw12")
    with pytest.raises(InvalidCredentialsError):
        svc.login("alice", "wrong-pw")


def test_service_login_rejects_unknown_user(sqlite_storage, settings) -> None:
    from app.auth.service import InvalidCredentialsError

    svc, _ = _make_service(sqlite_storage, settings)
    with pytest.raises(InvalidCredentialsError):
        svc.login("ghost", "nope")


def test_service_login_rejects_unapproved(sqlite_storage, settings) -> None:
    from app.auth.service import UserNotApprovedError

    svc, _ = _make_service(sqlite_storage, settings)
    svc.register("alice", "alicepw12")
    with pytest.raises(UserNotApprovedError):
        svc.login("alice", "alicepw12")


def test_service_login_rejects_inactive(sqlite_storage, settings) -> None:
    from app.auth.service import UserInactiveError
    from app.auth.storage import UserStore

    svc, store = _make_service(sqlite_storage, settings)
    user = svc.register("alice", "alicepw12")
    UserStore(settings, db_path=sqlite_storage.db_path).update_user(
        user.id, is_approved=True, is_active=False
    )
    with pytest.raises(UserInactiveError):
        svc.login("alice", "alicepw12")


def test_service_refresh_roundtrip(sqlite_storage, settings) -> None:
    svc, _ = _make_service(sqlite_storage, settings)
    user = svc.register("alice", "alicepw12")
    from app.auth.storage import UserStore

    UserStore(settings, db_path=sqlite_storage.db_path).update_user(
        user.id, is_approved=True
    )
    first = svc.login("alice", "alicepw12")
    second = svc.refresh(first.refresh_token)
    assert second.user.id == user.id
    # The new access token must validate as an access token.
    decode_token(second.access_token, secret=settings.auth.jwt_secret or "")


def test_service_change_password(sqlite_storage, settings) -> None:
    from app.auth.service import InvalidCredentialsError

    svc, _ = _make_service(sqlite_storage, settings)
    user = svc.register("alice", "alicepw12")
    from app.auth.storage import UserStore

    UserStore(settings, db_path=sqlite_storage.db_path).update_user(
        user.id, is_approved=True
    )
    svc.change_password(user.id, "alicepw12", "newalicepw34")
    # Old password no longer works.
    with pytest.raises(InvalidCredentialsError):
        svc.change_password(user.id, "alicepw12", "x1234567")
    # New password does.
    svc.change_password(user.id, "newalicepw34", "newpw56789")


def test_service_change_password_rejects_short(sqlite_storage, settings) -> None:
    svc, _ = _make_service(sqlite_storage, settings)
    user = svc.register("alice", "alicepw12")
    with pytest.raises(ValueError):
        svc.change_password(user.id, "alicepw12", "short")


def test_service_admin_cannot_demote_self(sqlite_storage, settings) -> None:
    from app.auth.service import CannotDemoteSelfError

    svc, store = _make_service(sqlite_storage, settings)
    admin = store.create_user(
        username="root",
        password_hash="h",
        role=UserRole.ADMIN,
        is_approved=True,
    )
    with pytest.raises(CannotDemoteSelfError):
        svc.update_user(admin.id, admin.id, role=UserRole.MEMBER)


def test_service_admin_can_change_other_users(sqlite_storage, settings) -> None:
    svc, _ = _make_service(sqlite_storage, settings)
    user = svc.register("alice", "alicepw12")
    updated = svc.update_user(
        "admin-id", user.id, is_approved=True, role=UserRole.ADMIN
    )
    assert updated.is_approved is True
    assert updated.role == UserRole.ADMIN


def test_service_admin_cannot_delete_self(sqlite_storage, settings) -> None:
    from app.auth.service import CannotDemoteSelfError

    svc, store = _make_service(sqlite_storage, settings)
    admin = store.create_user(
        username="root", password_hash="h", role=UserRole.ADMIN, is_approved=True
    )
    with pytest.raises(CannotDemoteSelfError):
        svc.delete_user(admin.id, admin.id)


# ---------------------------------------------------------------------------
# API-level tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def auth_admin(client: TestClient) -> Iterator[dict]:
    """Yield the bootstrapped admin's credentials.

    Depends on ``client`` so the lifespan handler has already created
    the ``root`` admin via ``bootstrap_admin_if_empty``; we just look
    it up off ``app.state.user_store``. All API-level tests then
    exercise the same DB the admin was created in.
    """
    store = client.app.state.user_store
    admin = store.get_by_username("root")
    assert admin is not None, "lifespan should have bootstrapped admin"
    yield {"username": "root", "password": "rootpw", "user_id": admin.id, "store": store}


def _login_admin(client: TestClient, username: str, password: str) -> None:
    r = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert r.status_code == 200, r.text


def test_register_creates_unapproved_user(
    client: TestClient, auth_admin
) -> None:
    r = client.post(
        "/api/auth/register",
        json={"username": "alice", "email": "a@x.com", "password": "alicepw12"},
    )
    assert r.status_code == 201, r.text
    body = r.json()["data"]
    assert body["username"] == "alice"
    assert body["role"] == "member"
    assert body["is_approved"] is False


def test_register_validates_payload(client: TestClient, auth_admin) -> None:
    # Short password
    r = client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "short"},
    )
    assert r.status_code == 400
    # Bad username
    r = client.post(
        "/api/auth/register",
        json={"username": "a b", "password": "alicepw12"},
    )
    assert r.status_code == 400


def test_login_sets_cookie_and_returns_user(
    client: TestClient, auth_admin
) -> None:
    r = client.post(
        "/api/auth/login",
        json={"username": auth_admin["username"], "password": auth_admin["password"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["user"]["username"] == auth_admin["username"]
    assert "session_token" in client.cookies


def test_login_rejects_bad_password(client: TestClient, auth_admin) -> None:
    r = client.post(
        "/api/auth/login",
        json={"username": auth_admin["username"], "password": "wrong"},
    )
    assert r.status_code == 401


def test_login_rejects_unapproved_member(client: TestClient, auth_admin) -> None:
    r = client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "alicepw12"},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "alicepw12"},
    )
    assert r.status_code == 403
    assert "approval" in r.json()["message"].lower()


def test_me_returns_current_user(client: TestClient, auth_admin) -> None:
    _login_admin(client, auth_admin["username"], auth_admin["password"])
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["data"]["username"] == auth_admin["username"]


def test_me_rejects_unauthenticated(client: TestClient, auth_admin) -> None:
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_logout_clears_cookie(client: TestClient, auth_admin) -> None:
    _login_admin(client, auth_admin["username"], auth_admin["password"])
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    # Cookie should be cleared. TestClient keeps a cookie jar but
    # FastAPI's ``delete_cookie`` resets the value to empty.
    me = client.get("/api/auth/me")
    assert me.status_code == 401


def test_change_password(client: TestClient, auth_admin) -> None:
    _login_admin(client, auth_admin["username"], auth_admin["password"])
    r = client.post(
        "/api/auth/change-password",
        json={"old_password": auth_admin["password"], "new_password": "newrootpw"},
    )
    assert r.status_code == 200, r.text
    # Logout and try the new password.
    client.post("/api/auth/logout")
    r = client.post(
        "/api/auth/login",
        json={"username": auth_admin["username"], "password": "newrootpw"},
    )
    assert r.status_code == 200


def test_change_password_rejects_wrong_old(client: TestClient, auth_admin) -> None:
    _login_admin(client, auth_admin["username"], auth_admin["password"])
    r = client.post(
        "/api/auth/change-password",
        json={"old_password": "wrong", "new_password": "newrootpw"},
    )
    assert r.status_code == 401


def test_refresh_mints_new_access(client: TestClient, auth_admin) -> None:
    # Bootstrap a member + login to get a refresh token. The simplest
    # path: the admin already has a valid login; we hit ``/refresh``
    # with their cookie (which is an access token) -- it must fail.
    _login_admin(client, auth_admin["username"], auth_admin["password"])
    r = client.post("/api/auth/refresh")
    assert r.status_code == 401


def test_refresh_works_with_valid_refresh(client: TestClient, auth_admin) -> None:
    """Use a refresh token obtained from /api/auth/login as a Bearer."""
    from app.auth.service import AuthService

    svc = client.app.state.auth_service
    login = svc.login(auth_admin["username"], auth_admin["password"])
    refresh_token = login.refresh_token

    r2 = client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["user"]["username"] == auth_admin["username"]


def test_admin_lists_users(client: TestClient, auth_admin) -> None:
    _login_admin(client, auth_admin["username"], auth_admin["password"])
    r = client.get("/api/admin/users")
    assert r.status_code == 200
    usernames = {u["username"] for u in r.json()["data"]}
    assert auth_admin["username"] in usernames


def test_admin_lists_users_forbidden_for_member(
    client: TestClient, auth_admin
) -> None:
    from app.auth.security import hash_password

    # Seed an approved member.
    store = client.app.state.user_store
    member = store.create_user(
        username="bob",
        password_hash=hash_password("bobpw1234", rounds=4),
        role=UserRole.MEMBER,
        is_active=True,
        is_approved=True,
    )
    client.post(
        "/api/auth/login", json={"username": "bob", "password": "bobpw1234"}
    )
    r = client.get("/api/admin/users")
    assert r.status_code == 403


def test_admin_approves_member(client: TestClient, auth_admin) -> None:
    # Register a member, login should fail (unapproved).
    client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "alicepw12"},
    )
    r = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "alicepw12"},
    )
    assert r.status_code == 403

    # Admin approves.
    _login_admin(client, auth_admin["username"], auth_admin["password"])
    store = client.app.state.user_store
    alice = store.get_by_username("alice")
    assert alice is not None
    r = client.patch(
        f"/api/admin/users/{alice.id}",
        json={"is_approved": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["is_approved"] is True

    # Member can now log in.
    client.post("/api/auth/logout")
    r = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "alicepw12"},
    )
    assert r.status_code == 200


def test_admin_deletes_user(client: TestClient, auth_admin) -> None:
    _login_admin(client, auth_admin["username"], auth_admin["password"])
    store = client.app.state.user_store
    victim = store.create_user(
        username="victim",
        password_hash="h",
        is_approved=True,
    )
    r = client.delete(f"/api/admin/users/{victim.id}")
    assert r.status_code == 200, r.text
    assert store.get_user(victim.id) is None


def test_admin_delete_self_blocked(client: TestClient, auth_admin) -> None:
    _login_admin(client, auth_admin["username"], auth_admin["password"])
    r = client.delete(f"/api/admin/users/{auth_admin['user_id']}")
    assert r.status_code == 400


def test_health_endpoint_stays_public(client: TestClient) -> None:
    """Sanity: the health check must not require auth."""
    r = client.get("/api/health")
    assert r.status_code == 200
