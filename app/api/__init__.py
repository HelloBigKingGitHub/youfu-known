"""HTTP API layer (FastAPI routers + helpers).

All endpoints return a uniform envelope:

- success: ``{ "code": 0, "data": <payload> }``
- failure: ``{ "code": <int>, "message": <str> }``

The ``ok(data=...)`` helper here builds success envelopes.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


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
