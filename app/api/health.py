"""Health-check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import ok

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Lightweight liveness probe used by smoke tests and load balancers."""
    return ok({"status": "ok", "version": "0.1.0"})
