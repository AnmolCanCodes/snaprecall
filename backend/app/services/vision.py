"""Gemma vision analysis with defensive JSON parsing."""

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import get_settings
from app.services.llm_client import ProviderResponseError, get_llm_client

logger = logging.getLogger(__name__)

APP_TYPES = (
    "chat",
    "payment",
    "code",
    "error",
    "document",
    "social",
    "shopping",
    "map",
    "ticket",
    "email",
    "settings",
    "web",
    "other",
)
MAX_TAGS = 8
MAX_TAG_CHARS = 30
MAX_SUMMARY_CHARS = 400
MAX_VISIBLE_TEXT_CHARS = 1500

_FENCE = re.compile(r"```(?:json)?", re.IGNORECASE)


def build_vision_prompt(ocr_engine: str) -> str:
    """Build the user prompt instructing the model to return JSON with visible text."""
    if ocr_engine == "none":
        text_instruction = (
            f"put all readable text you can see in visible_text up to {MAX_VISIBLE_TEXT_CHARS} "
            "characters. Hindi and Hinglish text must be preserved verbatim, exactly as shown."
        )
    else:
        text_instruction = (
            f"the most important text visible, at most {MAX_VISIBLE_TEXT_CHARS} characters."
        )

    return (
        "You analyze a screenshot so that it can be found later with a search box. "
        "The screenshot may contain English, Hindi (Devanagari) or Hinglish text. "
        "Preserve names, amounts, numbers and error messages verbatim, exactly as shown. "
        "Reply with a single JSON object and nothing else, using exactly these keys:\n"
        '- "summary": at most 2 sentences describing what the screenshot shows.\n'
        '- "tags": 3 to 8 short lowercase tags.\n'
        f'- "app_type": one of {", ".join(APP_TYPES)}.\n'
        f'- "visible_text": {text_instruction}'
    )


def _clean_text(value: object, limit: int) -> str:
    """Return a whitespace normalized string capped at limit characters."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


class VisionResult(BaseModel):
    """Validated model output with safe fallbacks for missing fields."""

    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    app_type: str = "other"
    visible_text: str = ""

    @field_validator("summary", mode="before")
    @classmethod
    def _summary(cls, value: object) -> str:
        return _clean_text(value, MAX_SUMMARY_CHARS)

    @field_validator("visible_text", mode="before")
    @classmethod
    def _visible_text(cls, value: object) -> str:
        return _clean_text(value, MAX_VISIBLE_TEXT_CHARS)

    @field_validator("app_type", mode="before")
    @classmethod
    def _app_type(cls, value: object) -> str:
        candidate = value.strip().lower() if isinstance(value, str) else ""
        return candidate if candidate in APP_TYPES else "other"

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, value: object) -> list[str]:
        if isinstance(value, str):
            items: list[object] = list(value.split(","))
        elif isinstance(value, list):
            items = value
        else:
            return []
        tags: list[str] = []
        for item in items:
            if not isinstance(item, str):
                continue
            tag = " ".join(item.strip().lstrip("#").lower().split())[:MAX_TAG_CHARS]
            if tag and tag not in tags:
                tags.append(tag)
        return tags[:MAX_TAGS]


def _extract_object(text: str) -> dict[str, Any]:
    """Find the first decodable JSON object in free-form model output."""
    cleaned = _FENCE.sub("", text)
    decoder = json.JSONDecoder()
    start = cleaned.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(cleaned, start)
        except json.JSONDecodeError:
            start = cleaned.find("{", start + 1)
            continue
        if isinstance(value, dict):
            return value
        start = cleaned.find("{", start + 1)
    raise ProviderResponseError("Vision model did not return a JSON object")


def parse_vision_response(raw: str) -> VisionResult:
    """Turn raw model text into a VisionResult, tolerating fences and partial output."""
    payload = _extract_object(raw)
    try:
        return VisionResult.model_validate(payload)
    except ValidationError as exc:
        raise ProviderResponseError(f"Vision JSON failed validation: {exc}") from exc


async def analyze_image(image_b64: str) -> VisionResult:
    """Describe a base64 JPEG screenshot with the configured vision model."""
    settings = get_settings()
    prompt = build_vision_prompt(settings.ocr_engine)
    client = get_llm_client()
    raw = await client.describe_image(settings.vision_model, prompt, image_b64)
    return parse_vision_response(raw)