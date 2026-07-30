"""Runtime settings endpoints for administrators."""

from __future__ import annotations

from threading import RLock
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api import ok
from app.auth.deps import require_admin
from app.auth.models import User
from app.admin import get_storage

router = APIRouter(prefix="/api/admin", tags=["admin"])


class SettingsPatch(BaseModel):
    """Allowed non-secret runtime settings."""

    model_config = ConfigDict(extra="forbid")

    model_name: str | None = Field(default=None, min_length=1, max_length=128)
    embedding_batch_size: int | None = Field(default=None, ge=1, le=100)
    chunk_size: int | None = Field(default=None, ge=1, le=100_000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=99_999)
    max_upload_size_mb: int | None = Field(default=None, ge=1, le=10_240)

    @model_validator(mode="after")
    def validate_patch_overlap(self) -> "SettingsPatch":
        if (
            self.chunk_size is not None
            and self.chunk_overlap is not None
            and self.chunk_overlap >= self.chunk_size
        ):
            raise ValueError("chunk_overlap must be less than chunk_size")
        return self


class RuntimeSettings:
    """Thread-safe process-local view of the editable settings."""

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._lock = RLock()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return _settings_payload(self._settings)

    def apply(self, patch: SettingsPatch) -> dict[str, Any]:
        with self._lock:
            values = patch.model_dump(exclude_none=True)
            current_size = int(self._settings.rag.chunk_size)
            current_overlap = int(self._settings.rag.chunk_overlap)
            next_size = int(values.get("chunk_size", current_size))
            next_overlap = int(values.get("chunk_overlap", current_overlap))
            if next_overlap >= next_size:
                raise ValueError("chunk_overlap must be less than chunk_size")

            if "model_name" in values:
                self._settings.chat.model = str(values["model_name"])
            if "embedding_batch_size" in values:
                self._settings.embedding.batch_size = int(
                    values["embedding_batch_size"]
                )
            if "chunk_size" in values:
                self._settings.rag.chunk_size = next_size
            if "chunk_overlap" in values:
                self._settings.rag.chunk_overlap = next_overlap
            if "max_upload_size_mb" in values:
                self._settings.upload.max_file_size_mb = int(
                    values["max_upload_size_mb"]
                )
            return _settings_payload(self._settings)


def _settings_payload(settings: Any) -> dict[str, Any]:
    """Expose only the five supported non-secret fields."""
    return {
        "model_name": str(settings.chat.model),
        "embedding_batch_size": int(settings.embedding.batch_size),
        "chunk_size": int(settings.rag.chunk_size),
        "chunk_overlap": int(settings.rag.chunk_overlap),
        "max_upload_size_mb": int(settings.upload.max_file_size_mb),
    }


def _runtime_for(request: Request) -> RuntimeSettings:
    runtime = getattr(request.app.state, "runtime_settings", None)
    if isinstance(runtime, RuntimeSettings):
        return runtime
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail="settings not initialised")
    runtime = RuntimeSettings(settings)
    request.app.state.runtime_settings = runtime
    return runtime


@router.get("/settings")
async def get_admin_settings(
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    """Return editable settings without credentials or other secrets."""
    del admin
    return ok(_runtime_for(request).snapshot())


@router.patch("/settings")
async def patch_admin_settings(
    body: SettingsPatch,
    request: Request,
    admin: User = Depends(require_admin),
) -> dict:
    """Apply settings in memory; values reset when the process restarts."""
    del admin
    try:
        updated = _runtime_for(request).apply(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(updated)


__all__ = ["router", "RuntimeSettings", "SettingsPatch"]
