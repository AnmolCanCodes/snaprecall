"""GET /api/search."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.config import get_settings
from app.schemas import SearchResponse
from app.services.search import hybrid_search

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResponse)
async def search(
    q: Annotated[str, Query(max_length=500)] = "",
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> SearchResponse:
    """Hybrid keyword and semantic search. An empty query returns the newest screenshots."""
    return await hybrid_search(q, limit or get_settings().search_default_limit)