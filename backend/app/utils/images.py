"""Pillow helpers: model-ready encoding, thumbnails and dimension probing."""

import base64
import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps

from app.config import get_settings

MAX_PIXELS = 50_000_000
MODEL_JPEG_QUALITY = 85
THUMBNAIL_JPEG_QUALITY = 80
EXIF_ORIENTATION_TAG = 0x0112
TRANSPOSED_ORIENTATIONS = frozenset({5, 6, 7, 8})
DECODE_ERRORS = (OSError, SyntaxError, ValueError, Image.DecompressionBombError)


class UnreadableImageError(Exception):
    """Raised when a file cannot be decoded as a safe, reasonably sized image."""


def thumbnail_path(image_id: int) -> Path:
    """Return the thumbnail location for an image id."""
    return get_settings().thumbnails_dir / f"{image_id}.jpg"


def _flatten(image: Image.Image) -> Image.Image:
    """Convert any mode to RGB, compositing transparency onto white."""
    if image.mode in ("RGBA", "LA", "P", "PA"):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def open_rgb(path: Path) -> Image.Image:
    """Open an image, apply EXIF orientation and return a detached RGB copy."""
    try:
        with Image.open(path) as source:
            if source.width * source.height > MAX_PIXELS:
                raise UnreadableImageError(f"{path.name} exceeds the {MAX_PIXELS} pixel limit")
            return _flatten(ImageOps.exif_transpose(source))
    except DECODE_ERRORS as exc:
        raise UnreadableImageError(f"Cannot decode {path.name}: {exc}") from exc


def load_for_model(path: Path, max_side: int) -> str:
    """Return a base64 JPEG whose longest side is at most max_side pixels."""
    image = open_rgb(path)
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=MODEL_JPEG_QUALITY)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def make_thumbnail(path: Path, out_path: Path, size: int) -> Path:
    """Write a JPEG thumbnail of at most size x size pixels and return its path."""
    image = open_rgb(path)
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_name(f".{uuid.uuid4().hex}.tmp")
    try:
        image.save(temp_path, format="JPEG", quality=THUMBNAIL_JPEG_QUALITY, optimize=True)
        temp_path.replace(out_path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return out_path


def read_dimensions(path: Path) -> tuple[int, int]:
    """Return (width, height) as displayed, honoring EXIF rotation."""
    try:
        with Image.open(path) as image:
            width, height = image.size
            orientation = image.getexif().get(EXIF_ORIENTATION_TAG)
    except DECODE_ERRORS as exc:
        raise UnreadableImageError(f"Cannot read dimensions of {path.name}: {exc}") from exc
    if orientation in TRANSPOSED_ORIENTATIONS:
        width, height = height, width
    return width, height