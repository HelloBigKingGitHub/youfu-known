"""Configuration loader.

Reads ``config.yaml`` (committed) for structural config and ``.env``
(optional) for credentials. Credentials in ``.env`` override
``config.yaml``.

Resolution rules:
- chat.api_key              <- MINIMAX_API_KEY
- embedding.api_key         <- DASHSCOPE_API_KEY
- auth.jwt_secret           <- YOUFU_JWT_SECRET
- auth.admin_username       <- YOUFU_ADMIN_USERNAME
- auth.admin_password       <- YOUFU_ADMIN_PASSWORD
- auth.cookie_secure        <- YOUFU_COOKIE_SECURE
- auth.session_hours        <- YOUFU_SESSION_HOURS
- auth.refresh_days         <- YOUFU_REFRESH_DAYS
- auth.bcrypt_rounds        <- YOUFU_BCRYPT_ROUNDS

``get_settings()`` returns a process-wide singleton ``Settings`` instance.
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class ChatConfig(BaseModel):
    base_url: str = "https://api.MiniMax.chat/v1"
    api_key: str = "REPLACE_ME"     # 单 key 兼容字段 (从 MINIMAX_API_KEY 读)
    api_keys: List[str] = Field(default_factory=list)  # 多 key 列表 (按顺序轮询)
    model: str = "MiniMax-Text-01"
    timeout: int = 60


class EmbeddingConfig(BaseModel):
    provider: str = "dashscope"
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key: str = "REPLACE_ME"
    model: str = "text-embedding-v3"
    dim: int = 1024
    batch_size: int = 25
    timeout: int = 30


class StorageConfig(BaseModel):
    upload_dir: str = "./storage/uploads"
    chroma_dir: str = "./storage/chroma"
    meta_db: str = "./storage/knowledge_base.sqlite3"


class RagConfig(BaseModel):
    chunk_size: int = 600
    chunk_overlap: int = 80
    separators: List[str] = Field(
        default_factory=lambda: ["\n\n", "\n", "。", "!", "?", "！", "?", " ", ""]
    )
    top_k: int = 6
    score_threshold: float = 0.0
    system_prompt: str = (
        "你是用户的个人知识库助手。请严格基于下方【参考资料】回答问题。\n"
        "要求:\n"
        "1. 只用参考资料中的事实,不要编造。\n"
        "2. 若资料不足以回答,直接说\"知识库中没有相关信息\"。\n"
        "3. 回答末尾用 [n] 标注引用的资料编号 (n 从 1 开始)。\n"
        "4. 回答用中文,简洁准确。"
    )
    max_context_chars: int = 8000


class UploadConfig(BaseModel):
    max_file_size_mb: int = 50
    allowed_extensions: List[str] = Field(
        default_factory=lambda: [".pdf", ".docx", ".doc", ".md", ".txt", ".html", ".htm"]
    )


class AuthConfig(BaseModel):
    """Authentication / session configuration.

    Sensitive values default to ``None`` so ``Settings`` validation
    passes even when ``.env`` hasn't been populated yet. ``load_settings``
    fills ``jwt_secret`` with an ephemeral random value (with a loud
    warning at boot if it was not explicitly provided via env), and the
    lifespan logs again if the admin username / password are missing.
    """

    jwt_secret: Optional[str] = None
    admin_username: Optional[str] = "admin"
    admin_password: Optional[str] = None
    cookie_secure: bool = True
    session_hours: int = 24
    refresh_days: int = 30
    bcrypt_rounds: int = 12


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


class Settings(BaseModel):
    """Aggregated application settings."""

    project_root: Path
    server: ServerConfig = Field(default_factory=ServerConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    rag: RagConfig = Field(default_factory=RagConfig)
    upload: UploadConfig = Field(default_factory=UploadConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)

    # ------------------------------------------------------------------
    # Convenience accessors (always absolute paths)
    # ------------------------------------------------------------------

    def upload_dir_abs(self) -> Path:
        p = Path(self.storage.upload_dir)
        if not p.is_absolute():
            p = self.project_root / p
        return p.resolve()

    def chroma_dir_abs(self) -> Path:
        p = Path(self.storage.chroma_dir)
        if not p.is_absolute():
            p = self.project_root / p
        return p.resolve()

    def meta_db_abs(self) -> Path:
        p = Path(self.storage.meta_db)
        if not p.is_absolute():
            p = self.project_root / p
        return p.resolve()


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _resolve_project_root() -> Path:
    """Locate the project root.

    Priority:
    1. ``YOUFU_KNOWN_ROOT`` env var (if set).
    2. Walk up from CWD until we find ``config.yaml``.
    3. Fall back to CWD.
    """
    env_root = os.getenv("YOUFU_KNOWN_ROOT")
    if env_root:
        return Path(env_root).resolve()

    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "config.yaml").is_file():
            return candidate
    return cwd


def load_settings(
    config_path: Optional[os.PathLike] = None,
    dotenv_path: Optional[os.PathLike] = None,
) -> Settings:
    """Load ``Settings`` from ``config.yaml`` + ``.env``.

    Parameters
    ----------
    config_path:
        Path to the YAML config. Defaults to ``<project_root>/config.yaml``.
    dotenv_path:
        Path to the dotenv file. Defaults to ``<project_root>/.env``
        (silent if missing).
    """
    project_root = _resolve_project_root()

    cfg_path = Path(config_path) if config_path else project_root / "config.yaml"
    if not cfg_path.is_file():
        raise FileNotFoundError(f"config.yaml not found at {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # .env is optional -- load it best-effort
    env_path = Path(dotenv_path) if dotenv_path else project_root / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)

    # Apply credential overrides (MINIMAX_API_KEY + MINIMAX_API_KEY_2/3/...)
    raw_chat = dict(raw.get("chat") or {})

    # 收集所有 key: 主 key + _2, _3, ... 后缀
    chat_keys: List[str] = []
    main_key = os.getenv("MINIMAX_API_KEY")
    if main_key:
        chat_keys.append(main_key)
    # 扫 _2, _3, ...
    for suffix in (2, 3, 4, 5, 6, 7, 8, 9, 10):
        extra = os.getenv(f"MINIMAX_API_KEY_{suffix}")
        if extra:
            chat_keys.append(extra)
    if chat_keys:
        raw_chat["api_keys"] = chat_keys
        raw_chat["api_key"] = chat_keys[0]  # 单 key 兼容字段
    raw["chat"] = raw_chat

    raw_emb = dict(raw.get("embedding") or {})
    if (env_val := os.getenv("DASHSCOPE_API_KEY")):
        raw_emb["api_key"] = env_val
    raw["embedding"] = raw_emb

    # Auth env overrides (JWT secret, admin bootstrap, cookie flags).
    raw_auth = dict(raw.get("auth") or {})
    if (env_val := os.getenv("YOUFU_JWT_SECRET")):
        raw_auth["jwt_secret"] = env_val
    elif not raw_auth.get("jwt_secret"):
        # Stable per-installation dev fallback so first-run / tests work
        # without an .env entry. Production deployments MUST override via
        # YOUFU_JWT_SECRET (a warning is logged at startup).
        raw_auth["jwt_secret"] = secrets.token_hex(32)
    if (env_val := os.getenv("YOUFU_ADMIN_USERNAME")):
        raw_auth["admin_username"] = env_val
    if (env_val := os.getenv("YOUFU_ADMIN_PASSWORD")):
        raw_auth["admin_password"] = env_val
    if (env_val := os.getenv("YOUFU_COOKIE_SECURE")):
        raw_auth["cookie_secure"] = env_val.lower() not in {"0", "false", "no"}
    if (env_val := os.getenv("YOUFU_SESSION_HOURS")):
        try:
            raw_auth["session_hours"] = int(env_val)
        except ValueError:
            pass
    if (env_val := os.getenv("YOUFU_REFRESH_DAYS")):
        try:
            raw_auth["refresh_days"] = int(env_val)
        except ValueError:
            pass
    if (env_val := os.getenv("YOUFU_BCRYPT_ROUNDS")):
        try:
            raw_auth["bcrypt_rounds"] = int(env_val)
        except ValueError:
            pass
    raw["auth"] = raw_auth

    return Settings(project_root=project_root, **raw)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return load_settings()


def reset_settings_cache() -> None:
    """Clear the LRU cache (useful in tests)."""
    get_settings.cache_clear()