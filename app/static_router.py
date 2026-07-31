"""Host-based static SPA dispatcher.

The single FastAPI service on port 8000 serves *two* React SPAs, one per
subdomain:

- ``kb.sxy.homes`` (and dev aliases ``localhost:5173`` / ``127.0.0.1:5173``)
  -> ``web/dist`` (the main personal-KB SPA)
- ``admin.sxy.homes`` (and dev alias ``localhost:5174`` /
  ``127.0.0.1:5174``) -> ``admin-web/dist`` (the admin backend SPA)

The router inspects the request ``Host`` header at request time and
dispatches to the appropriate ``StaticFiles`` + SPA fallback. This keeps
the process topology as a single 8000 service: no nginx, no extra
``http.server`` process, no per-subdomain tunnel.

Path resolution for ``admin-web/dist``:

1. ``YOUFU_ADMIN_WEB_DIST`` env var, if set (used by the Pi deploy to
   point at ``/home/youfu/admin-web/dist`` where rsync lands the build).
2. ``<project_root>/admin-web/dist`` (used by local dev where
   ``admin-web/`` lives next to ``web/`` inside the repo).

If a dist is missing, that SPA is treated as "not built". When the admin
URL is hit but the admin dist is missing, we fall back to the KB SPA so
the visitor at least sees a page; when neither dist is built (the
typical local dev / CI scenario where ``npm run build`` hasn't run),
the helper is a no-op -- matching the historical behaviour of
``_register_static``.

CORS / cookie allowlist constants live in :mod:`app.api`; this module
only deals with static asset serving.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Host allowlists
# ---------------------------------------------------------------------------
#
# The KB (main) SPA is served for any host not explicitly routed to the
# admin SPA. This includes the dev Vite servers, the production hostname
# ``kb.sxy.homes``, and any bare-IP access (fallback).
KB_HOSTS: frozenset[str] = frozenset(
    {
        "kb.sxy.homes",
        # Dev Vite (main SPA) -- mirrors ``web/vite.config.ts`` port 5173.
        "localhost:5173",
        "127.0.0.1:5173",
    }
)

# Hosts routed to the admin backend SPA. The new single-label
# two-segment domain ``admin.sxy.homes`` replaces the legacy
# three-segment ``admin.kb.sxy.homes`` so the cross-subdomain cookie
# (``Domain=.sxy.homes``) is naturally scoped.
ADMIN_HOSTS: frozenset[str] = frozenset(
    {
        "admin.sxy.homes",
        # Dev Vite (admin SPA) -- mirrors ``admin-web/vite.config.ts``
        # port 5174.
        "localhost:5174",
        "127.0.0.1:5174",
    }
)


# ---------------------------------------------------------------------------
# dist path resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpaBundle:
    """A single SPA build output we know how to serve.

    ``dist_dir`` is the directory containing the built ``index.html``
    and ``assets/`` subdir. ``available`` is ``False`` when the dist
    hasn't been built (dev mode); callers should treat that as
    "this SPA isn't shippable from this process right now".
    """

    name: str
    dist_dir: Path
    available: bool


def _resolve_kb_dist(project_root: Path) -> SpaBundle:
    dist = project_root / "web" / "dist"
    return SpaBundle(
        name="kb",
        dist_dir=dist,
        available=(dist / "index.html").is_file(),
    )


def _resolve_admin_dist(project_root: Path) -> SpaBundle:
    """Locate ``admin-web/dist`` for either local dev or Pi deploy.

    Pi deploys land the admin build at ``/home/youfu/admin-web/dist``
    (rsync target, separate from the backend repo). Local dev builds
    inside the repo at ``<project_root>/admin-web/dist``.

    Precedence:

    1. ``YOUFU_ADMIN_WEB_DIST`` env var (explicit override for Pi).
    2. ``<project_root>/admin-web/dist`` (local repo layout).
    """
    env_override = os.environ.get("YOUFU_ADMIN_WEB_DIST")
    if env_override:
        dist = Path(env_override).expanduser().resolve()
    else:
        dist = (project_root / "admin-web" / "dist").resolve()
    return SpaBundle(
        name="admin",
        dist_dir=dist,
        available=(dist / "index.html").is_file(),
    )


def _host_for(request: Request) -> str:
    """Strip the port (if any) from the ``Host`` header.

    ``Host: kb.sxy.homes:443`` -> ``kb.sxy.homes`` (so it can be matched
    against the bare hostnames above). When the header is missing we
    return an empty string -- the caller treats that as
    "unrouted, use the default (KB) bundle".
    """
    raw = request.headers.get("host") or ""
    if raw.startswith("["):
        # IPv6 literal: ``[::1]:8000``
        end = raw.find("]")
        if end == -1:
            return raw
        return raw[: end + 1]
    if ":" in raw:
        raw = raw.split(":", 1)[0]
    return raw.lower()


def _pick_bundle(
    request: Request, kb: SpaBundle, admin: SpaBundle
) -> SpaBundle:
    """Return the SPA bundle to serve for ``request``.

    Resolution order:

    1. ``ADMIN_HOSTS`` -> admin bundle (falling back to KB if the admin
       dist isn't built, since users hitting the admin URL with a
       missing build should still see *something* rather than a bare
       404 -- the KB SPA will at least serve the login page).
    2. Anything else (including bare IPs and the production
       ``kb.sxy.homes``) -> KB bundle.
    """
    host = _host_for(request)
    if host in ADMIN_HOSTS:
        if admin.available:
            return admin
        logger.warning(
            "admin SPA requested (host=%s) but admin-web/dist is not built; "
            "falling back to KB SPA",
            host,
        )
    return kb


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_host_static(app: FastAPI, project_root: Path) -> None:
    """Mount the host-based static SPA dispatcher on ``app``.

    Replaces the previous single-SPA ``_register_static`` helper. The
    mount order is significant: we register ``/assets`` (a generic path
    that exists in both SPAs) with a small ASGI app that consults the
    Host header and dispatches to the right ``StaticFiles`` directory.
    SPA fallbacks (``/`` and ``/{full_path:path}``) follow the same
    dispatch.

    When neither dist is built (the typical local dev / CI scenario
    where ``npm run build`` hasn't run), the helper is a no-op --
    matching the historical behaviour of ``_register_static``.
    """
    kb = _resolve_kb_dist(project_root)
    admin = _resolve_admin_dist(project_root)

    if not kb.available and not admin.available:
        logger.info(
            "no SPA dist available (web/dist and admin-web/dist both missing); "
            "skipping static mount (dev mode)"
        )
        return

    if kb.available:
        logger.info("KB SPA dist ready: %s", kb.dist_dir)
    else:
        logger.info("KB SPA dist NOT built: %s", kb.dist_dir)
    if admin.available:
        logger.info("admin SPA dist ready: %s", admin.dist_dir)
    else:
        logger.info("admin SPA dist NOT built: %s", admin.dist_dir)

    _register_asset_mount(app, kb, admin)
    _register_spa_fallback(app, kb, admin)


def _register_asset_mount(
    app: FastAPI, kb: SpaBundle, admin: SpaBundle
) -> None:
    """Mount ``/assets`` to the right dist based on the Host header.

    We can't use ``app.mount`` twice with the same path, so we wrap a
    small ASGI app that inspects ``scope['headers']`` for the Host
    header and dispatches to the right ``StaticFiles`` instance. When a
    host asks for assets from a dist that wasn't built, we return 404
    directly -- the browser will see a 404 for a missing chunk and
    surface it in the console, which is the right signal during a
    half-built deploy.
    """
    kb_app = (
        StaticFiles(directory=str(kb.dist_dir / "assets"))
        if kb.available
        else None
    )
    admin_app = (
        StaticFiles(directory=str(admin.dist_dir / "assets"))
        if admin.available
        else None
    )

    class _AssetDispatcher:
        async def __call__(self, scope, receive, send) -> None:
            if scope["type"] != "http":
                # lifespan / websocket pass-through (we never expect
                # these here, but be safe).
                return
            headers = dict(scope.get("headers") or [])
            host_raw = headers.get(b"host", b"").decode("latin-1")
            host = _host_from_header(host_raw)
            target = admin_app if host in ADMIN_HOSTS else kb_app
            if target is None:
                from starlette.responses import Response

                response = Response("Not Found", status_code=404)
                await response(scope, receive, send)
                return
            await target(scope, receive, send)

    app.mount("/assets", _AssetDispatcher(), name="assets")


def _host_from_header(host_header: str) -> str:
    """Normalise a raw ``Host`` header value to a bare hostname.

    Identical rule to :func:`_host_for` but takes the header string
    directly -- the ASGI ``/assets`` mount runs outside the FastAPI
    request lifecycle, so we don't have a ``Request`` to hand.
    """
    if not host_header:
        return ""
    if host_header.startswith("["):
        end = host_header.find("]")
        if end == -1:
            return host_header
        return host_header[: end + 1]
    if ":" in host_header:
        host_header = host_header.split(":", 1)[0]
    return host_header.lower()


def _register_spa_fallback(
    app: FastAPI, kb: SpaBundle, admin: SpaBundle
) -> None:
    """Register ``/`` and ``/{full_path:path}`` for SPA HTML fallback.

    Non-asset, non-API paths return the chosen dist's ``index.html``
    so client-side routing works.
    """

    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(request: Request, full_path: str = "") -> object:
        if full_path.startswith("api/") or full_path.startswith("docs") \
                or full_path.startswith("openapi.json") \
                or full_path.startswith("redoc"):
            raise HTTPException(status_code=404, detail="Not Found")
        bundle = _pick_bundle(request, kb, admin)
        if not bundle.available:
            raise HTTPException(status_code=404, detail="Not Found")
        index = bundle.dist_dir / "index.html"
        return FileResponse(str(index))


__all__ = [
    "ADMIN_HOSTS",
    "KB_HOSTS",
    "SpaBundle",
    "register_host_static",
]
