"""Throttled, resumable background worker that drains the pending queue."""

import asyncio
import datetime
import logging
from collections.abc import Awaitable, Callable

from app.config import get_settings
from app.db import connection, has_embedding_mismatch
from app.schemas import IndexStatus
from app.services.llm_client import get_daily_tracker
from app.services.pipeline import Outcome, get_last_retry_after, process_image

logger = logging.getLogger(__name__)

INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 120.0
DB_ERROR_PAUSE_SECONDS = 5.0

ProcessFn = Callable[[int], Awaitable[Outcome]]

_CLAIM_SQL = """
UPDATE images SET status = 'processing'
WHERE id = (
    SELECT id FROM images WHERE status = 'pending'
    ORDER BY mtime DESC, id DESC LIMIT 1
)
RETURNING id, filename
"""


def _seconds_until_local_midnight() -> float:
    """Calculate the seconds remaining until the next local midnight."""
    now = datetime.datetime.now().astimezone()
    tomorrow = now.date() + datetime.timedelta(days=1)
    midnight = datetime.datetime.combine(tomorrow, datetime.time.min, tzinfo=now.tzinfo)
    return max(1.0, (midnight - now).total_seconds())


def _claim_next() -> tuple[int, str] | None:
    """Atomically move the newest pending image to processing and return it."""
    with connection() as conn:
        rows = conn.execute(_CLAIM_SQL).fetchall()
    return (rows[0]["id"], rows[0]["filename"]) if rows else None


def _count_by_status() -> dict[str, int]:
    counts = {"pending": 0, "processing": 0, "done": 0, "failed": 0}
    with connection() as conn:
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM images GROUP BY status"):
            counts[row["status"]] = row["n"]
    return counts


class IndexWorker:
    """Processes one image at a time, newest first, with a pause between images."""

    def __init__(self, process: ProcessFn = process_image) -> None:
        self._process = process
        self._task: asyncio.Task[None] | None = None
        self._midnight_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._running = asyncio.Event()
        self._running.set()
        self._paused_reason: str | None = None
        self._current_filename: str | None = None
        self._provider_ok = True

    def start(self) -> None:
        """Start the background loop on the running event loop."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="index-worker")
        self._midnight_task = asyncio.create_task(
            self._midnight_watcher(), name="midnight-watcher"
        )

    async def stop(self) -> None:
        """Ask the loop to exit and wait for the current image to finish."""
        self._stop.set()
        self._wake.set()
        self._running.set()
        if self._midnight_task is not None:
            self._midnight_task.cancel()
            self._midnight_task = None
        if self._task is not None:
            await self._task
            self._task = None

    def pause(self, reason: str = "user") -> None:
        """Stop claiming new images after the current one finishes."""
        self._paused_reason = reason
        self._running.clear()

    def resume(self) -> None:
        """Continue claiming images and clear any paused reason."""
        self._paused_reason = None
        self._running.set()
        self._wake.set()

    def notify(self) -> None:
        """Wake an idle worker because new work was enqueued."""
        self._wake.set()

    async def status(self) -> IndexStatus:
        """Return queue counts and live worker state."""
        counts = await asyncio.to_thread(_count_by_status)
        is_paused = not self._running.is_set()
        return IndexStatus(
            pending=counts["pending"],
            processing=counts["processing"],
            done=counts["done"],
            failed=counts["failed"],
            total=sum(counts.values()),
            current_filename=self._current_filename,
            paused=is_paused,
            paused_reason=self._paused_reason if is_paused else None,
            provider_ok=self._provider_ok,
            requests_today=get_daily_tracker().requests_today,
        )

    async def _sleep(self, seconds: float) -> None:
        """Sleep that returns early when the worker is asked to stop."""
        if seconds <= 0:
            return
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except TimeoutError:
            return

    async def _midnight_watcher(self) -> None:
        """Background monitor that sleeps until local midnight and auto-resumes."""
        while not self._stop.is_set():
            wait_seconds = _seconds_until_local_midnight()
            await self._sleep(wait_seconds)
            if self._stop.is_set():
                break
            get_daily_tracker().reset()
            if self._paused_reason in ("quota_exhausted", "daily_budget"):
                logger.info(
                    "Local midnight reached; resetting daily quota counter and resuming worker"
                )
                self.resume()

    async def _safe_process(self, image_id: int) -> Outcome:
        try:
            return await self._process(image_id)
        except Exception:
            logger.exception("Unexpected error while processing image %d", image_id)
            return Outcome.ERROR

    async def _run(self) -> None:
        backoff = 0.0
        logger.info("Index worker started")
        while not self._stop.is_set():
            if has_embedding_mismatch():
                self.pause(reason="embedding_mismatch")
                await self._sleep(DB_ERROR_PAUSE_SECONDS)
                continue

            settings = get_settings()
            budget = settings.daily_request_budget
            if budget > 0 and get_daily_tracker().requests_today >= budget:
                logger.info(
                    "Daily request budget (%d) reached. Pausing worker until midnight or resume.",
                    budget,
                )
                self.pause(reason="daily_budget")

            await self._running.wait()
            if self._stop.is_set():
                break

            self._wake.clear()
            try:
                claimed = await asyncio.to_thread(_claim_next)
            except Exception:
                logger.exception("Could not claim the next image")
                await self._sleep(DB_ERROR_PAUSE_SECONDS)
                continue

            if claimed is None:
                self._current_filename = None
                await self._wake.wait()
                continue

            image_id, filename = claimed
            self._current_filename = filename
            outcome = await self._safe_process(image_id)
            self._current_filename = None

            if outcome is Outcome.PROVIDER_DOWN:
                self._provider_ok = False
                backoff = min(max(backoff * 2, INITIAL_BACKOFF_SECONDS), MAX_BACKOFF_SECONDS)
                logger.warning("Provider unavailable, retrying in %.0f seconds", backoff)
                await self._sleep(backoff)
                continue

            if outcome is Outcome.RATE_LIMITED:
                self._provider_ok = True
                retry_after = get_last_retry_after()
                cur_backoff = backoff * 2 if backoff > 0 else INITIAL_BACKOFF_SECONDS
                backoff = min(max(retry_after or 0.0, cur_backoff), MAX_BACKOFF_SECONDS)
                logger.warning(
                    "Rate limit hit, backing off for %.1f seconds without counting failure",
                    backoff,
                )
                await self._sleep(backoff)
                continue

            if outcome is Outcome.QUOTA_EXHAUSTED:
                self._provider_ok = True
                logger.warning(
                    "Quota exhausted. Pausing worker automatically until midnight or resume."
                )
                self.pause(reason="quota_exhausted")
                continue

            self._provider_ok = True
            backoff = 0.0
            await self._sleep(get_settings().worker_throttle_seconds)

        logger.info("Index worker stopped")