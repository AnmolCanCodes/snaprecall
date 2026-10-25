"""Pydantic models shared by the API and the services."""

import json
import sqlite3
from typing import Literal, Self

from pydantic import BaseModel, Field

ImageStatus = Literal["pending", "processing", "done", "failed"]
MatchLeg = Literal["keyword", "semantic"]


def parse_tags(raw: str | None) -> list[str]:
    """Decode the JSON tags column into a list of strings, tolerating bad data."""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [tag for tag in value if isinstance(tag, str)]


class ErrorResponse(BaseModel):
    """Body shape used by every error response."""

    detail: str


class ImageBase(BaseModel):
    """Image fields needed by the search grid."""

    id: int
    filename: str
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    status: ImageStatus
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    app_type: str = ""
    visible_text: str = ""
    created_at: str
    indexed_at: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Self:
        """Build a model from a database row that includes every field of the model."""
        data = {key: row[key] for key in row.keys() if key in cls.model_fields}  # noqa: SIM118
        data["tags"] = parse_tags(row["tags"])
        return cls.model_validate(data)


class ImageDetail(ImageBase):
    """Full metadata for one image."""

    ocr_text: str = ""
    attempts: int = 0
    error: str | None = None


class SearchHit(BaseModel):
    """One ranked search result."""

    image: ImageBase
    score: float
    matched_by: list[MatchLeg]
    snippet: str | None = None


class SearchResponse(BaseModel):
    """Result of a hybrid search."""

    query: str
    total: int
    degraded: bool = False
    results: list[SearchHit]


class ComponentCheck(BaseModel):
    """Outcome of one health probe."""

    ok: bool
    detail: str | None = None


class HealthResponse(BaseModel):
    """Aggregate health report."""

    status: Literal["ok", "degraded"]
    provider_name: str
    key_configured: bool
    database: ComponentCheck
    provider: ComponentCheck
    vision_model: ComponentCheck
    embedding_model: ComponentCheck
    tesseract: ComponentCheck
    screenshot_dir: ComponentCheck
    requests_today: int = 0
    paused_reason: str | None = None
    embedding_mismatch: bool = False


class IndexStatus(BaseModel):
    """Live state of the indexing queue and worker."""

    pending: int
    processing: int
    done: int
    failed: int
    total: int
    current_filename: str | None = None
    paused: bool
    paused_reason: str | None = None
    provider_ok: bool
    requests_today: int = 0


class ScanResult(BaseModel):
    """Summary of a folder scan."""

    added: int
    requeued: int
    removed: int
    unchanged: int