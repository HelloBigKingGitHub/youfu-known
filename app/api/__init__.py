"""HTTP API layer (FastAPI routers + helpers).

All endpoints return a uniform envelope:

- success: ``{ "code": 0, "data": <payload> }``
- failure: ``{ "code": <int>, "message": <str> }``

The ``ok(data=...)`` helper here builds success envelopes.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi.middleware.cors import CORSMiddleware


ADMIN_CORS_ORIGINS = (
    # Production hostnames. Both share the ``Domain=.sxy.homes``
    # cookie scope set in :mod:`app.api.auth` so a single login works
    # on every ``*.sxy.homes`` subdomain. The admin SPA lives on its
    # own origin (``admin.sxy.homes``, served by nginx :8002) and
    # therefore requires an explicit CORS entry to call ``/api/*``.
    "https://kb.sxy.homes",
    "https://admin.sxy.homes",
    # Dev Vite origins.
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    # Admin SPA dev Vite (port 5174 -- mirrors ``admin-web/vite.config.ts``).
    "http://localhost:5174",
    "http://127.0.0.1:5174",
)


# Legacy admin hosts we migrated off. Both were intermediate names
# during the rename sequence:
#   admin.kb.sxy.homes (three-segment) -> admin-kb.sxy.homes -> admin.sxy.homes
# Browsers will no longer carry the cross-subdomain cookie for these
# (we deleted them from the production DNS), so any incoming CORS /
# cookie-attach from them is either stale config or an active exploit
# attempt. The CSRF middleware rejects with 403 and logs so deploy
# drift is obvious in the access log.
LEGACY_ADMIN_ORIGINS = frozenset(
    {
        "https://admin.kb.sxy.homes",
        "https://admin-kb.sxy.homes",
    }
)


def add_cors(app: Any) -> None:
    """Install the explicit-origin CORS policy used by both SPAs."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(ADMIN_CORS_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# Backwards-compatible name used by existing application wiring.
configure_cors = add_cors


def ok(data: Any = None) -> Dict[str, Any]:
    """Build a success envelope ``{"code": 0, "data": data}``.

    Passing ``None`` is allowed (the JSON will then read ``"data": null``);
    callers that want to omit ``data`` entirely should pass an empty dict.
    """
    return {"code": 0, "data": data}


def err(code: int, message: str, *, detail: Optional[str] = None) -> Dict[str, Any]:
    """Build an error envelope ``{"code": <int>, "message": <str>, ...}``.

    ``detail`` is only attached for 5xx responses so the spec'd
    ``{code:500, message:"internal error", detail:str}`` payload works.
    """
    body: Dict[str, Any] = {"code": int(code), "message": str(message)}
    if detail is not None:
        body["detail"] = str(detail)
    return body


__all__ = ["ok", "err"]
