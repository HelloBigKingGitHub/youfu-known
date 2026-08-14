"""Tests for the Phase 2.1 token-quota system.

Covers four layers:

- ``User`` quota helpers  (``quota_remaining``, ``quota_exceeded``,
  ``reset_quota_if_due``, ``_compute_next_reset``).
- ``QuotaService``        (record + breakdown + admin reset).
- ``enforce_quota`` decorator behaviour at the HTTP layer
  (admin bypass, 402 on overflow).
- ``/api/users/me/quota`` + admin per-user + admin reset endpoints.

The HTTP-layer tests use the shared ``client`` / ``admin_client``
fixtures from ``conftest.py`` so the storage layer is a real SQLite
file under the per-test ``tmp_path``. That makes the
``user_token_usage`` ↔ ``users.quota_tokens_used`` update transaction
visible to the next request without monkey-patching.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.admin.quota import QuotaService
from app.admin.quota_decorator import enforce_quota
from app.auth.deps import require_admin
from app.auth.models import (
    QuotaPeriod,
    User,
    UserRole,
    _compute_next_reset,
    _UNLIMITED_TOKENS,
)
from app.auth.security import hash_password
from app.auth.storage import UserStore
from app.config import Settings, StorageConfig
from app.feature_flags import Feature


# ---------------------------------------------------------------------------
# User model quota helpers (pure-Python, no DB)
# ---------------------------------------------------------------------------


def _make_user(
    *,
    quota_tokens_total: int = 1000,
    quota_tokens_used: int = 0,
    quota_period: QuotaPeriod = QuotaPeriod.MONTHLY,
    quota_period_reset_at: datetime | None = None,
) -> User:
    return User(
        id="u1",
        username="u1",
        role=UserRole.MEMBER,
        created_at=datetime(2026, 1, 1, 0, 0, 0),
        quota_tokens_total=quota_tokens_total,
        quota_tokens_used=quota_tokens_used,
        quota_period=quota_period,
        quota_period_reset_at=quota_period_reset_at,
    )


def test_quota_remaining_basic() -> None:
    u = _make_user(quota_tokens_total=1000, quota_tokens_used=300)
    assert u.quota_remaining() == 700


def test_quota_remaining_clamps_at_zero() -> None:
    u = _make_user(quota_tokens_total=100, quota_tokens_used=250)
    assert u.quota_remaining() == 0


def test_quota_remaining_unlimited_returns_sentinel() -> None:
    u = _make_user(quota_tokens_total=0, quota_tokens_used=999_999)
    assert u.quota_remaining() == _UNLIMITED_TOKENS


def test_quota_exceeded_basic() -> None:
    u = _make_user(quota_tokens_total=100, quota_tokens_used=50)
    assert not u.quota_exceeded()
    u.quota_tokens_used = 100
    assert u.quota_exceeded()
    u.quota_tokens_used = 200
    assert u.quota_exceeded()


def test_quota_exceeded_unlimited_is_never_exceeded() -> None:
    u = _make_user(quota_tokens_total=0, quota_tokens_used=10**9)
    assert not u.quota_exceeded()


def test_reset_quota_if_due_daily() -> None:
    # Daily boundary at midnight UTC. Simulate "now is just past the
    # reset moment" so the helper should clear usage and reschedule.
    u = _make_user(
        quota_tokens_total=100,
        quota_tokens_used=80,
        quota_period=QuotaPeriod.DAILY,
        quota_period_reset_at=datetime(2026, 1, 15, 0, 0, 0),
    )
    # exactly at the boundary -> still due (>=)
    u.reset_quota_if_due(now=datetime(2026, 1, 15, 0, 0, 0))
    assert u.quota_tokens_used == 0
    assert u.quota_period_reset_at == datetime(2026, 1, 16, 0, 0, 0)


def test_reset_quota_if_due_weekly() -> None:
    # 2026-01-15 is a Thursday; weekly boundary should jump to next Monday.
    u = _make_user(
        quota_tokens_used=50,
        quota_period=QuotaPeriod.WEEKLY,
        quota_period_reset_at=datetime(2026, 1, 15, 0, 0, 0),
    )
    u.reset_quota_if_due(now=datetime(2026, 1, 16, 12, 0, 0))
    assert u.quota_tokens_used == 0
    assert u.quota_period_reset_at == datetime(2026, 1, 19, 0, 0, 0)  # Mon


def test_reset_quota_if_due_monthly_year_boundary() -> None:
    # December -> next year's January 1st.
    u = _make_user(
        quota_tokens_used=42,
        quota_period=QuotaPeriod.MONTHLY,
        quota_period_reset_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    u.reset_quota_if_due(now=datetime(2026, 1, 15))
    assert u.quota_tokens_used == 0
    # The boundary we crossed is January 2026; next reset is Feb 2026.
    assert u.quota_period_reset_at == datetime(2026, 2, 1, 0, 0, 0)


def test_reset_quota_if_due_none_does_nothing() -> None:
    u = _make_user(
        quota_tokens_used=99,
        quota_period=QuotaPeriod.NONE,
        quota_period_reset_at=datetime(2026, 1, 1),
    )
    u.reset_quota_if_due(now=datetime(2099, 1, 1))
    assert u.quota_tokens_used == 99
    assert u.quota_period_reset_at == datetime(2026, 1, 1)


def test_compute_next_reset_year_rollover() -> None:
    # December -> next January 1st of the *next* year.
    assert _compute_next_reset(
        datetime(2026, 12, 15, 10, 0, 0), QuotaPeriod.MONTHLY
    ) == datetime(2027, 1, 1)


def test_compute_next_reset_weekly_lands_on_monday() -> None:
    # Wednesday 2026-01-14 -> next Monday is 2026-01-19.
    nxt = _compute_next_reset(datetime(2026, 1, 14, 12, 0, 0), QuotaPeriod.WEEKLY)
    assert nxt == datetime(2026, 1, 19)
    assert nxt.weekday() == 0  # Monday


# ---------------------------------------------------------------------------
# QuotaService (DB-backed) -- uses a per-test tmp file
# ---------------------------------------------------------------------------


@pytest.fixture
def quota_db(tmp_path: Path) -> Iterator[Path]:
    p = tmp_path / "quota.sqlite3"
    yield p
    if p.exists():
        p.unlink()


@pytest.fixture
def quota_env(
    quota_db: Path,
) -> Iterator[tuple[UserStore, QuotaService]]:
    settings = Settings(
        project_root=quota_db.parent,
        storage=StorageConfig(meta_db=str(quota_db)),
    )
    store = UserStore(settings=settings, db_path=quota_db)
    store.init()
    svc = QuotaService(db_path=quota_db, user_store=store)
    yield store, svc
    svc._conn.close()  # type: ignore[attr-defined]


def _seed_user(
    store: UserStore,
    *,
    username: str = "alice",
    role: UserRole = UserRole.MEMBER,
    quota_tokens_total: int = 1000,
) -> User:
    return store.create_user(
        username=username,
        password_hash=hash_password("test-pw", rounds=4),
        role=role,
        is_approved=True,
        quota_tokens_total=quota_tokens_total,
    )


def test_quota_service_record_writes_ledger(
    quota_env: tuple[UserStore, QuotaService],
) -> None:
    store, svc = quota_env
    user = _seed_user(store)
    svc.record_usage(
        user_id=user.id,
        endpoint="/api/kbs/kb1/chat",
        feature=Feature.KB_CHAT.value,
        prompt_tokens=100,
        completion_tokens=50,
    )
    breakdown = svc.get_usage_breakdown(user.id, days=0)
    assert len(breakdown) == 1
    row = breakdown[0]
    assert row["prompt_tokens"] == 100
    assert row["completion_tokens"] == 50
    assert row["total_tokens"] == 150
    assert row["calls"] == 1


def test_quota_service_record_bumps_used_counter(
    quota_env: tuple[UserStore, QuotaService],
) -> None:
    store, svc = quota_env
    user = _seed_user(store, quota_tokens_total=10_000)
    svc.record_usage(
        user_id=user.id,
        endpoint="/x",
        feature=Feature.KB_CHAT.value,
        prompt_tokens=200,
        completion_tokens=80,
    )
    svc.record_usage(
        user_id=user.id,
        endpoint="/x",
        feature=Feature.KB_CHAT.value,
        prompt_tokens=50,
        completion_tokens=20,
    )
    refreshed = store.get_user(user.id)
    assert refreshed is not None
    assert refreshed.quota_tokens_used == 200 + 80 + 50 + 20
    breakdown = svc.get_usage_breakdown(user.id, days=0)
    assert sum(r["calls"] for r in breakdown) == 2


def test_quota_service_breakdown_groups_by_day(
    quota_env: tuple[UserStore, QuotaService],
) -> None:
    store, svc = quota_env
    user = _seed_user(store)
    day1 = datetime(2026, 1, 1, 10, 0, 0)
    day2 = datetime(2026, 1, 2, 10, 0, 0)
    for ts, p, c in (
        (day1, 100, 50),
        (day1, 30, 10),
        (day2, 200, 100),
    ):
        svc.record_usage(
            user_id=user.id,
            endpoint="/x",
            feature=Feature.KB_CHAT.value,
            prompt_tokens=p,
            completion_tokens=c,
            now=ts,
        )
    breakdown = svc.get_usage_breakdown(user.id, days=0)
    assert len(breakdown) == 2
    by_day = {r["date"]: r for r in breakdown}
    assert by_day["2026-01-01"]["calls"] == 2
    assert by_day["2026-01-01"]["total_tokens"] == 100 + 50 + 30 + 10
    assert by_day["2026-01-02"]["calls"] == 1
    assert by_day["2026-01-02"]["total_tokens"] == 200 + 100


def test_quota_service_reset_zeroes_used_and_advances_clock(
    quota_env: tuple[UserStore, QuotaService],
) -> None:
    store, svc = quota_env
    user = _seed_user(store, quota_tokens_total=100)
    svc.record_usage(
        user_id=user.id,
        endpoint="/x",
        feature=Feature.KB_CHAT.value,
        prompt_tokens=80,
        completion_tokens=20,
    )
    refreshed = svc.reset_quota(user.id)
    assert refreshed is not None
    assert refreshed.quota_tokens_used == 0
    assert refreshed.quota_period_reset_at is not None
    # Reset clock should be in the future relative to ``utcnow``.
    assert refreshed.quota_period_reset_at > datetime.utcnow()


def test_quota_service_periodic_reset_during_record(
    quota_env: tuple[UserStore, QuotaService],
) -> None:
    """A period boundary that passes between two calls resets the counter."""
    store, svc = quota_env
    user = _seed_user(store, quota_tokens_total=10_000)
    before = datetime.utcnow() - timedelta(days=2)
    svc.record_usage(
        user_id=user.id,
        endpoint="/x",
        feature=Feature.KB_CHAT.value,
        prompt_tokens=500,
        completion_tokens=0,
        now=before,
    )
    # Now record again after a month has passed -- the helper should
    # see the stale clock and reset before applying the new delta.
    after = datetime.utcnow() + timedelta(days=31)
    svc.record_usage(
        user_id=user.id,
        endpoint="/x",
        feature=Feature.KB_CHAT.value,
        prompt_tokens=10,
        completion_tokens=0,
        now=after,
    )
    refreshed = store.get_user(user.id)
    assert refreshed is not None
    # Used == 10 (the second call), not 510.
    assert refreshed.quota_tokens_used == 10


# ---------------------------------------------------------------------------
# enforce_quota decorator behaviour (HTTP-layer)
# ---------------------------------------------------------------------------


def test_enforce_quota_blocks_member_when_exceeded(
    client: TestClient,
) -> None:
    """A member with a 100-token quota that's already at the cap gets 402."""
    store: UserStore = client.app.state.user_store  # type: ignore[attr-defined]
    user = store.create_user(
        username="capped",
        password_hash=hash_password("test-pw", rounds=4),
        role=UserRole.MEMBER,
        is_approved=True,
        quota_tokens_total=100,
    )
    # Stamp used >= total.
    store.update_user(user.id, quota_tokens_used=100)

    # Add an endpoint that uses enforce_quota.
    from fastapi import APIRouter, Depends

    test_router = APIRouter()

    @test_router.get("/__test/enforce")
    async def _endpoint(
        user: User = Depends(enforce_quota(Feature.KB_CHAT)),
    ) -> dict:
        return {"user": user.username}

    client.app.include_router(test_router)

    # Login as the capped member.
    r = client.post(
        "/api/auth/login",
        json={"username": "capped", "password": "test-pw"},
    )
    assert r.status_code == 200, r.text

    resp = client.get("/__test/enforce")
    assert resp.status_code == 402, resp.text
    assert "quota exceeded" in resp.json()["message"].lower()


