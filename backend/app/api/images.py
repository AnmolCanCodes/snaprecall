"""Image metadata, thumbnails and original files."""

import asyncio
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import get_settings
from app.db import connection
from app.schemas import ErrorResponse, ImageDetail
from app.utils.images import UnreadableImageError, make_thumbnail, thumbnail_path

router = APIRouter(
    prefix="/images",
    tags=["images"],
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)

THUMBNAIL_HEADERS = {"Cache-Control": "private, max-age=3600"}


def _fetch_row(image_id: int) -> sqlite3.Row | None:
    with connection() as conn:
        return conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()


async def _get_row(image_id: int) -> sqlite3.Row:
    row = await asyncio.to_thread(_fetch_row, image_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return row


def _safe_path(row: sqlite3.Row) -> Path:
    """Resolve the stored path and make sure it stays inside SCREENSHOT_DIR."""
    root = get_settings().screenshot_dir
    if root is None:
        raise HTTPException(status_code=404, detail="SCREENSHOT_DIR is not configured")
    try:
        resolved = Path(row["path"]).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=404, detail="Image file is missing") from exc
    if not resolved.is_relative_to(root):
        raise HTTPException(status_code=403, detail="File is outside the screenshot directory")
    return resolved


@router.get("/{image_id}", response_model=ImageDetail)
async def get_image(image_id: int) -> ImageDetail:
    """Return metadata for one screenshot."""
    return ImageDetail.from_row(await _get_row(image_id))


@router.get("/{image_id}/thumbnail", response_class=FileResponse)
async def get_thumbnail(image_id: int) -> FileResponse:
    """Serve the thumbnail, generating it on first request if needed."""
    row = await _get_row(image_id)
    thumbnail = thumbnail_path(image_id)
    if not await asyncio.to_thread(thumbnail.exists):
        source = await asyncio.to_thread(_safe_path, row)
        try:
            await asyncio.to_thread(
                make_thumbnail, source, thumbnail, get_settings().thumbnail_size
            )
        except UnreadableImageError as exc:
            raise HTTPException(status_code=404, detail="Thumbnail unavailable") from exc
    return FileResponse(thumbnail, media_type="image/jpeg", headers=THUMBNAIL_HEADERS)


@router.get("/{image_id}/file", response_class=FileResponse)
async def get_file(image_id: int) -> FileResponse:
    """Serve the original file. The path comes from the database, never from the client."""
    row = await _get_row(image_id)
    return FileResponse(await asyncio.to_thread(_safe_path, row))