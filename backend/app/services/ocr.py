"""Tesseract OCR that degrades to empty text instead of failing the pipeline."""

import logging
import re
from functools import lru_cache
from pathlib import Path

import pytesseract
from pytesseract import TesseractError, TesseractNotFoundError

from app.config import get_settings
from app.utils.images import open_rgb

logger = logging.getLogger(__name__)

MAX_OCR_CHARS = 20_000
OCR_TIMEOUT_SECONDS = 90
_WHITESPACE = re.compile(r"\s+")


def _configure_binary() -> None:
    """Point pytesseract at TESSERACT_CMD when it is set."""
    command = get_settings().tesseract_cmd
    if command:
        pytesseract.pytesseract.tesseract_cmd = command


def check_tesseract() -> tuple[bool, str]:
    """Report whether the tesseract binary and every configured language pack are usable."""
    settings = get_settings()
    _configure_binary()
    try:
        installed = set(pytesseract.get_languages(config=""))
    except TesseractNotFoundError:
        return False, "Tesseract binary not found. Install it or set TESSERACT_CMD in .env"
    except (TesseractError, RuntimeError) as exc:
        return False, f"Tesseract could not list languages: {exc}"
    missing = [lang for lang in settings.ocr_langs.split("+") if lang and lang not in installed]
    if missing:
        return False, f"Missing Tesseract language pack(s): {', '.join(missing)}"
    return True, f"Tesseract ready ({settings.ocr_langs})"


@lru_cache
def _availability() -> bool:
    """Check Tesseract once per process and log a single warning when it is unusable."""
    available, detail = check_tesseract()
    if not available:
        logger.warning("OCR is disabled for this run: %s", detail)
    return available


def _normalize(text: str) -> str:
    """Collapse whitespace and cap the length."""
    return _WHITESPACE.sub(" ", text).strip()[:MAX_OCR_CHARS]


def extract_text(path: Path) -> str:
    """Run OCR on an image file and return normalized text, or an empty string."""
    settings = get_settings()
    if settings.ocr_engine == "none" or not _availability():
        return ""
    image = open_rgb(path)
    try:
        raw = pytesseract.image_to_string(
            image, lang=settings.ocr_langs, timeout=OCR_TIMEOUT_SECONDS
        )
    except (TesseractError, TesseractNotFoundError, RuntimeError) as exc:
        logger.warning("OCR failed for %s: %s", path.name, exc)
        return ""
    return _normalize(raw)