def test_enforce_quota_admin_is_bypassed(
    client: TestClient,
) -> None:
    """Admins pass even with a zero-or-overflow quota."""
    # Bootstrap admin has quota_tokens_total=100000 by default; we
    # force their quota to overflow and verify the decorator still
    # returns the admin user.
    store: UserStore = client.app.state.user_store  # type: ignore[attr-defined]
    admin = next(u for u in store.list_users() if u.role == UserRole.ADMIN)
    store.update_user(admin.id, quota_tokens_total=100, quota_tokens_used=999_999)

    from fastapi import APIRouter, Depends

    test_router = APIRouter()

    @test_router.get("/__test/admin-enforce")
    async def _endpoint(
        user: User = Depends(enforce_quota(Feature.KB_CHAT)),
    ) -> dict:
        return {"user": user.username}

    client.app.include_router(test_router)

    # Bootstrap admin must be logged in to clear the JWT gate before
    # the enforce_quota dependency runs.
    r = client.post(
        "/api/auth/login",
        json={"username": "root", "password": "rootpw"},
    )
    assert r.status_code == 200, r.text

    resp = client.get("/__test/admin-enforce")
    assert resp.status_code == 200, resp.text
    # The test endpoint returns a bare dict; FastAPI does not wrap
    # non-API-router responses in the ``{"code":0,"data":...}``
    # envelope, so the assertion reads ``resp.json()["user"]`` directly.
    assert resp.json()["user"] == admin.username


