"""Folder scanning (backfill) and live filesystem watching."""

import asyncio
import logging
import os
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from app.config import get_settings
from app.db import connection, has_embedding_mismatch, transaction
from app.schemas import ScanResult
from app.utils.images import thumbnail_path

logger = logging.getLogger(__name__)

TEMP_SUFFIXES = (".tmp", ".part", ".partial", ".crdownload", ".download", ".swp", "~")
STABILITY_INTERVAL_SECONDS = 1.0
MAX_STABILITY_CHECKS = 120
MTIME_TOLERANCE = 1e-6

AsyncHandler = Callable[..., Coroutine[Any, Any, None]]


def _is_ignored_name(name: str) -> bool:
    """True for hidden files and common temporary or partial download names."""
    lowered = name.lower()
    return lowered.startswith((".", "~")) or lowered.endswith(TEMP_SUFFIXES)


def is_indexable(path: Path) -> bool:
    """Decide whether a path inside SCREENSHOT_DIR should be indexed."""
    settings = get_settings()
    root = settings.screenshot_dir
    if root is None:
        return False
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    if not settings.scan_recursive and len(relative.parts) > 1:
        return False
    if any(_is_ignored_name(part) for part in relative.parts):
        return False
    return path.suffix.lower() in settings.supported_suffixes


def _changed(row: object, size: int, mtime: float) -> bool:
    """Compare a stored row with the current size and mtime."""
    stored_size = row["size_bytes"]  # type: ignore[index]
    stored_mtime = row["mtime"]  # type: ignore[index]
    if stored_size != size or stored_mtime is None:
        return True
    return abs(stored_mtime - mtime) > MTIME_TOLERANCE


def _unlink_thumbnail(image_id: int) -> None:
    try:
        thumbnail_path(image_id).unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not remove thumbnail %d: %s", image_id, exc)


def _walk(
    root: Path, recursive: bool, suffixes: frozenset[str]
) -> tuple[dict[str, tuple[int, float]], bool]:
    """Single pass over the folder. Returns {path: (size, mtime)} and whether it was complete."""
    found: dict[str, tuple[int, float]] = {}
    complete = True
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if _is_ignored_name(entry.name):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if recursive:
                                pending.append(Path(entry.path))
                            continue
                        if os.path.splitext(entry.name)[1].lower() not in suffixes:
                            continue
                        info = entry.stat()
                    except OSError:
                        continue
                    found[entry.path] = (info.st_size, info.st_mtime)
        except OSError as exc:
            logger.warning("Could not read directory %s: %s", directory, exc)
            complete = False
    return found, complete


def scan_folder() -> ScanResult:
    """Reconcile the database with the screenshots folder in one directory walk."""
    if has_embedding_mismatch():
        logger.error("Scan skipped: database has embedding mismatch. Delete database to rebuild.")
        return ScanResult(added=0, requeued=0, removed=0, unchanged=0)

    settings = get_settings()
    root = settings.screenshot_dir
    if root is None or not root.is_dir() or not os.access(root, os.R_OK):
        logger.warning("Scan skipped: SCREENSHOT_DIR is not set, missing or unreadable")
        return ScanResult(added=0, requeued=0, removed=0, unchanged=0)

    found, complete = _walk(root, settings.scan_recursive, settings.supported_suffixes)
    new_rows: list[tuple[str, str, int, float]] = []
    changed: list[tuple[int, float, int]] = []
    removed_ids: list[int] = []

    with connection() as conn, transaction(conn):
        known = {
            row["path"]: row
            for row in conn.execute("SELECT id, path, size_bytes, mtime FROM images")
        }
        for path, (size, mtime) in found.items():
            row = known.get(path)
            if row is None:
                new_rows.append((path, os.path.basename(path), size, mtime))
            elif _changed(row, size, mtime):
                changed.append((size, mtime, row["id"]))
        if complete:
            removed_ids = [row["id"] for path, row in known.items() if path not in found]
        else:
            logger.warning("Scan was incomplete, skipping removal of missing files")

        conn.executemany(
            "INSERT INTO images(path, filename, size_bytes, mtime) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(path) DO NOTHING",
            new_rows,
        )
        conn.executemany(
            "UPDATE images SET size_bytes = ?, mtime = ?, status = 'pending', attempts = 0, "
            "error = NULL WHERE id = ?",
            changed,
        )
        conn.executemany(
            "DELETE FROM images WHERE id = ?", [(image_id,) for image_id in removed_ids]
        )

    for image_id in removed_ids:
        _unlink_thumbnail(image_id)
    result = ScanResult(
        added=len(new_rows),
        requeued=len(changed),
        removed=len(removed_ids),
        unchanged=len(found) - len(new_rows) - len(changed),
    )
    logger.info("Scan finished: %s", result.model_dump())
    return result


