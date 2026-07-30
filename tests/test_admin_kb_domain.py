"""Tests for the ``admin-kb.sxy.homes`` domain migration.

The admin SPA URL migrated from the legacy three-segment
``admin.kb.sxy.homes`` to the single-label two-segment
``admin-kb.sxy.homes`` (matching the cross-subdomain cookie scope
``Domain=.sxy.homes``). These tests pin the new contract:

- Host header dispatch (``kb.sxy.homes`` -> KB SPA, ``admin-kb.sxy.homes``
  -> admin SPA).
- Fallback routing for unknown hosts (defaults to KB SPA so bare IP /
  unmapped dev hosts still serve a page).
- CSRF middleware: legacy ``admin.kb.sxy.homes`` Origin is rejected
  with 403 (proves the migration is final -- the old host is no
  longer trusted).
- CSRF middleware: the new ``admin-kb.sxy.homes`` Origin is allowed
  through (state-changing requests reach the auth dependency rather
  than the CSRF gate).

For the host-dispatch tests we mint fake ``web/dist`` and
``admin-web/dist`` directories under pytest's ``tmp_path`` and patch
the resolver functions in :mod:`app.static_router` to point at them.
This avoids touching the real worktree on disk (no leftover
``index.html`` artefacts in ``web/dist`` / ``admin-web/dist``).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fake dist builders
# ---------------------------------------------------------------------------


_KB_INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <title>youfu-known · 个人知识库</title>
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>
"""


_ADMIN_INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <title>youfu-known 管理后台</title>
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>
"""


def _make_fake_dist(tmp_path: Path, name: str, html: str) -> Path:
    """Create ``tmp_path/<name>/index.html`` with the given HTML body.

    Returns the directory path. The directory also has an empty
    ``assets/`` subdir because :mod:`app.static_router`'s asset
    dispatcher mounts each dist's ``assets/`` as its own
    ``StaticFiles`` instance at startup, which fails if the directory
    is missing.
    """
    dist = tmp_path / name
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(html, encoding="utf-8")
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    return dist


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_client_with_fake_dists(
    tmp_path: Path, monkeypatch, *, with_kb: bool, with_admin: bool
) -> TestClient:
    """Construct a TestClient whose SPA dispatcher resolves to fake dists.

    Patches ``app.static_router._resolve_kb_dist`` and
    ``app.static_router._resolve_admin_dist`` so the dists come from
    ``tmp_path`` rather than the worktree's ``web/dist`` /
    ``admin-web/dist``. Either or both can be created via the ``*_``
    flags.
    """
    from app.static_router import SpaBundle

    # Pre-create dists that the dispatcher will serve. Either may be
    # skipped to exercise the "dist not built" branch.
    kb_dist = _make_fake_dist(tmp_path, "kb-dist", _KB_INDEX_HTML) if with_kb else None
    admin_dist = (
        _make_fake_dist(tmp_path, "admin-dist", _ADMIN_INDEX_HTML)
        if with_admin
        else None
    )

    def fake_resolve_kb(project_root: Path) -> SpaBundle:  # noqa: ARG001
        if kb_dist is None:
            return SpaBundle(name="kb", dist_dir=tmp_path / "kb-dist-missing",
                             available=False)
        return SpaBundle(name="kb", dist_dir=kb_dist, available=True)

    def fake_resolve_admin(project_root: Path) -> SpaBundle:  # noqa: ARG001
        if admin_dist is None:
            return SpaBundle(name="admin", dist_dir=tmp_path / "admin-dist-missing",
                             available=False)
        return SpaBundle(name="admin", dist_dir=admin_dist, available=True)

    import app.static_router as static_router
    monkeypatch.setattr(static_router, "_resolve_kb_dist", fake_resolve_kb)
    monkeypatch.setattr(static_router, "_resolve_admin_dist", fake_resolve_admin)

    from main import create_app

    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_host_dispatch_kb_serves_main_spa(tmp_path, monkeypatch):
    """``Host: kb.sxy.homes`` GET / returns the KB SPA's index.html."""
    client = _build_client_with_fake_dists(
        tmp_path, monkeypatch, with_kb=True, with_admin=True
    )
    with client:
        response = client.get("/", headers={"Host": "kb.sxy.homes"})
    assert response.status_code == 200, response.text
    assert "youfu-known · 个人知识库" in response.text


def test_host_dispatch_admin_kb_serves_admin_spa(tmp_path, monkeypatch):
    """``Host: admin-kb.sxy.homes`` GET / returns the admin SPA's index.html."""
    client = _build_client_with_fake_dists(
        tmp_path, monkeypatch, with_kb=True, with_admin=True
    )
    with client:
        response = client.get("/", headers={"Host": "admin-kb.sxy.homes"})
    assert response.status_code == 200, response.text
    assert "youfu-known 管理后台" in response.text


def test_host_dispatch_unknown_host_falls_back_to_kb(tmp_path, monkeypatch):
    """Unknown hosts default to the KB SPA (no 404 to bare IP access)."""
    client = _build_client_with_fake_dists(
        tmp_path, monkeypatch, with_kb=True, with_admin=True
    )
    with client:
        response = client.get("/", headers={"Host": "unknown.example.com"})
    assert response.status_code == 200, response.text
    assert "youfu-known · 个人知识库" in response.text


def test_csrf_blocks_legacy_admin_origin(tmp_path, monkeypatch):
    """The legacy three-segment admin host is rejected with 403.

    After the URL moved to ``admin-kb.sxy.homes`` the legacy
    ``admin.kb.sxy.homes`` host should produce 403 from the CSRF
    middleware (logs a warning) rather than being trusted. Verifies the
    legacy cleanup actually fires.
    """
    client = _build_client_with_fake_dists(
        tmp_path, monkeypatch, with_kb=False, with_admin=False
    )
    with client:
        response = client.post(
            "/api/auth/logout",
            headers={"Origin": "https://admin.kb.sxy.homes"},
        )
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == 403
    assert "invalid origin" in body["message"].lower()


def test_csrf_allows_new_admin_kb_origin(tmp_path, monkeypatch):
    """The new admin-kb.sxy.homes Origin passes the CSRF gate.

    The handler still returns 401 (no auth) -- the point is the
    middleware must NOT 403. Proves the new origin made it onto the
    allowlist.
    """
    client = _build_client_with_fake_dists(
        tmp_path, monkeypatch, with_kb=False, with_admin=False
    )
    with client:
        response = client.delete(
            "/api/admin/kbs/does-not-exist",
            headers={"Origin": "https://admin-kb.sxy.homes"},
        )
    assert response.status_code != 403, response.text
    assert response.status_code == 401