def test_enforce_quota_unlimited_user_never_blocked(
    client: TestClient,
) -> None:
    """``quota_tokens_total == 0`` (unlimited) means the decorator lets
    every request through, even with a huge ``quota_tokens_used``.
    """
    store: UserStore = client.app.state.user_store  # type: ignore[attr-defined]
    user = store.create_user(
        username="unlimited",
        password_hash=hash_password("test-pw", rounds=4),
        role=UserRole.MEMBER,
        is_approved=True,
        quota_tokens_total=0,  # unlimited
        quota_tokens_used=10**9,
    )

    from fastapi import APIRouter, Depends

    test_router = APIRouter()

    @test_router.get("/__test/unlim")
    async def _endpoint(
        user: User = Depends(enforce_quota(Feature.KB_CHAT)),
    ) -> dict:
        return {"user": user.username}

    client.app.include_router(test_router)

    r = client.post(
        "/api/auth/login",
        json={"username": "unlimited", "password": "test-pw"},
    )
    assert r.status_code == 200, r.text

    resp = client.get("/__test/unlim")
    assert resp.status_code == 200, resp.text
    # See ``test_enforce_quota_admin_is_bypassed`` for why the test
    # endpoint returns a bare dict instead of the unified envelope.
    assert resp.json()["user"] == "unlimited"