def upsert_path(path: Path) -> bool:
    """Insert or requeue one file. Returns True when the queue changed."""
    if has_embedding_mismatch():
        logger.error("Indexing skipped: database has embedding mismatch.")
        return False

    if not is_indexable(path):
        return False
    try:
        info = path.stat()
    except OSError:
        return False
    with connection() as conn, transaction(conn):
        row = conn.execute(
            "SELECT id, size_bytes, mtime FROM images WHERE path = ?", (str(path),)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO images(path, filename, size_bytes, mtime) VALUES (?, ?, ?, ?)",
                (str(path), path.name, info.st_size, info.st_mtime),
            )
            return True
        if not _changed(row, info.st_size, info.st_mtime):
            return False
        conn.execute(
            "UPDATE images SET size_bytes = ?, mtime = ?, status = 'pending', attempts = 0, "
            "error = NULL WHERE id = ?",
            (info.st_size, info.st_mtime, row["id"]),
        )
    return True


def remove_path(path: Path) -> bool:
    """Delete the row for a removed file. Returns True when a row existed."""
    with connection() as conn, transaction(conn):
        row = conn.execute("SELECT id FROM images WHERE path = ?", (str(path),)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM images WHERE id = ?", (row["id"],))
    _unlink_thumbnail(row["id"])
    return True


def move_path(source: Path, destination: Path) -> None:
    """Keep the index entry of a renamed file instead of re-indexing it."""
    with connection() as conn, transaction(conn):
        row = conn.execute("SELECT id FROM images WHERE path = ?", (str(source),)).fetchone()
        if row is None:
            return
        target_taken = conn.execute(
            "SELECT 1 FROM images WHERE path = ?", (str(destination),)
        ).fetchone()
        if is_indexable(destination) and target_taken is None:
            conn.execute(
                "UPDATE images SET path = ?, filename = ? WHERE id = ?",
                (str(destination), destination.name, row["id"]),
            )
            return
        conn.execute("DELETE FROM images WHERE id = ?", (row["id"],))
    _unlink_thumbnail(row["id"])


def _file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


async def _wait_until_stable(path: Path) -> bool:
    """Wait until the file size stays unchanged for one interval."""
    previous = -1
    for _ in range(MAX_STABILITY_CHECKS):
        size = await asyncio.to_thread(_file_size, path)
        if size is None:
            return False
        if size > 0 and size == previous:
            return True
        previous = size
        await asyncio.sleep(STABILITY_INTERVAL_SECONDS)
    return False


def _to_path(raw: str | bytes) -> Path:
    return Path(os.fsdecode(raw))


class _EventHandler(FileSystemEventHandler):
    """Forwards watchdog thread events to the asyncio loop."""

    def __init__(self, watcher: "FolderWatcher") -> None:
        self._watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._watcher.submit(self._watcher.handle_upsert, _to_path(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._watcher.submit(
                self._watcher.handle_move, _to_path(event.src_path), _to_path(event.dest_path)
            )

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._watcher.submit(self._watcher.handle_delete, _to_path(event.src_path))


class FolderWatcher:
    """Indexes new screenshots shortly after they finish being written."""

    def __init__(self, loop: asyncio.AbstractEventLoop, on_enqueued: Callable[[], None]) -> None:
        self._loop = loop
        self._on_enqueued = on_enqueued
        self._observer: BaseObserver | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._inflight: set[str] = set()

    def start(self) -> bool:
        """Begin watching SCREENSHOT_DIR. Returns False when it cannot be watched."""
        settings = get_settings()
        root = settings.screenshot_dir
        if root is None or not root.is_dir():
            logger.warning("Folder watcher not started: SCREENSHOT_DIR is not set or missing")
            return False
        observer = Observer()
        observer.schedule(_EventHandler(self), str(root), recursive=settings.scan_recursive)
        observer.start()
        self._observer = observer
        logger.info("Watching %s", root)
        return True

    def stop(self) -> None:
        """Stop the observer thread and cancel in-flight handlers."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        for task in list(self._tasks):
            task.cancel()

    def submit(self, handler: AsyncHandler, *args: Path) -> None:
        """Schedule an async handler on the event loop from the watchdog thread."""
        try:
            self._loop.call_soon_threadsafe(self._spawn, handler, *args)
        except RuntimeError:
            logger.debug("Event loop is closed, dropping filesystem event")

    def _spawn(self, handler: AsyncHandler, *args: Path) -> None:
        task = self._loop.create_task(handler(*args))
        self._tasks.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Watcher handler failed", exc_info=task.exception())

    async def handle_upsert(self, path: Path) -> None:
        """Enqueue a created or renamed file once its size has stopped changing."""
        key = str(path)
        if key in self._inflight or not is_indexable(path):
            return
        self._inflight.add(key)
        try:
            if await _wait_until_stable(path) and await asyncio.to_thread(upsert_path, path):
                self._on_enqueued()
        finally:
            self._inflight.discard(key)

    async def handle_delete(self, path: Path) -> None:
        """Drop the index entry of a deleted file."""
        await asyncio.to_thread(remove_path, path)

    async def handle_move(self, source: Path, destination: Path) -> None:
        """Carry the index entry over to a renamed file, then enqueue it if it is new."""
        await asyncio.to_thread(move_path, source, destination)
        await self.handle_upsert(destination)
