"""FastAPI application and lifespan wiring."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import api_router
from app.config import get_settings
from app.db import init_db
from app.services.llm_client import close_llm_client
from app.services.watcher import FolderWatcher, scan_folder
from app.services.worker import IndexWorker
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)


async def _initial_scan(worker: IndexWorker) -> None:
    """Backfill existing screenshots without blocking startup."""
    try:
        await asyncio.to_thread(scan_folder)
    except Exception:
        logger.exception("Initial scan failed")
        return
    worker.notify()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the worker, watcher and backfill on startup and stop them cleanly."""
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.thumbnails_dir.mkdir(parents=True, exist_ok=True)
    init_db()

    worker = IndexWorker()
    app.state.worker = worker
    worker.start()

    watcher: FolderWatcher | None = None
    if settings.watch_enabled:
        watcher = FolderWatcher(asyncio.get_running_loop(), worker.notify)
        watcher.start()

    backfill: asyncio.Task[None] | None = None
    if settings.backfill_on_start:
        backfill = asyncio.create_task(_initial_scan(worker), name="initial-scan")
    worker.notify()

    try:
        yield
    finally:
        if backfill is not None:
            backfill.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await backfill
        if watcher is not None:
            watcher.stop()
        await worker.stop()
        await close_llm_client()


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        {"detail": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers
    )


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    messages = [
        f"{'.'.join(str(part) for part in error['loc'][1:])}: {error['msg']}"
        for error in exc.errors()
    ]
    return JSONResponse({"detail": "; ".join(messages)}, status_code=422)


async def _unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error", exc_info=exc)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    settings = get_settings()
    app = FastAPI(title="SnapRecall", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
    app.include_router(api_router)
    return app


app = create_app()

if __name__ == "__main__":
    runtime = get_settings()
    uvicorn.run("app.main:app", host=runtime.api_host, port=runtime.api_port)