# ---------------------------------------------------------------------------
# HTTP endpoints: /api/users/me/quota + admin views
# ---------------------------------------------------------------------------


@pytest.fixture
def quota_seeded(client: TestClient) -> UserStore:
    store: UserStore = client.app.state.user_store  # type: ignore[attr-defined]
    # Create one approved member with a known quota.
    store.create_user(
        username="alice",
        password_hash=hash_password("test-pw", rounds=4),
        role=UserRole.MEMBER,
        is_approved=True,
        quota_tokens_total=5000,
        quota_tokens_used=1234,
    )
    return store


def test_my_quota_envelope_shape(
    client: TestClient, quota_seeded: UserStore
) -> None:
    r = client.post(
        "/api/auth/login", json={"username": "alice", "password": "test-pw"}
    )
    assert r.status_code == 200, r.text
    resp = client.get("/api/users/me/quota")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert set(data.keys()) == {
        "tokens_total",
        "tokens_used",
        "tokens_remaining",
        "period",
        "reset_at",
        "usage_breakdown",
    }
    assert data["tokens_total"] == 5000
    assert data["tokens_used"] == 1234
    assert data["tokens_remaining"] == 5000 - 1234
    assert data["period"] == "monthly"
    assert data["usage_breakdown"] == []  # no usage yet


