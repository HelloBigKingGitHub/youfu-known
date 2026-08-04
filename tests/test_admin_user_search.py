"""End-to-end tests for ``app.admin.users.list_users`` (Phase 2.0).

The new admin router exposes a search/filter/pagination surface over
``UserStore.search_users``. These tests pin down the contract that
the admin SPA relies on:

- ``q`` substring match against ``username`` *or* ``email``
  (case-insensitive)
- ``role`` exact filter
- ``is_approved`` / ``is_active`` boolean filters
- ``limit`` / ``offset`` pagination, with ``limit`` clamped to 200
- envelope shape ``{code: 0, data: {total, items, limit, offset}}``
- error cases (invalid role / boolean / oversized limit) return HTTP 400
- non-admin callers see HTTP 403

The fixtures drive the real ``TestClient`` + ``UserStore`` -- mocking
``search_users`` would only re-test the mock.
"""

from __future__ import annotations

from typing import Dict

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth.deps import require_admin
from app.auth.models import User, UserRole
from app.auth.security import hash_password
from app.auth.storage import UserStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_store(client: TestClient) -> UserStore:
    """Seed the UserStore with a deterministic mix of users.

    Layout (after this fixture runs):

    - ``root``           -- bootstrapped admin (from lifespan)
    - ``alice``          -- approved member, alice@example.com
    - ``bob``            -- approved member, user-bob@example.com
    - ``carol``          -- approved member, carol@example.com
    - ``disabled``       -- approved + inactive member
    - ``pending``        -- not-approved member
    - ``admin2``         -- second admin
    """
    store: UserStore = client.app.state.user_store  # type: ignore[attr-defined]

    def _create(
        username: str,
        *,
        role: UserRole,
        is_approved: bool = True,
        is_active: bool = True,
        email: str = "",
    ) -> User:
        return store.create_user(
            username,
            hash_password("test-pw", rounds=4),
            role=role,
            is_approved=is_approved,
            is_active=is_active,
            email=email,
        )

    _create("alice", role=UserRole.MEMBER, email="alice@example.com")
    _create("bob", role=UserRole.MEMBER, email="user-bob@example.com")
    _create("carol", role=UserRole.MEMBER, email="carol@example.com")
    _create(
        "disabled",
        role=UserRole.MEMBER,
        is_active=False,
        email="disabled@example.com",
    )
    _create(
        "pending",
        role=UserRole.MEMBER,
        is_approved=False,
        email="pending@example.com",
    )
    _create("admin2", role=UserRole.ADMIN)
    return store


@pytest.fixture
def member_blocker(client: TestClient) -> TestClient:
    """Install ``require_admin`` as a 403 in front of the test client.

    Used to verify that the new search/filter endpoint inherits the
    admin gate via its ``Depends(require_admin)`` declaration.
    """
    def _deny() -> User:
        raise HTTPException(
            status_code=403, detail="admin role required"
        )

    client.app.dependency_overrides[require_admin] = _deny
    return client


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


