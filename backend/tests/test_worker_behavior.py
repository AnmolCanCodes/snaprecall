"""Unit tests for worker backoff, rate limits, daily budget, and embedding mismatch."""

import asyncio

import pytest

from app.db import connection, get_embedding_mismatch, has_embedding_mismatch, init_db
from app.services.embeddings import embed_documents
from app.services.llm_client import (
    ProviderResponseError,
    QuotaExhaustedError,
    RateLimitError,
    get_daily_tracker,
)
from app.services.pipeline import Outcome, process_image
from app.services.worker import IndexWorker


def _row(image_id: int):
    with connection() as conn:
        return conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()


@pytest.mark.asyncio
async def test_dimension_mismatch_raises_provider_response_error(monkeypatch) -> None:
    class BadDimClient:
        async def embed(self, model: str, texts: list[str], task: str = "document"):
            # Return 3 dimensions when EMBEDDING_DIM is 4
            return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr("app.services.embeddings.get_llm_client", lambda: BadDimClient())

    with pytest.raises(ProviderResponseError) as exc_info:
        await embed_documents(["Hello world"])
    assert "dimensions but EMBEDDING_DIM is 4" in str(exc_info.value)


@pytest.mark.asyncio
async def test_pipeline_rate_limit_error_requeues_without_failing(
    add_image, make_png, shots_dir, monkeypatch
) -> None:
    image_id = add_image(str(make_png(shots_dir / "rate.png")))

    async def mock_index(img_id, path):
        raise RateLimitError("Too Many Requests", retry_after_seconds=15.0)

    monkeypatch.setattr("app.services.pipeline._index", mock_index)

    outcome = await process_image(image_id)
    assert outcome is Outcome.RATE_LIMITED

    row = _row(image_id)
    assert row["status"] == "pending"
    assert row["attempts"] == 0


@pytest.mark.asyncio
async def test_pipeline_quota_exhausted_requeues_without_failing(
    add_image, make_png, shots_dir, monkeypatch
) -> None:
    image_id = add_image(str(make_png(shots_dir / "quota.png")))

    async def mock_index(img_id, path):
        raise QuotaExhaustedError("Daily quota exhausted")

    monkeypatch.setattr("app.services.pipeline._index", mock_index)

    outcome = await process_image(image_id)
    assert outcome is Outcome.QUOTA_EXHAUSTED

    row = _row(image_id)
    assert row["status"] == "pending"
    assert row["attempts"] == 0


@pytest.mark.asyncio
async def test_worker_daily_budget_pause(add_image, make_png, shots_dir, monkeypatch) -> None:
    tracker = get_daily_tracker()
    tracker.reset()

    monkeypatch.setenv("DAILY_REQUEST_BUDGET", "2")
    from app.config import get_settings

    get_settings.cache_clear()

    # Artificially simulate 2 requests already made today
    tracker.increment()
    tracker.increment()

    worker = IndexWorker()
    worker.start()

    # Enqueue an image
    add_image(str(make_png(shots_dir / "item.png")))
    worker.notify()

    # Give worker a moment to notice budget
    await asyncio.sleep(0.1)

    status = await worker.status()
    assert status.paused is True
    assert status.paused_reason == "daily_budget"
    assert status.requests_today == 2

    # Verify resume clears paused_reason
    worker.resume()
    status_resumed = await worker.status()
    assert status_resumed.paused is False
    assert status_resumed.paused_reason is None

    await worker.stop()
    tracker.reset()


@pytest.mark.asyncio
async def test_worker_quota_exhausted_pause(add_image, make_png, shots_dir, monkeypatch) -> None:
    image_id = add_image(str(make_png(shots_dir / "item_q.png")))

    async def mock_process(img_id):
        return Outcome.QUOTA_EXHAUSTED

    worker = IndexWorker(process=mock_process)
    worker.start()
    worker.notify()

    await asyncio.sleep(0.1)

    status = await worker.status()
    assert status.paused is True
    assert status.paused_reason == "quota_exhausted"

    row = _row(image_id)
    assert row is not None
    await worker.stop()


def test_embedding_mismatch_detected_on_init_db(monkeypatch, client) -> None:
    from app.config import get_settings

    # Database was initialized with embedding_model="embeddinggemma" and embedding_dim=4
    # Now simulate setting config to a different model and dimension
    monkeypatch.setenv("EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setenv("EMBEDDING_DIM", "768")
    get_settings.cache_clear()

    init_db()

    assert has_embedding_mismatch() is True
    mismatch_detail = get_embedding_mismatch()
    assert mismatch_detail is not None
    assert "embedding_mismatch" in mismatch_detail

    # Health check must report degraded and embedding_mismatch=True
    health_resp = client.get("/api/health").json()
    assert health_resp["status"] == "degraded"
    assert health_resp["embedding_mismatch"] is True
