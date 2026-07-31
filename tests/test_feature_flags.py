"""Tests for feature flags (Phase Feature Flags)."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.feature_flags import Feature, FeatureFlagService


def _create_user(
    client: TestClient, username: str, password: str = "test_password_123"
) -> str:
    """Register a user (unapproved), return user_id."""
    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@test.com",
            "password": password,
            "turnstile_token": "",
        },
    )
    assert response.status_code in (200, 201), response.text
    listed = client.get("/api/admin/users")
    assert listed.status_code == 200, listed.text
    return next(
        user["id"]
        for user in listed.json()["data"]
        if user["username"] == username
    )


def test_default_features_for_new_user(admin_client: TestClient) -> None:
    """新 user 默认 feature 状态: 没有手动 override。"""
    user_id = _create_user(admin_client, "ff_default_user")

    response = admin_client.get(f"/api/admin/users/{user_id}/features")

    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0
    assert response.json()["data"] == []


def test_admin_can_grant_feature_to_user(admin_client: TestClient) -> None:
    """Admin PUT feature flag 后可在列表中看到启用状态。"""
    user_id = _create_user(admin_client, "ff_grant_user")

    response = admin_client.put(
        f"/api/admin/users/{user_id}/features/kb_chat",
        json={"enabled": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["enabled"] is True
    listed = admin_client.get(f"/api/admin/users/{user_id}/features")
    assert listed.status_code == 200, listed.text
    assert any(
        flag["feature"] == "kb_chat" and flag["enabled"] is True
        for flag in listed.json()["data"]
    )


def test_user_without_feature_gets_403(client: TestClient) -> None:
    """Member 调用默认关闭的 KB chat 功能时返回 403。"""
    from tests.test_admin_phase15 import (
        _create_approved_member,
        _login_admin,
    )

    admin = _login_admin(client)
    _create_approved_member(admin, "ff_deny_user", "test_password_123")

    response = client.post(
        "/api/auth/login",
        json={
            "username": "ff_deny_user",
            "password": "test_password_123",
        },
    )
    assert response.status_code == 200, response.text
    token = response.json()["data"]["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"

    response = client.post(
        "/api/kbs/any-kb-id/chat",
        json={"question": "test"},
    )

    assert response.status_code == 403, response.text
    payload = response.json()
    detail = payload.get("detail") or payload.get("message", "")
    assert "kb_chat" in detail or "disabled" in detail.lower()


def test_admin_can_revoke_feature(admin_client: TestClient) -> None:
    """Admin revoke 后立即在列表中看到关闭状态。"""
    user_id = _create_user(admin_client, "ff_revoke_user")

    grant = admin_client.put(
        f"/api/admin/users/{user_id}/features/kb_chat",
        json={"enabled": True},
    )
    assert grant.status_code == 200, grant.text
    revoke = admin_client.put(
        f"/api/admin/users/{user_id}/features/kb_chat",
        json={"enabled": False},
    )
    assert revoke.status_code == 200, revoke.text

    listed = admin_client.get(f"/api/admin/users/{user_id}/features")
    assert listed.status_code == 200, listed.text
    flag = next(
        flag for flag in listed.json()["data"] if flag["feature"] == "kb_chat"
    )
    assert flag["enabled"] is False


def test_feature_flag_survives_session_restart(
    admin_client: TestClient, tmp_path: Path
) -> None:
    """Feature flag 持久化到 SQLite，可由新 service 实例读取。"""
    del tmp_path
    from app import config as config_mod

    settings = config_mod.get_settings()
    db_path = Path(settings.storage.meta_db)
    user_id = _create_user(admin_client, "ff_persist_user")

    response = admin_client.put(
        f"/api/admin/users/{user_id}/features/kb_chat",
        json={"enabled": True},
    )
    assert response.status_code == 200, response.text

    service_new = FeatureFlagService(db_path)

    assert service_new.is_enabled(user_id, Feature.KB_CHAT) is True
