from __future__ import annotations

import asyncio
from typing import Any, Callable

import httpx
import pytest

from app.auth import turnstile


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", turnstile.TURNSTILE_VERIFY_URL)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                "Turnstile response failed", request=request, response=response
            )

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    def __init__(
        self,
        response: _FakeResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, url: str, *, data: dict[str, Any]) -> _FakeResponse:
        self.calls.append({"url": url, "data": data})
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_verify_turnstile_skips_when_secret_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("YOUFU_TURNSTILE_SECRET", raising=False)

    result = _run(turnstile.verify_turnstile(""))

    assert result is True


def test_verify_turnstile_accepts_cloudflare_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOUFU_TURNSTILE_SECRET", turnstile.TURNSTILE_TEST_SECRET)
    client = _FakeAsyncClient(_FakeResponse({"success": True}))
    monkeypatch.setattr(turnstile.httpx, "AsyncClient", lambda **_: client)

    result = _run(turnstile.verify_turnstile("valid-token", "203.0.113.10"))

    assert result is True
    assert client.calls == [
        {
            "url": turnstile.TURNSTILE_VERIFY_URL,
            "data": {
                "secret": turnstile.TURNSTILE_TEST_SECRET,
                "response": "valid-token",
                "remoteip": "203.0.113.10",
            },
        }
    ]


def test_verify_turnstile_rejects_cloudflare_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOUFU_TURNSTILE_SECRET", "production-secret")
    client = _FakeAsyncClient(_FakeResponse({"success": False}))
    monkeypatch.setattr(turnstile.httpx, "AsyncClient", lambda **_: client)

    result = _run(turnstile.verify_turnstile("bad-token"))

    assert result is False
    assert client.calls[0]["data"] == {
        "secret": "production-secret",
        "response": "bad-token",
    }


def test_verify_turnstile_rejects_cloudflare_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOUFU_TURNSTILE_SECRET", "production-secret")
    client = _FakeAsyncClient(error=httpx.ConnectError("offline"))
    monkeypatch.setattr(turnstile.httpx, "AsyncClient", lambda **_: client)

    result = _run(turnstile.verify_turnstile("token"))

    assert result is False


def test_register_in_dev_mode_without_token(client, auth_admin) -> None:
    response = client.post(
        "/api/auth/register",
        json={"username": "devmember", "password": "devmemberpw"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["data"]["is_approved"] is False


def test_register_rejects_bad_turnstile_token(
    client,
    auth_admin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOUFU_TURNSTILE_SECRET", "production-secret")
    client_stub = _FakeAsyncClient(_FakeResponse({"success": False}))
    monkeypatch.setattr(turnstile.httpx, "AsyncClient", lambda **_: client_stub)

    response = client.post(
        "/api/auth/register",
        json={
            "username": "blockedmember",
            "password": "blockedpw",
            "turnstile_token": "bad-token",
        },
    )

    assert response.status_code == 400, response.text
    assert "captcha verification failed" in response.json()["message"]
    assert client.app.state.user_store.get_by_username("blockedmember") is None


def test_register_approve_then_login(client, auth_admin, monkeypatch) -> None:
    monkeypatch.delenv("YOUFU_TURNSTILE_SECRET", raising=False)
    register = client.post(
        "/api/auth/register",
        json={"username": "pendingmember", "password": "pendingpw"},
    )
    assert register.status_code == 201, register.text

    pending_login = client.post(
        "/api/auth/login",
        json={"username": "pendingmember", "password": "pendingpw"},
    )
    assert pending_login.status_code == 403

    admin_login = client.post(
        "/api/auth/login",
        json={"username": "root", "password": "rootpw"},
    )
    assert admin_login.status_code == 200, admin_login.text
    member = client.app.state.user_store.get_by_username("pendingmember")
    assert member is not None

    approval = client.patch(
        f"/api/admin/users/{member.id}",
        json={"is_approved": True},
    )
    assert approval.status_code == 200, approval.text

    client.post("/api/auth/logout")
    approved_login = client.post(
        "/api/auth/login",
        json={"username": "pendingmember", "password": "pendingpw"},
    )
    assert approved_login.status_code == 200, approved_login.text
    assert approved_login.json()["data"]["user"]["is_approved"] is True
