"""Indexing pipeline for a single screenshot."""

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app.config import get_settings
from app.db import connection, copy_vector, transaction, upsert_vector
from app.services.embeddings import DocumentRecord, build_document_text, embed_document
from app.services.llm_client import (
    ProviderUnavailableError,
    QuotaExhaustedError,
    RateLimitError,
)
from app.services.ocr import extract_text
from app.services.vision import analyze_image
from app.utils.hashing import sha256_file
from app.utils.images import (
    UnreadableImageError,
    load_for_model,
    make_thumbnail,
    read_dimensions,
    thumbnail_path,
)

logger = logging.getLogger(__name__)

NOW_SQL = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
MAX_ERROR_CHARS = 500

_last_retry_after: float | None = None


def get_last_retry_after() -> float | None:
    """Return and clear the most recently encountered RateLimitError retry-after value."""
    global _last_retry_after
    val = _last_retry_after
    _last_retry_after = None
    return val


class Outcome(StrEnum):
    """Result of processing one image, used by the worker to decide what to do next."""

    DONE = "done"
    MISSING = "missing"
    ERROR = "error"
    PROVIDER_DOWN = "provider_down"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    OLLAMA_DOWN = "provider_down"


@dataclass(frozen=True)
class FileInfo:
    """Facts read from the file on disk."""

    sha256: str
    width: int
    height: int


def _load_row(image_id: int) -> sqlite3.Row | None:
    with connection() as conn:
        return conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()


def _delete_row(image_id: int) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
    thumbnail_path(image_id).unlink(missing_ok=True)


def _inspect_file(path: Path) -> FileInfo:
    width, height = read_dimensions(path)
    return FileInfo(sha256=sha256_file(path), width=width, height=height)


def _find_duplicate(sha256: str, image_id: int) -> sqlite3.Row | None:
    with connection() as conn:
        return conn.execute(
            "SELECT * FROM images WHERE sha256 = ? AND status = 'done' AND id != ? LIMIT 1",
            (sha256, image_id),
        ).fetchone()


def _try_thumbnail(image_id: int, path: Path) -> None:
    """Create the thumbnail eagerly; a failure is not fatal because the API retries lazily."""
    try:
        make_thumbnail(path, thumbnail_path(image_id), get_settings().thumbnail_size)
    except (UnreadableImageError, OSError) as exc:
        logger.warning("Thumbnail skipped for %s: %s", path.name, exc)


def _apply_duplicate(image_id: int, path: Path, info: FileInfo, source: sqlite3.Row) -> bool:
    """Copy metadata and vector from an identical, already indexed file."""
    with connection() as conn, transaction(conn):
        if not copy_vector(conn, source["id"], image_id):
            return False
        conn.execute(
            f"""UPDATE images SET sha256 = ?, width = ?, height = ?, summary = ?, tags = ?,
                app_type = ?, ocr_text = ?, visible_text = ?, status = 'done', error = NULL,
                indexed_at = {NOW_SQL} WHERE id = ?""",
            (
                info.sha256,
                info.width,
                info.height,
                source["summary"],
                source["tags"],
                source["app_type"],
                source["ocr_text"],
                source["visible_text"],
                image_id,
            ),
        )
    _try_thumbnail(image_id, path)
    return True


def _write_result(
    image_id: int, path: Path, info: FileInfo, record: DocumentRecord, vector: list[float]
) -> None:
    """Persist every indexed field and the vector atomically (FTS follows via triggers)."""
    _try_thumbnail(image_id, path)
    with connection() as conn, transaction(conn):
        conn.execute(
            f"""UPDATE images SET sha256 = ?, width = ?, height = ?, summary = ?, tags = ?,
                app_type = ?, ocr_text = ?, visible_text = ?, status = 'done', error = NULL,
                indexed_at = {NOW_SQL} WHERE id = ?""",
            (
                info.sha256,
                info.width,
                info.height,
                record.summary,
                json.dumps(record.tags, ensure_ascii=False),
                record.app_type,
                record.ocr_text,
                record.visible_text,
                image_id,
            ),
        )
        upsert_vector(conn, image_id, vector)


def _release(image_id: int) -> None:
    """Return an image to pending without counting an attempt (transient outage)."""
    with connection() as conn:
        conn.execute("UPDATE images SET status = 'pending' WHERE id = ?", (image_id,))


def _record_failure(image_id: int, message: str) -> None:
    """Count a failed attempt and mark the image failed once retries are exhausted."""
    with connection() as conn:
        conn.execute(
            """UPDATE images SET attempts = attempts + 1, error = ?,
               status = CASE WHEN attempts + 1 >= ? THEN 'failed' ELSE 'pending' END
               WHERE id = ?""",
            (message[:MAX_ERROR_CHARS], get_settings().worker_max_retries, image_id),
        )


async def _index(image_id: int, path: Path) -> Outcome:
    """Run the full indexing flow for one image."""
    settings = get_settings()
    if not await asyncio.to_thread(path.exists):
        await asyncio.to_thread(_delete_row, image_id)
        return Outcome.MISSING

    info = await asyncio.to_thread(_inspect_file, path)
    duplicate = await asyncio.to_thread(_find_duplicate, info.sha256, image_id)
    if duplicate is not None and await asyncio.to_thread(
        _apply_duplicate, image_id, path, info, duplicate
    ):
        logger.info("Deduplicated %s by checksum", path.name)
        return Outcome.DONE

    image_b64 = await asyncio.to_thread(load_for_model, path, settings.max_image_side)
    vision, ocr_text = await asyncio.gather(
        analyze_image(image_b64), asyncio.to_thread(extract_text, path)
    )
    record = DocumentRecord(
        summary=vision.summary,
        tags=vision.tags,
        app_type=vision.app_type,
        visible_text=vision.visible_text,
        ocr_text=ocr_text,
    )
    vector = await embed_document(build_document_text(record))
    await asyncio.to_thread(_write_result, image_id, path, info, record, vector)
    logger.info("Indexed %s", path.name)
    return Outcome.DONE


async def process_image(image_id: int) -> Outcome:
    """Index one image and translate failures into retry state in the database."""
    global _last_retry_after
    row = await asyncio.to_thread(_load_row, image_id)
    if row is None:
        return Outcome.MISSING
    path = Path(row["path"])
    try:
        return await _index(image_id, path)
    except RateLimitError as exc:
        logger.warning("Rate limit hit while indexing %s: %s", path.name, exc)
        _last_retry_after = exc.retry_after_seconds
        await asyncio.to_thread(_release, image_id)
        return Outcome.RATE_LIMITED
    except QuotaExhaustedError as exc:
        logger.warning("Quota exhausted while indexing %s: %s", path.name, exc)
        await asyncio.to_thread(_release, image_id)
        return Outcome.QUOTA_EXHAUSTED
    except ProviderUnavailableError as exc:
        logger.warning("Provider unavailable while indexing %s: %s", path.name, exc)
        await asyncio.to_thread(_release, image_id)
        return Outcome.PROVIDER_DOWN
    except Exception as exc:
        logger.exception("Indexing failed for %s", path.name)
        await asyncio.to_thread(_record_failure, image_id, f"{type(exc).__name__}: {exc}")
        return Outcome.ERROR