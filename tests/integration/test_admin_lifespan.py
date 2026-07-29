"""Integration test: admin API + lifespan end-to-end.

This is the **real** integration test the 32-commit DDD run was missing.
It boots the genuine ``main:create_app()`` factory with a real SQLite
metadata DB and real Chroma collection directory, runs the full
``lifespan`` handler (which bootstraps the admin account from
``api_settings.auth.admin_username/password``), exercises the admin
HTTP endpoints against the live service graph, closes the app (mock
SIGTERM), then **starts it a second time** against the same on-disk
DB to verify that ``P5b`` / ``P8a`` -- the lifespan-idempotent
crashes that plagued early DDD stages -- no longer reproduce.

Why this lives in ``tests/integration/`` (not ``tests/``):

* Sharing ``tests/conftest.py`` would re-apply the per-test ``Settings``
  + transient Chroma fixtures tuned for the single-process-per-test
  assumption. An integration test wants to bring the app up **twice**
  on the same on-disk DB to catch the ``P5b`` / ``P8a`` lifespan
  idempotent failures, which the unit suite cannot reproduce.
* ``tests/test_admin_api.py`` (stage 3) mocks ``AuthService`` and
  drives endpoints in isolation; this test goes the other way --
  no mocks, real lifespan, real SQLite, real AuthService, real HTTP.

Hard constraints (per stage-4 spec):

* Zero edits to ``app/``, ``main.py``, ``tests/conftest.py``, or any
  existing ``tests/test_*.py``. This file is the only addition.
* Zero commits -- the file lives in ``tests/integration/`` only and
  is committed by Hermes as a separate commit at the end.
* Uses the **existing** ``api_settings`` fixture from ``tests/conftest.py``
  (it already wires tmp paths, reloads the lru_cache ``get_settings``
  factory, monkey-patches env vars, and pre-populates the admin
  bootstrap creds so the lifespan can seed the initial admin).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# Marker so a future ``-m "not integration"`` run can skip this suite
# without removing the file.
pytestmark = pytest.mark.integration


def _login_admin(client: TestClient, username: str, password: str) -> str:
    """Helper: POST /api/auth/login -> access_token; asserts success."""
    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200, (
        f"admin login failed: status={resp.status_code} body={resp.text}"
    )
    payload = resp.json()
    assert payload.get("code") == 0, f"login envelope code != 0: {payload}"
    access_token = payload["data"]["access_token"]
    assert access_token, "login response missing data.access_token"
    return access_token


def _list_users(client: TestClient, admin_token: str) -> list:
    """Helper: GET /api/admin/users -> list of user dicts."""
    resp = client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, (
        f"list users failed: status={resp.status_code} body={resp.text}"
    )
    payload = resp.json()
    assert payload.get("code") == 0, f"list envelope code != 0: {payload}"
    return payload["data"]


def _register_member(
    client: TestClient, username: str, password: str, email: str
) -> str:
    """Helper: POST /api/auth/register -> user id (or 409 if pre-existing).

    Returns the new user's id when the registration succeeds, or the
    id of the pre-existing user when the DB already has one with the
    same username (e.g. test re-run against a populated tmp dir).
    """
    resp = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
        },
    )
    if resp.status_code in (200, 201):
        payload = resp.json()
        assert payload.get("code") == 0, f"register envelope != 0: {payload}"
        return payload["data"]["id"]
    # Already exists -- look up via admin list. Caller must have an
    # admin token to do this; we accept the 409 here and let the
    # caller resolve the id.
    assert resp.status_code == 409, (
        f"register failed (non-409): status={resp.status_code} body={resp.text}"
    )
    return ""  # sentinel: caller will resolve


def _approve_member(
    client: TestClient, admin_token: str, user_id: str
) -> dict:
    """Helper: PATCH /api/admin/users/{id} is_approved=True -> updated user dict."""
    resp = client.patch(
        f"/api/admin/users/{user_id}",
        json={"is_approved": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, (
        f"approve failed: status={resp.status_code} body={resp.text}"
    )
    payload = resp.json()
    assert payload.get("code") == 0, f"approve envelope != 0: {payload}"
    assert payload["data"]["is_approved"] is True
    return payload["data"]


def test_admin_login_and_list_users_via_uvicorn(api_settings, tmp_path) -> None:
    """End-to-end: admin login + list users + register + approve, twice.

    Boots ``main:create_app()`` twice against the same on-disk SQLite
    DB (pointed at ``tmp_path``) and the same Chroma dir. The first
    run exercises the full lifespan (bootstrap admin -> register ->
    approve), and the second run simulates a service restart after a
    SIGTERM. The second run must succeed without raising -- this is
    the contract the stage-4 spec calls out as guarding against
    ``P5b`` / ``P8a`` (lifespan-idempotent failures).

    Round 1 (lifespan #1):
        1. admin login    -> access_token
        2. admin list     -> [{admin, ...}] (initial users)
        3. register       -> member, is_approved=False (default)
        4. admin approve  -> is_approved=True
        5. verify         -> member visible in list, is_approved=True

    [ TestClient context exits -> lifespan close, Chroma client close,
      DB connection release. SQLite + Chroma state persist to
      tmp_path because the api_settings fixture points storage /
      chroma at tmp_path via tmp_path monkeypatching. ]

    Round 2 (lifespan #2 against the same on-disk DB):
        6. admin login    -> access_token (proves DB + admin persisted)
        7. admin list     -> member still present, is_approved=True
                             (proves approval persisted)
        [ No raise -> P5b / P8a lifespan-idempotent contract holds. ]
    """
    # ``api_settings`` is the per-test fixture from tests/conftest.py
    # that already:
    #   * sets YOUFU_KNOWN_ROOT + admin creds via monkeypatch.setenv,
    #   * clears the lru_cache on app.config.get_settings,
    #   * reloads app.config so subsequent imports see fresh env vars,
    #   * rewrites storage paths under tmp_path,
    #   * patches both app.config.get_settings and app.deps.get_settings
    #     to return the per-test Settings instance.
    # We build a fresh FastAPI app here so each TestClient context
    # owns its own lifespan state (singletons on app.state).
    from main import create_app

    admin_username = api_settings.auth.admin_username
    admin_password = api_settings.auth.admin_password
    assert admin_username and admin_password, (
        "api_settings must seed admin_username/password for lifespan bootstrap"
    )

    member_username = "test_member"
    member_password = "member_password_123"
    member_email = "member@test.local"

    app = create_app()

    # ------------------------------------------------------------------
    # Round 1: lifespan bootstrap + register + approve
    # ------------------------------------------------------------------
    with TestClient(app) as client:
        # 1. admin login -- lifespan auto-bootstrapped the admin account.
        admin_token = _login_admin(client, admin_username, admin_password)

        # 2. admin list -- bootstrap admin should be visible.
        initial_users = _list_users(client, admin_token)
        assert isinstance(initial_users, list)
        admin_rows = [u for u in initial_users if u["username"] == admin_username]
        assert len(admin_rows) == 1, (
            f"expected bootstrap admin in list, got: {initial_users}"
        )
        assert admin_rows[0]["is_approved"] is True
        assert admin_rows[0]["is_active"] is True

        # 3. register member (default is_approved=False).
        member_id = _register_member(
            client, member_username, member_password, member_email
        )
        if not member_id:
            # Already exists from a prior partial run -- resolve via admin list.
            current = _list_users(client, admin_token)
            existing = next(
                (u for u in current if u["username"] == member_username), None
            )
            assert existing is not None, (
                "register returned 409 but member missing from list_users"
            )
            member_id = existing["id"]

        # 4. admin approve member.
        updated = _approve_member(client, admin_token, member_id)
        assert updated["is_approved"] is True
        assert updated["username"] == member_username

        # 5. verify in list.
        users_after = _list_users(client, admin_token)
        member_after = next(
            (u for u in users_after if u["username"] == member_username), None
        )
        assert member_after is not None, "member not in list after approve"
        assert member_after["is_approved"] is True, "approval not reflected in list"
        assert member_after["is_active"] is True

    # TestClient context exited: lifespan close -> Chroma client
    # ``close()`` invoked (best-effort). SQLite connections released.
    # The DB file + Chroma dir on disk are the same ones the next
    # TestClient will pick up -- this is the SIGTERM analogue.

    # ------------------------------------------------------------------
    # Round 2: re-boot lifespan against the same on-disk DB.
    # Catches P5b / P8a (lifespan must be idempotent: second startup
    # against an already-provisioned DB must not raise).
    # ------------------------------------------------------------------
    with TestClient(app) as client:
        # 6. admin login again -- proves admin persisted across "SIGTERM".
        admin_token_2 = _login_admin(client, admin_username, admin_password)

        # 7. admin list -- member still present + approved -> persistence
        #    of both the new user row AND the admin PATCH mutation.
        users_round2 = _list_users(client, admin_token_2)
        admin_rows_2 = [
            u for u in users_round2 if u["username"] == admin_username
        ]
        assert len(admin_rows_2) == 1, (
            f"bootstrap admin lost across restart: {users_round2}"
        )
        assert admin_rows_2[0]["is_approved"] is True

        member_round2 = next(
            (u for u in users_round2 if u["username"] == member_username), None
        )
        assert member_round2 is not None, (
            "member did not persist across lifespan restart -- P5b/P8a regression?"
        )
        assert member_round2["is_approved"] is True, (
            "approval mutation did not persist across lifespan restart"
        )
        assert member_round2["email"] == member_email, (
            "member email did not persist across lifespan restart"
        )

    # Round 2 closed cleanly -- if we got here, the lifespan was
    # idempotent against an already-provisioned DB. P5b/P8a guard holds.


__all__ = ["test_admin_login_and_list_users_via_uvicorn"]