"""Cloudflare Turnstile verification."""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# Cloudflare's official test secrets.
TURNSTILE_TEST_SECRET = "1x0000000000000000000000000000000AA"
TURNSTILE_TEST_SECRET_ALWAYS_BLOCKS = "2x00000000000000000000AB"


async def verify_turnstile(token: str, remote_ip: Optional[str] = None) -> bool:
    """Verify a Turnstile token, skipping verification only in dev mode."""
    secret = os.getenv("YOUFU_TURNSTILE_SECRET", "").strip()

    if not secret:
        logger.warning(
            "YOUFU_TURNSTILE_SECRET not set — skipping Turnstile verification "
            "(dev mode)"
        )
        return True

    payload = {
        "secret": secret,
        "response": token,
        **({"remoteip": remote_ip} if remote_ip else {}),
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(TURNSTILE_VERIFY_URL, data=payload)
            response.raise_for_status()
            result = response.json()
            success = bool(result.get("success", False))
            if not success:
                logger.warning(
                    "Turnstile verification failed: %s",
                    result.get("error-codes", []),
                )
            return success
    except Exception as exc:  # noqa: BLE001 - fail closed on verification errors
        logger.error("Turnstile verification error: %s", exc)
        return False


__all__ = [
    "TURNSTILE_TEST_SECRET",
    "TURNSTILE_TEST_SECRET_ALWAYS_BLOCKS",
    "TURNSTILE_VERIFY_URL",
    "verify_turnstile",
]
