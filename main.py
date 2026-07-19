"""FastAPI application entry point.

Wires the process-wide service graph on application startup via the
``lifespan`` handler defined here, registers global exception handlers
that normalise every error into the spec'd ``{code, message}`` envelope,
and mounts the routers exposed under :mod:`app.api`.

Run via::

    source .venv/bin/activate
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api import chat as chat_router
from app.api import chat_history as chat_history_router
from app.api import documents as documents_router
from app.api import health as health_router
from app.api import knowledge_bases as knowledge_bases_router
from app.api import err as api_err
from app.api import ok as api_ok
from app.config import Settings, get_settings
from app.jobs.ingest import recover_interrupted
from app.kb.service import (
    DocumentNotFoundError,
    FileTooLargeError,
    KBNotFoundError,
    UnsupportedFormat,
)
from app.rag.loader import UnsupportedFormat as LoaderUnsupportedFormat

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise / tear down the process-wide service graph.

    Startup order matters: storage must be ready before any chroma / KB
    operations; vectorstore and KBService both reach for the SQLite DB
    during construction (they call ``init()`` defensively, so order is
    not catastrophic, but we keep it explicit for clarity).
    """
    settings: Settings = get_settings()

    # 1. SQLite metadata store (idempotent).
    from app.kb.storage import SQLiteStorage

    storage = SQLiteStorage(settings)
    storage.init()

    # 2. Chat / embedding clients.
    from app.llm.embedding_client import DashScopeEmbeddingClient
    from app.llm.minimax_client import MiniMaxChatClient

    chat_client = MiniMaxChatClient(settings)
    embed_client = DashScopeEmbeddingClient(settings)

    # 3. Chroma wrapper + Embedder + KBService + Retriever.
    from app.rag.embedder import Embedder
    from app.rag.retriever import Retriever
    from app.rag.vectorstore import VectorStore

    # ``VectorStore`` resolves ``storage.chroma_dir`` against
    # ``settings.project_root`` itself, so we feed the full settings
    # object rather than the raw path string.
    vectorstore = VectorStore(settings=settings)
    embedder = Embedder(embed_client)

    from app.kb.service import KBService

    kb_service = KBService(
        storage=storage,
        vectorstore=vectorstore,
        embedder=embedder,
        settings=settings,
    )
    retriever = Retriever(
        embedder=embedder,
        vectorstore=vectorstore,
        chat_client=chat_client,
        settings=settings,
    )

    # 4. Make singletons visible to the routers (``app.deps``).
    app.state.settings = settings
    app.state.storage = storage
    app.state.chat_client = chat_client
    app.state.embed_client = embed_client
    app.state.vectorstore = vectorstore
    app.state.embedder = embedder
    app.state.kb_service = kb_service
    app.state.retriever = retriever

    logger.info(
        "Service graph initialised: project_root=%s", settings.project_root
    )

    # 5. Crash recovery: re-kick any docs that were ``processing`` when
    # the previous process exited.
    recover_interrupted(app)

    try:
        yield
    finally:
        # Tear down the underlying Chroma client if available. The
        # ``PersistentClient`` exposes ``close`` on newer chromadb
        # versions; older ones do not -- tolerate both.
        chroma_client = getattr(vectorstore, "raw_client", None)
        close = getattr(chroma_client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 -- best-effort teardown
                logger.exception("Failed to close Chroma client cleanly")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Build a fully-wired FastAPI app.

    Exposed as a factory function (instead of a module-level singleton)
    so tests can construct an instance pointed at a tmp dir without
    conflicting with module-level state.
    """
    app = FastAPI(
        title="youfu-known",
        description="Personal knowledge-base + RAG service.",
        version="0.1.0",
        lifespan=lifespan,
    )

    _register_exception_handlers(app)
    _register_routers(app)
    _register_root(app)
    _register_static(app)
    return app


def _register_static(app: FastAPI) -> None:
    """挂载前端构建产物 (web/dist) 为静态服务 (根路径 /)"""
    dist_dir = Path(__file__).resolve().parent / "web" / "dist"
    if not (dist_dir / "index.html").is_file():
        return  # dev 模式: 没 build, 跳过
    # 资源路径 /assets/* 走 StaticFiles
    app.mount(
        "/assets",
        StaticFiles(directory=str(dist_dir / "assets")),
        name="assets",
    )

    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str = "") -> object:
        # /api/* 已经由 router 处理; 其它都返回 index.html (SPA 路由)
        if full_path.startswith("api/") or full_path.startswith("docs") \
                or full_path.startswith("openapi.json") \
                or full_path.startswith("redoc"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Not Found")
        index = dist_dir / "index.html"
        from fastapi.responses import FileResponse
        return FileResponse(str(index))


def _register_root(app: FastAPI) -> None:
    """Dev 模式: 根路径返回 JSON 提示。生产模式被 _register_static 覆盖。"""
    # 不再注册 GET / , 改由 _register_static 提供 SPA 文件
    pass


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------


def _register_routers(app: FastAPI) -> None:
    """Mount the per-feature routers.

    Order is irrelevant for routing precedence (paths are unique) but
    we group them by family in the OpenAPI tags for readability.
    """
    app.include_router(health_router.router)
    app.include_router(knowledge_bases_router.router)
    app.include_router(documents_router.router)
    app.include_router(chat_router.router)
    app.include_router(chat_history_router.router)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


def _register_exception_handlers(app: FastAPI) -> None:
    """Map domain exceptions / HTTPExceptions to the unified envelope."""

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # 422 from FastAPI: surface as 400 with a flat message so the
        # spec'd envelope stays simple. ``detail`` keeps the raw errors
        # for debugging.
        return JSONResponse(
            status_code=400,
            content=api_err(
                400,
                "validation error",
                detail=str(exc.errors()),
            ),
        )

    @app.exception_handler(ValueError)
    async def _value_error_handler(
        request: Request, exc: ValueError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=api_err(400, str(exc)),
        )

    @app.exception_handler(KBNotFoundError)
    async def _kb_not_found_handler(
        request: Request, exc: KBNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=api_err(404, str(exc)),
        )

    @app.exception_handler(DocumentNotFoundError)
    async def _doc_not_found_handler(
        request: Request, exc: DocumentNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=api_err(404, str(exc)),
        )

    @app.exception_handler(FileNotFoundError)
    async def _fnf_handler(
        request: Request, exc: FileNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=api_err(404, str(exc)),
        )

    @app.exception_handler(FileTooLargeError)
    async def _too_large_handler(
        request: Request, exc: FileTooLargeError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content=api_err(413, str(exc)),
        )

    @app.exception_handler(UnsupportedFormat)
    async def _unsupported_format_handler(
        request: Request, exc: UnsupportedFormat
    ) -> JSONResponse:
        # Both ``app.kb.service.UnsupportedFormat`` and
        # ``app.rag.loader.UnsupportedFormat`` are caught here; in case
        # the loader-level exception escapes without going through the
        # KB layer, register the second instance explicitly.
        return JSONResponse(
            status_code=400,
            content=api_err(400, str(exc)),
        )

    @app.exception_handler(LoaderUnsupportedFormat)
    async def _loader_unsupported_handler(
        request: Request, exc: LoaderUnsupportedFormat
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=api_err(400, str(exc)),
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=api_err(
                500,
                "internal error",
                detail=str(exc),
            ),
        )


# ---------------------------------------------------------------------------
# Module-level ASGI app (uvicorn `main:app`).
# ---------------------------------------------------------------------------


app = create_app()