def test_list_users_envelope_shape(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """Default response is the documented envelope."""
    resp = admin_client.get("/api/admin/users")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert set(data.keys()) == {"total", "items", "limit", "offset"}
    # 6 seeded users + the bootstrap admin = 7.
    assert data["total"] == 7
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert isinstance(data["items"], list)
    assert len(data["items"]) == 7


# ---------------------------------------------------------------------------
# Search (q)
# ---------------------------------------------------------------------------


def test_search_by_username_substring(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """``?q=ali`` matches ``alice`` (case-insensitive substring)."""
    resp = admin_client.get("/api/admin/users", params={"q": "ali"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    usernames = {u["username"] for u in data["items"]}
    assert usernames == {"alice"}
    assert data["total"] == 1


def test_search_by_email_substring(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """``?q=user-bob@example.com`` matches Bob's email exactly.

    ``alice@example.com`` and ``carol@example.com`` share the
    ``@example.com`` suffix but the substring ``user-bob@`` only
    appears in Bob's email, so the case-insensitive substring
    search returns Bob alone.
    """
    resp = admin_client.get(
        "/api/admin/users", params={"q": "user-bob@"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    usernames = {u["username"] for u in data["items"]}
    assert usernames == {"bob"}


def test_search_is_case_insensitive(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """Substring search ignores case in both query and stored value."""
    upper = admin_client.get("/api/admin/users", params={"q": "ALICE"})
    mixed = admin_client.get("/api/admin/users", params={"q": "AlIcE"})
    assert {u["username"] for u in upper.json()["data"]["items"]} == {"alice"}
    assert {u["username"] for u in mixed.json()["data"]["items"]} == {"alice"}


def test_search_with_no_matches(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """Empty result set returns ``items=[]`` and ``total=0``."""
    resp = admin_client.get(
        "/api/admin/users", params={"q": "definitely-no-such-user"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["items"] == []
    assert data["total"] == 0


# ---------------------------------------------------------------------------
# Filter (role / is_approved / is_active)
# ---------------------------------------------------------------------------


def test_filter_by_role_admin(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """``?role=admin`` returns the two admins (root + admin2)."""
    resp = admin_client.get("/api/admin/users", params={"role": "admin"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    usernames = {u["username"] for u in data["items"]}
    assert usernames == {"root", "admin2"}
    assert all(u["role"] == "admin" for u in data["items"])


def test_filter_by_role_member(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """``?role=member`` returns every non-admin user."""
    resp = admin_client.get("/api/admin/users", params={"role": "member"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert all(u["role"] == "member" for u in data["items"])
    assert data["total"] == 5


def test_filter_by_is_approved_true(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """``?is_approved=true`` excludes the pending member."""
    resp = admin_client.get(
        "/api/admin/users", params={"is_approved": "true"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    usernames = {u["username"] for u in data["items"]}
    assert "pending" not in usernames
    assert all(u["is_approved"] for u in data["items"])


def test_filter_by_is_approved_false(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """``?is_approved=false`` returns exactly the pending member."""
    resp = admin_client.get(
        "/api/admin/users", params={"is_approved": "false"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    usernames = {u["username"] for u in data["items"]}
    assert usernames == {"pending"}
    assert all(not u["is_approved"] for u in data["items"])


def test_filter_by_is_active_false(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """``?is_active=false`` returns the disabled member only."""
    resp = admin_client.get(
        "/api/admin/users", params={"is_active": "false"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    usernames = {u["username"] for u in data["items"]}
    assert usernames == {"disabled"}


def test_combined_filters(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """``role=member`` + ``is_approved=true`` + ``is_active=true``.

    Excludes the admin pair, the disabled user, and the pending
    member -- leaving alice / bob / carol.
    """
    resp = admin_client.get(
        "/api/admin/users",
        params={
            "role": "member",
            "is_approved": "true",
            "is_active": "true",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    usernames = {u["username"] for u in data["items"]}
    assert usernames == {"alice", "bob", "carol"}


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_pagination_limit_offset(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """``?limit=2&offset=0`` returns the first two rows in the order
    dictated by the storage layer (newest first).
    """
    resp = admin_client.get(
        "/api/admin/users", params={"limit": 2, "offset": 0}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["limit"] == 2
    assert data["offset"] == 0
    assert data["total"] == 7
    assert len(data["items"]) == 2


def test_pagination_second_page(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """``?limit=2&offset=2`` returns the second page; combined with
    the first page they cover distinct rows.
    """
    first = admin_client.get(
        "/api/admin/users", params={"limit": 2, "offset": 0}
    ).json()["data"]["items"]
    second = admin_client.get(
        "/api/admin/users", params={"limit": 2, "offset": 2}
    ).json()["data"]["items"]
    assert len(first) == 2
    assert len(second) == 2
    first_ids = {u["id"] for u in first}
    second_ids = {u["id"] for u in second}
    assert first_ids.isdisjoint(second_ids)


def test_pagination_offset_past_end(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """``offset`` past the last row returns an empty page but still
    reports the correct ``total``.
    """
    resp = admin_client.get(
        "/api/admin/users", params={"limit": 5, "offset": 100}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["items"] == []
    assert data["total"] == 7


def test_pagination_with_filter(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """Pagination respects active filters: ``role=member`` (5 total)
    plus ``limit=2`` returns 2 items and ``total=5``.
    """
    resp = admin_client.get(
        "/api/admin/users",
        params={"role": "member", "limit": 2, "offset": 0},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 5
    assert len(data["items"]) == 2


def test_limit_above_max_returns_400(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """``limit > 200`` is rejected with HTTP 400 (FastAPI's Query clamp)."""
    resp = admin_client.get("/api/admin/users", params={"limit": 9999})
    assert resp.status_code == 400, resp.text


def test_negative_offset_returns_400(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """``offset < 0`` is rejected with HTTP 400."""
    resp = admin_client.get("/api/admin/users", params={"offset": -1})
    assert resp.status_code == 400, resp.text


# ---------------------------------------------------------------------------
# Bad inputs
# ---------------------------------------------------------------------------


def test_invalid_role_returns_400(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """``?role=foo`` is rejected with HTTP 400 + clear error message."""
    resp = admin_client.get("/api/admin/users", params={"role": "foo"})
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert "role" in body["message"].lower()


def test_invalid_boolean_returns_400(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """``?is_approved=maybe`` is rejected with HTTP 400."""
    resp = admin_client.get(
        "/api/admin/users", params={"is_approved": "maybe"}
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert "boolean" in body["message"].lower()


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_list_users_requires_admin(
    member_blocker: TestClient, seeded_store: UserStore
) -> None:
    """A non-admin caller sees HTTP 403 on the new list endpoint."""
    resp = member_blocker.get("/api/admin/users")
    assert resp.status_code == 403, resp.text
    assert "admin role required" in resp.json()["message"]


# ---------------------------------------------------------------------------
# Stats endpoint
# ---------------------------------------------------------------------------


def test_user_stats_returns_counts(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """``GET /api/admin/users/{id}/stats`` returns zero counts on a
    freshly-created user with no KB / doc / chat activity.
    """
    target = next(
        u for u in seeded_store.list_users() if u.username == "alice"
    )
    resp = admin_client.get(
        f"/api/admin/users/{target.id}/stats"
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data == {
        "user_id": target.id,
        "kb_count": 0,
        "doc_count": 0,
        "chat_count": 0,
    }


def test_user_stats_404_for_unknown_user(
    admin_client: TestClient, seeded_store: UserStore
) -> None:
    """Unknown user id surfaces HTTP 404."""
    resp = admin_client.get("/api/admin/users/no-such-id/stats")
    assert resp.status_code == 404, resp.text
    assert "not found" in resp.json()["message"].lower()


__all__ = [
    "test_list_users_envelope_shape",
    "test_search_by_username_substring",
    "test_search_by_email_substring",
    "test_search_is_case_insensitive",
    "test_search_with_no_matches",
    "test_filter_by_role_admin",
    "test_filter_by_role_member",
    "test_filter_by_is_approved_true",
    "test_filter_by_is_approved_false",
    "test_filter_by_is_active_false",
    "test_combined_filters",
    "test_pagination_limit_offset",
    "test_pagination_second_page",
    "test_pagination_offset_past_end",
    "test_pagination_with_filter",
    "test_limit_above_max_returns_400",
    "test_negative_offset_returns_400",
    "test_invalid_role_returns_400",
    "test_invalid_boolean_returns_400",
    "test_list_users_requires_admin",
    "test_user_stats_returns_counts",
    "test_user_stats_404_for_unknown_user",
]