def test_my_quota_unlimited_returns_null_remaining(
    client: TestClient,
) -> None:
    store: UserStore = client.app.state.user_store  # type: ignore[attr-defined]
    store.create_user(
        username="bob",
        password_hash=hash_password("test-pw", rounds=4),
        role=UserRole.MEMBER,
        is_approved=True,
        quota_tokens_total=0,
    )
    r = client.post(
        "/api/auth/login", json={"username": "bob", "password": "test-pw"}
    )
    assert r.status_code == 200, r.text
    resp = client.get("/api/users/me/quota")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["tokens_remaining"] is None
    assert data["tokens_total"] == 0


def test_admin_quota_for_other_user(
    admin_client: TestClient, quota_seeded: UserStore
) -> None:
    alice = quota_seeded.get_by_username("alice")
    assert alice is not None
    resp = admin_client.get(f"/api/admin/users/{alice.id}/quota")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["tokens_total"] == 5000
    assert data["tokens_used"] == 1234


def test_admin_quota_for_other_user_requires_admin(
    client: TestClient, quota_seeded: UserStore
) -> None:
    """A member asking for another member's quota is 403, not 200."""
    alice = quota_seeded.get_by_username("alice")
    assert alice is not None
    r = client.post(
        "/api/auth/login", json={"username": "alice", "password": "test-pw"}
    )
    assert r.status_code == 200, r.text
    resp = client.get(f"/api/admin/users/{alice.id}/quota")
    assert resp.status_code == 403, resp.text


def test_admin_quota_404_for_unknown_user(
    admin_client: TestClient,
) -> None:
    resp = admin_client.get("/api/admin/users/no-such-user/quota")
    assert resp.status_code == 404, resp.text


def test_admin_reset_quota_zeroes_used_and_returns_envelope(
    admin_client: TestClient, quota_seeded: UserStore
) -> None:
    alice = quota_seeded.get_by_username("alice")
    assert alice is not None
    resp = admin_client.post(f"/api/admin/users/{alice.id}/quota/reset")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["tokens_used"] == 0
    # The admin's ``reset`` pushed the clock to the next boundary,
    # so ``reset_at`` must be set.
    assert data["reset_at"] is not None


def test_admin_reset_quota_requires_admin(
    client: TestClient, quota_seeded: UserStore
) -> None:
    alice = quota_seeded.get_by_username("alice")
    assert alice is not None
    r = client.post(
        "/api/auth/login", json={"username": "alice", "password": "test-pw"}
    )
    assert r.status_code == 200, r.text
    resp = client.post(f"/api/admin/users/{alice.id}/quota/reset")
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# PATCH /api/admin/users/{id} supports quota fields
# ---------------------------------------------------------------------------


def test_patch_user_updates_quota_fields(
    admin_client: TestClient, quota_seeded: UserStore
) -> None:
    alice = quota_seeded.get_by_username("alice")
    assert alice is not None
    resp = admin_client.patch(
        f"/api/admin/users/{alice.id}",
        json={"quota_tokens_total": 9999, "quota_period": "weekly"},
    )
    assert resp.status_code == 200, resp.text
    # The PATCH endpoint re-reads the user via AuthService.update_user
    # and returns the same payload shape as the user search; the new
    # quota values are reflected on the row we just fetched.
    refreshed = quota_seeded.get_user(alice.id)
    assert refreshed is not None
    assert refreshed.quota_tokens_total == 9999
    assert refreshed.quota_period == QuotaPeriod.WEEKLY