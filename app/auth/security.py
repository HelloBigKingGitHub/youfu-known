"""Password hashing + JWT helpers.

Two pieces of crypto live here:

- :func:`hash_password` / :func:`verify_password` use ``bcrypt``
  directly (instead of via ``passlib``) because passlib 1.7.4 has a
  known incompatibility with bcrypt >= 4.1 -- it probes the backend
  version via ``_bcrypt.__about__``, which was removed in bcrypt 4.1+.
  Going through ``bcrypt`` keeps the cost factor configuration in one
  place and avoids the dependency on passlib's brittle version probe.
- :func:`create_access_token` / :func:`create_refresh_token` /
  :func:`decode_token` wrap ``PyJWT``. We sign HS256 with the secret
  pulled from :class:`app.config.AuthConfig.jwt_secret`. The ``typ``
  claim disambiguates access vs refresh so a refresh token cannot be
  presented at an access-token endpoint.

Secret stability and token lifetime
-----------------------------------

The HS256 signing secret is the only thing standing between an
attacker and forged tokens, so it MUST be stable across restarts in
any non-throwaway deployment. When ``YOUFU_JWT_SECRET`` is unset,
:mod:`app.config` falls back to a per-process random secret; every
restart rotates it, which **invalidates every outstanding access and
refresh token** and forces every logged-in user to log in again. A
loud multi-line WARNING is logged at boot whenever that fallback
fires, but the right fix is to set ``YOUFU_JWT_SECRET`` in ``.env``
(a long random string) and keep it stable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Literal, Union

import bcrypt
import jwt

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


# bcrypt has a hard 72-byte input cap; truncate explicitly so a 200-char
# password doesn't blow up with a confusing ``ValueError`` from the C ext.
_BCRYPT_MAX_BYTES = 72


def _truncate(plain: str) -> bytes:
    encoded = plain.encode("utf-8")
    return encoded[:_BCRYPT_MAX_BYTES]


def hash_password(plain: str, *, rounds: int = 12) -> str:
    """Return a bcrypt hash of ``plain`` using ``rounds`` cost."""
    if not plain:
        raise ValueError("password must be non-empty")
    salt = bcrypt.gensalt(rounds=int(rounds))
    return bcrypt.hashpw(_truncate(plain), salt).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time bcrypt comparison. Returns False on malformed hashes."""
    if not plain or not hashed:
        return False
    try:
        return bool(bcrypt.checkpw(_truncate(plain), hashed.encode("ascii")))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


TokenKind = Literal["access", "refresh"]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    user_id: str,
    role: str,
    *,
    secret: str,
    expires_in: Union[int, timedelta] = 24 * 3600,
) -> str:
    """Mint an HS256 access token for ``user_id`` / ``role``.

    ``expires_in`` is interpreted as seconds when ``int`` and as a
    delta when ``timedelta``.
    """
    delta = (
        timedelta(seconds=int(expires_in))
        if isinstance(expires_in, int)
        else expires_in
    )
    now = _now_utc()
    payload: Dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + delta).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def create_refresh_token(
    user_id: str,
    *,
    secret: str,
    expires_in: Union[int, timedelta] = 30 * 24 * 3600,
) -> str:
    """Mint an HS256 refresh token (30 days by default)."""
    delta = (
        timedelta(seconds=int(expires_in))
        if isinstance(expires_in, int)
        else expires_in
    )
    now = _now_utc()
    payload: Dict[str, Any] = {
        "sub": user_id,
        "typ": "refresh",
        "iat": int(now.timestamp()),
        "exp": int((now + delta).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


class TokenError(Exception):
    """Raised when a JWT fails verification (bad sig, expired, wrong kind)."""


def decode_token(
    token: str,
    *,
    secret: str,
    expected_kind: TokenKind = "access",
) -> Dict[str, Any]:
    """Verify signature + ``typ`` + ``exp`` and return the payload dict.

    Raises :class:`TokenError` for any failure. Callers should catch it
    and translate to an HTTP 401.
    """
    if not token:
        raise TokenError("missing token")
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError(f"invalid token: {exc}") from exc

    typ = payload.get("typ")
    if typ != expected_kind:
        raise TokenError(f"wrong token kind: expected {expected_kind}, got {typ}")
    if not payload.get("sub"):
        raise TokenError("token missing subject")
    return payload


__all__ = [
    "TokenError",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "hash_password",
    "verify_password",
]
