"""GET /api/health."""

import asyncio
import os
import sqlite3

from fastapi import APIRouter, Request

from app.config import get_settings
from app.db import VectorExtensionError, connection, get_embedding_mismatch
from app.schemas import ComponentCheck, HealthResponse
from app.services.llm_client import (
    ProviderResponseError,
    ProviderUnavailableError,
    get_daily_tracker,
    get_llm_client,
)
from app.services.ocr import check_tesseract

router = APIRouter(tags=["health"])


def _check_database() -> ComponentCheck:
    mismatch = get_embedding_mismatch()
    if mismatch:
        return ComponentCheck(ok=False, detail=mismatch)
    try:
        with connection() as conn:
            conn.execute("SELECT 1").fetchone()
    except (sqlite3.Error, VectorExtensionError, OSError) as exc:
        return ComponentCheck(ok=False, detail=str(exc))
    return ComponentCheck(ok=True)


def _check_tesseract() -> ComponentCheck:
    if get_settings().ocr_engine == "none":
        return ComponentCheck(ok=True, detail="OCR disabled (OCR_ENGINE=none)")
    available, detail = check_tesseract()
    return ComponentCheck(ok=available, detail=detail)


def _check_screenshot_dir() -> ComponentCheck:
    root = get_settings().screenshot_dir
    if root is None:
        return ComponentCheck(ok=False, detail="SCREENSHOT_DIR is not set in .env")
    if not root.is_dir():
        return ComponentCheck(ok=False, detail=f"{root} does not exist or is not a folder")
    if not os.access(root, os.R_OK):
        return ComponentCheck(ok=False, detail=f"{root} is not readable")
    return ComponentCheck(ok=True, detail=str(root))


def _ollama_model_check(configured: str, pulled: list[str]) -> ComponentCheck:
    wanted = configured if ":" in configured else f"{configured}:latest"
    if wanted.lower() in pulled:
        return ComponentCheck(ok=True, detail=configured)
    return ComponentCheck(ok=False, detail=f"Model not pulled. Run: ollama pull {configured}")


def _gemini_model_check(configured: str, available_models: list[str]) -> ComponentCheck:
    wanted = configured.lower().removeprefix("models/")
    match = any(
        wanted == item or wanted == item.removeprefix("models/")
        for item in available_models
    )
    if match:
        return ComponentCheck(ok=True, detail=configured)
    return ComponentCheck(ok=True, detail=f"{configured} (unverified in list)")


async def _check_provider() -> tuple[ComponentCheck, ComponentCheck, ComponentCheck, bool]:
    settings = get_settings()
    provider = settings.llm_provider

    if provider == "gemini":
        key_configured = bool(settings.gemini_api_key and settings.gemini_api_key.strip())
        if not key_configured:
            return (
                ComponentCheck(ok=False, detail="GEMINI_API_KEY is not set in .env"),
                ComponentCheck(ok=False, detail="API key missing"),
                ComponentCheck(ok=False, detail="API key missing"),
                False,
            )
        try:
            client = get_llm_client()
            models = [m.lower() for m in await client.list_models()]
            return (
                ComponentCheck(ok=True, detail=settings.gemini_base_url),
                _gemini_model_check(settings.vision_model, models),
                _gemini_model_check(settings.embedding_model, models),
                True,
            )
        except ProviderUnavailableError as exc:
            return (
                ComponentCheck(ok=False, detail=str(exc)),
                ComponentCheck(ok=False, detail="Gemini is not reachable"),
                ComponentCheck(ok=False, detail="Gemini is not reachable"),
                True,
            )
        except ProviderResponseError as exc:
            return (
                ComponentCheck(ok=False, detail=str(exc)),
                ComponentCheck(
                    ok=True, detail=f"{settings.vision_model} (tolerated list failure)"
                ),
                ComponentCheck(
                    ok=True, detail=f"{settings.embedding_model} (tolerated list failure)"
                ),
                True,
            )

    # Provider is ollama
    try:
        client = get_llm_client()
        pulled = [name.lower() for name in await client.list_models()]
        return (
            ComponentCheck(ok=True, detail=settings.ollama_base_url),
            _ollama_model_check(settings.vision_model, pulled),
            _ollama_model_check(settings.embedding_model, pulled),
            True,
        )
    except (ProviderUnavailableError, ProviderResponseError) as exc:
        down = ComponentCheck(ok=False, detail=str(exc))
        skipped = ComponentCheck(ok=False, detail="Ollama is not reachable")
        return down, skipped, skipped, True


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Report the state of the database, provider, models, OCR and the screenshot folder."""
    settings = get_settings()
    database, (provider_check, vision, embedding, key_configured), tesseract, screenshots = (
        await asyncio.gather(
            asyncio.to_thread(_check_database),
            _check_provider(),
            asyncio.to_thread(_check_tesseract),
            asyncio.to_thread(_check_screenshot_dir),
        )
    )

    mismatch = get_embedding_mismatch() is not None
    checks = (database, provider_check, vision, embedding, tesseract, screenshots)
    is_ok = all(check.ok for check in checks) and not mismatch

    worker = getattr(request.app.state, "worker", None)
    paused_reason: str | None = None
    if worker is not None:
        if not worker._running.is_set():
            paused_reason = worker._paused_reason or "user"

    return HealthResponse(
        status="ok" if is_ok else "degraded",
        provider_name=settings.llm_provider,
        key_configured=key_configured,
        database=database,
        provider=provider_check,
        vision_model=vision,
        embedding_model=embedding,
        tesseract=tesseract,
        screenshot_dir=screenshots,
        requests_today=get_daily_tracker().requests_today,
        paused_reason=paused_reason,
        embedding_mismatch=mismatch,
    )