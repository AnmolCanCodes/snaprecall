"""Hybrid search: FTS5 keywords, sqlite-vec KNN and Reciprocal Rank Fusion."""

import asyncio
import logging
import sqlite3
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

import sqlite_vec

from app.config import get_settings
from app.db import connection
from app.schemas import ImageBase, MatchLeg, SearchHit, SearchResponse
from app.services.embeddings import embed_query
from app.services.llm_client import ProviderResponseError, ProviderUnavailableError

logger = logging.getLogger(__name__)

MAX_QUERY_TOKENS = 16

_KEYWORD_SQL = """
SELECT images.id AS id, snippet(images_fts, -1, '[[', ']]', '...', 12) AS snippet
FROM images_fts
JOIN images ON images.id = images_fts.rowid
WHERE images_fts MATCH ? AND images.status = 'done'
ORDER BY bm25(images_fts)
LIMIT ?
"""

_SEMANTIC_SQL = """
WITH knn AS (
    SELECT rowid, distance FROM vec_images WHERE embedding MATCH ? AND k = ?
)
SELECT knn.rowid AS id
FROM knn
JOIN images ON images.id = knn.rowid
WHERE images.status = 'done'
ORDER BY knn.distance
"""


@dataclass(frozen=True)
class FusedResult:
    """One image after rank fusion."""

    image_id: int
    score: float
    matched_by: tuple[MatchLeg, ...]


def sanitize_fts_query(raw: str) -> str:
    """Turn free text into a safe FTS5 expression of quoted prefix tokens joined by OR.

    Every character that is not a letter, digit or combining mark (which Devanagari
    vowel signs are) acts as a separator, so quotes and FTS operators cannot leak in.
    """
    cleaned = "".join(
        ch if ch.isalnum() or unicodedata.category(ch).startswith("M") else " " for ch in raw
    )
    tokens = cleaned.split()[:MAX_QUERY_TOKENS]
    return " OR ".join(f'"{token}"*' for token in tokens)


def rrf_fuse(
    keyword_ids: Sequence[int], semantic_ids: Sequence[int], k: int
) -> list[FusedResult]:
    """Merge two ranked id lists with Reciprocal Rank Fusion.

    Ties on score are broken by the better single-leg rank, then by higher id (newer).
    """
    scores: dict[int, float] = {}
    best_rank: dict[int, int] = {}
    legs: dict[int, list[MatchLeg]] = {}
    ranked: list[tuple[MatchLeg, Sequence[int]]] = [
        ("keyword", keyword_ids),
        ("semantic", semantic_ids),
    ]
    for leg, ids in ranked:
        seen: set[int] = set()
        rank = 0
        for image_id in ids:
            if image_id in seen:
                continue
            seen.add(image_id)
            rank += 1
            scores[image_id] = scores.get(image_id, 0.0) + 1.0 / (k + rank)
            best_rank[image_id] = min(best_rank.get(image_id, rank), rank)
            legs.setdefault(image_id, []).append(leg)
    ordered = sorted(
        scores, key=lambda image_id: (-scores[image_id], best_rank[image_id], -image_id)
    )
    return [FusedResult(i, scores[i], tuple(legs[i])) for i in ordered]


def keyword_candidates(fts_query: str, limit: int) -> list[tuple[int, str]]:
    """Return (image id, snippet) pairs ranked by bm25 for a sanitized query."""
    if not fts_query:
        return []
    try:
        with connection() as conn:
            rows = conn.execute(_KEYWORD_SQL, (fts_query, limit)).fetchall()
    except sqlite3.OperationalError as exc:
        logger.warning("Keyword search failed for %r: %s", fts_query, exc)
        return []
    return [(row["id"], row["snippet"]) for row in rows]


def semantic_candidates(vector: Sequence[float], limit: int) -> list[int]:
    """Return image ids ordered by vector distance."""
    with connection() as conn:
        rows = conn.execute(
            _SEMANTIC_SQL, (sqlite_vec.serialize_float32(list(vector)), limit)
        ).fetchall()
    return [row["id"] for row in rows]


async def _semantic_ids(query: str, limit: int) -> tuple[list[int], bool]:
    """Run the semantic leg. Returns (ids, degraded) and never raises for provider problems."""
    try:
        vector = await embed_query(query)
        return await asyncio.to_thread(semantic_candidates, vector, limit), False
    except ProviderUnavailableError:
        logger.info("Provider unavailable, using keyword search only")
    except ProviderResponseError as exc:
        logger.warning("Semantic search skipped: %s", exc)
    return [], True


def _recent_hits(limit: int) -> list[SearchHit]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM images WHERE status = 'done' "
            "ORDER BY indexed_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        SearchHit(image=ImageBase.from_row(row), score=0.0, matched_by=[], snippet=None)
        for row in rows
    ]


def _load_hits(fused: list[FusedResult], snippets: dict[int, str]) -> list[SearchHit]:
    if not fused:
        return []
    ids = [item.image_id for item in fused]
    placeholders = ",".join("?" * len(ids))
    with connection() as conn:
        rows = conn.execute(f"SELECT * FROM images WHERE id IN ({placeholders})", ids).fetchall()
    by_id = {row["id"]: row for row in rows}
    return [
        SearchHit(
            image=ImageBase.from_row(by_id[item.image_id]),
            score=item.score,
            matched_by=list(item.matched_by),
            snippet=snippets.get(item.image_id),
        )
        for item in fused
        if item.image_id in by_id
    ]


async def hybrid_search(query: str, limit: int) -> SearchResponse:
    """Search indexed screenshots by keywords and meaning, falling back to keywords only."""
    settings = get_settings()
    limit = max(1, limit)
    text = query.strip()
    if not text:
        recent = await asyncio.to_thread(_recent_hits, limit)
        return SearchResponse(query=query, total=len(recent), degraded=False, results=recent)

    candidates = settings.search_candidates
    keyword_rows, (semantic_ids, degraded) = await asyncio.gather(
        asyncio.to_thread(keyword_candidates, sanitize_fts_query(text), candidates),
        _semantic_ids(text, candidates),
    )
    fused = rrf_fuse([image_id for image_id, _ in keyword_rows], semantic_ids, settings.rrf_k)
    snippets = dict(keyword_rows)
    hits = await asyncio.to_thread(_load_hits, fused[:limit], snippets)
    return SearchResponse(query=query, total=len(hits), degraded=degraded, results=hits)